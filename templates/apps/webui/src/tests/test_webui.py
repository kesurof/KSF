import json
import asyncio
import os
import subprocess
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient
from fastapi.responses import JSONResponse

from webui.api import router_apps
from webui.api import router_logs
from webui.api import router_operations
from webui.api import router_status
from webui.core import ksf_cli
from webui.core import jobs
from webui.core.schemas import ConfigureRequest, ConfirmRequest, InstallRequest, OperationRequest
from webui.core.state import AppRecord, parse_env_file
from webui.core.validation import validate_host, validate_instance, validate_port
from webui.main import app


class ValidationTests(unittest.TestCase):
    def test_instance_validation_rejects_path_traversal(self):
        with self.assertRaises(ValueError):
            validate_instance("../outside")

    def test_port_validation_rejects_invalid_port(self):
        with self.assertRaises(ValueError):
            validate_port("70000")

    def test_host_validation_accepts_fqdn(self):
        self.assertEqual(validate_host("app.example.com"), "app.example.com")

    def test_install_request_accepts_internal_port_override(self):
        request = InstallRequest(template="radarr", port="17878")
        self.assertEqual(request.port, "17878")


class OperationTests(unittest.TestCase):
    def test_sensitive_operation_requires_confirmation(self):
        response = router_operations.restart_infrastructure(
            OperationRequest(confirmed=False)
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("Confirmation", response.body.decode())


class HttpSecurityTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.headers = {"host": "webui.example.com", "origin": "https://webui.example.com"}

    def test_mutation_without_origin_or_referer_is_rejected(self):
        response = self.client.post("/api/operations/render", json={"confirmed": True})
        self.assertEqual(response.status_code, 400)

    def test_mutation_rejects_origin_that_only_contains_host(self):
        response = self.client.post(
            "/api/operations/render", headers={"host": "webui.example.com", "origin": "https://webui.example.com.attacker.test"},
            json={"confirmed": True},
        )
        self.assertEqual(response.status_code, 400)

    def test_mutation_with_valid_origin_still_requires_server_confirmation(self):
        response = self.client.post("/api/operations/render", headers=self.headers, json={})
        self.assertEqual(response.status_code, 422)

    def test_openapi_is_disabled_in_production(self):
        response = self.client.get("/openapi.json")
        self.assertEqual(response.status_code, 404)

    @patch("webui.api.router_apps.get_installed_app")
    def test_webui_rebuild_is_refused(self, get_installed_app):
        get_installed_app.return_value = SimpleNamespace(disabled=False)
        response = self.client.post("/api/apps/webui/rebuild", headers=self.headers, json={"confirmed": True})
        self.assertEqual(response.status_code, 403)
        self.assertIn("ne peut pas se reconstruire", response.json()["error"])

    @patch("webui.api.router_operations.start_job", return_value=(42, ""))
    def test_confirmed_operation_creates_job(self, start_job):
        response = router_operations.restart_infrastructure(
            OperationRequest(confirmed=True)
        )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(json.loads(response.body)["job_id"], 42)
        start_job.assert_called_once()

    def test_dry_run_is_rejected_for_unsupported_operation(self):
        response = router_operations._queue("crowdsec-enroll", "crowdsec", (), OperationRequest(confirmed=True, dry_run=True))
        self.assertEqual(response.status_code, 422)


class KsfCliTests(unittest.TestCase):
    def test_missing_embedded_cli_is_reported(self):
        with patch.object(ksf_cli, "CLI_DIR", Path("/missing/ksf")):
            code, _, error = ksf_cli.run_ksf("render")
        self.assertEqual(code, -1)
        self.assertIn("introuvables", error)

    def test_dns_rejects_an_invalid_host_before_shell_execution(self):
        code, _, error = ksf_cli.run_dns("ensure", "bad host; rm -rf /")
        self.assertEqual(code, -1)
        self.assertIn("invalide", error)

    def test_dry_run_argument_is_positioned_before_yes(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "ksf.sh"
            script.touch()
            result = SimpleNamespace(returncode=0, stdout="[DRY-RUN]", stderr="")
            with patch.object(ksf_cli, "CLI_DIR", Path(tmp)), patch("subprocess.run", return_value=result) as run:
                ksf_cli.run_ksf("render", dry_run=True)
            command = run.call_args.args[0]
            self.assertEqual(command[-2:], ["--dry-run", "--yes"])

    def test_app_yes_requires_server_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "app.sh"
            script.touch()
            result = SimpleNamespace(returncode=0, stdout="", stderr="")
            with patch.object(ksf_cli, "CLI_DIR", Path(tmp)), patch("subprocess.run", return_value=result) as run:
                ksf_cli.run_app("disable", "films")
                self.assertNotIn("--yes", run.call_args.args[0])
                ksf_cli.run_app("remove", "films", confirmed=True, remove_data=True)
            command = run.call_args.args[0]
            self.assertEqual(command[-1], "--yes")
            self.assertEqual(run.call_args.kwargs["env"]["APP_REMOVE_DELETE_DATA"], "true")


class AppMutationParityTests(unittest.TestCase):
    def _config(self):
        return SimpleNamespace(domains=["example.com"], has_oauth2=lambda: True)

    def _start_job(self, action, target, runner):
        runner()
        return 42, ""

    def test_each_template_install_is_delegated_to_the_cli(self):
        templates_dir = Path(__file__).parents[3]
        for template in ("dockge", "radarr", "webui", "wordpress"):
            with self.subTest(template=template):
                values = parse_env_file(templates_dir / template / "app.env")
                self.assertTrue(values["APP_DOCKER_SERVICE"])
                request = InstallRequest(
                    template=template,
                    instance=f"{template}-test",
                    host=f"{template}.example.com",
                    no_auth=True,
                )
                with patch("webui.api.router_apps.get_config", return_value=self._config()), \
                     patch("webui.api.router_apps.get_template", return_value={"name": template}), \
                     patch("webui.api.router_apps.get_installed_app", return_value=None), \
                     patch("webui.api.router_apps.start_job", side_effect=self._start_job), \
                     patch("webui.api.router_apps.run_app", return_value=(0, "", "")) as run_app:
                    response = router_apps.install_app(request)
                self.assertEqual(response.status_code, 202)
                self.assertEqual(run_app.call_args.args[:4], ("install", template, "--instance", f"{template}-test"))
                self.assertIn("--host", run_app.call_args.args)
                self.assertTrue(run_app.call_args.kwargs["confirmed"])

    def test_disabled_enable_reinstalls_through_the_cli_fallback(self):
        app = AppRecord(
            instance="films", template="radarr", port="7878", host="films.example.com",
            protected=True, disabled=True,
        )
        with patch("webui.api.router_apps.get_installed_app", return_value=app), \
             patch("webui.api.router_apps.start_job", side_effect=self._start_job), \
             patch("webui.api.router_apps.run_app", return_value=(0, "", "")) as run_app:
            response = router_apps.enable_app("films")
        self.assertEqual(response.status_code, 202)
        self.assertEqual(
            run_app.call_args.args,
            ("install", "radarr", "--instance", "films", "--port", "7878",
             "--host", "films.example.com", "--auth", "--force"),
        )
        self.assertTrue(run_app.call_args.kwargs["confirmed"])

    def test_disabled_start_reinstalls_through_the_cli_fallback(self):
        app = AppRecord(
            instance="films", template="radarr", port="7878", host="films.example.com",
            protected=True, disabled=True,
        )
        with patch("webui.api.router_apps.get_installed_app", return_value=app), \
             patch("webui.api.router_apps.start_job", side_effect=self._start_job), \
             patch("webui.api.router_apps.run_app", return_value=(0, "", "")) as run_app:
            response = router_apps.start_app("films")
        self.assertEqual(response.status_code, 202)
        self.assertEqual(
            run_app.call_args.args,
            ("install", "radarr", "--instance", "films", "--port", "7878",
             "--host", "films.example.com", "--auth", "--force"),
        )

    def test_configure_requires_server_confirmation_and_delegates_to_cli(self):
        app = AppRecord(instance="films", template="radarr", domain="example.com",
                        subdomain="films", host="films.example.com")
        with patch("webui.api.router_apps.get_installed_app", return_value=app), \
             patch("webui.api.router_apps.get_config", return_value=self._config()), \
             patch("webui.api.router_apps.start_job", side_effect=self._start_job), \
             patch("webui.api.router_apps.run_app", return_value=(0, "", "")) as run_app:
            refused = router_apps.configure_app("films", ConfigureRequest(subdomain="cinema"))
            response = router_apps.configure_app(
                "films", ConfigureRequest(subdomain="cinema", confirmed=True)
            )
        self.assertEqual(refused.status_code, 422)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(run_app.call_args.args, ("configure", "films", "--subdomain", "cinema"))
        self.assertTrue(run_app.call_args.kwargs["confirmed"])

    def test_local_only_configuration_omits_public_access_overrides(self):
        app = AppRecord(instance="films", template="radarr", domain="example.com",
                        subdomain="films", host="films.example.com", host_port="17878")
        with patch("webui.api.router_apps.get_installed_app", return_value=app), \
             patch("webui.api.router_apps.get_config", return_value=self._config()), \
             patch("webui.api.router_apps.start_job", side_effect=self._start_job), \
             patch("webui.api.router_apps.run_app", return_value=(0, "", "")) as run_app:
            response = router_apps.configure_app(
                "films", ConfigureRequest(domain="example.com", subdomain="films",
                                          host="films.example.com", host_port="17878",
                                          local_only=True, confirmed=True)
            )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(
            run_app.call_args.args,
            ("configure", "films", "--host-port", "17878", "--local-only"),
        )

    def test_update_all_passes_server_confirmation_to_each_app(self):
        apps = [AppRecord(instance="films", template="radarr")]
        captured = []

        def runner_job(_action, _target, runner, **_kwargs):
            runner()
            return 42, ""

        with patch("webui.api.router_operations.list_installed_apps", return_value=apps), \
             patch("webui.api.router_operations.start_job", side_effect=runner_job), \
             patch("webui.api.router_operations.run_app", return_value=(0, "", "")) as run_app, \
             patch("webui.api.router_operations.run_ksf", return_value=(0, "", "")):
            response = router_operations.update_all_apps(OperationRequest(confirmed=True))
            captured.append(run_app.call_args)
        self.assertEqual(response.status_code, 202)
        self.assertTrue(captured[0].kwargs["confirmed"])

    def test_update_is_not_queued_without_server_confirmation(self):
        app = AppRecord(instance="films", template="radarr")
        with patch("webui.api.router_apps.get_installed_app", return_value=app), \
             patch("webui.api.router_apps.start_job") as start_job:
            response = router_apps.update_app("films", ConfirmRequest(confirmed=False))
        self.assertEqual(response.status_code, 422)
        start_job.assert_not_called()

    def test_router_has_no_direct_application_mutation_primitives(self):
        source = Path(router_apps.__file__).read_text()
        for primitive in (
            "render_app_route", "remove_route", "run_dns", "compose_up",
            "compose_down", "compose_build", "compose_pull", "compose_restart",
            "write_text", "mkdir", "rmtree", "unlink", "subprocess",
        ):
            self.assertNotIn(primitive, source)


class DoctorTests(unittest.TestCase):
    def _cfg(self, traefik=True, crowdsec=False, oauth=False):
        return SimpleNamespace(has_traefik=lambda: traefik, has_crowdsec=lambda: crowdsec, has_oauth2=lambda: oauth)

    def test_middlewares_present_and_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            dynamic = Path(tmp) / "dynamic"
            dynamic.mkdir()
            (dynamic / "middleware.yml").write_text("http:\n  middlewares:\n    oauth2-chain:\n      chain: {}\n")
            (dynamic / "route.yml").write_text("middlewares:\n  - oauth2-chain\n  - missing-chain\n")
            checks = []
            with patch.object(router_status, "TRAEFIK_DIR", Path(tmp)):
                router_status._doctor_middlewares(self._cfg(oauth=True), lambda *item: checks.append(item))
            self.assertIn(("ok", "Middleware Traefik", "oauth2-chain"), checks)
            self.assertIn(("err", "Middleware Traefik absent", "missing-chain"), checks)

    def test_access_log_states(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checks = []
            with patch.object(router_status, "TRAEFIK_DIR", root):
                router_status._doctor_access_log(self._cfg(), lambda *item: checks.append(item), now=100)
                (root / "logs").mkdir()
                log = root / "logs" / "access.log"
                log.touch()
                router_status._doctor_access_log(self._cfg(), lambda *item: checks.append(item), now=100)
                log.write_text("request\n")
                os.utime(log, (90, 90))
                router_status._doctor_access_log(self._cfg(), lambda *item: checks.append(item), now=100)
            self.assertTrue(any(item[0] == "err" for item in checks))
            self.assertTrue(any(item[0] == "warn" for item in checks))
            self.assertTrue(any(item[0] == "ok" for item in checks))

    def test_container_states_and_isolated_sdk_error(self):
        healthy = SimpleNamespace(attrs={"State": {"Status": "running", "Health": {"Status": "healthy"}, "RestartCount": 0}, "Config": {"Image": "traefik:v3"}, "Image": "sha256:1"}, image=SimpleNamespace(attrs={"RepoDigests": ["traefik@sha256:1"]}, tags=["traefik:v3"]))
        stopped = SimpleNamespace(attrs={"State": {"Status": "exited", "RestartCount": 0}, "Config": {"Image": "oauth:v1"}, "Image": "sha256:2"}, image=SimpleNamespace(attrs={"RepoDigests": []}, tags=["oauth:v1"]))
        client = Mock()
        client.containers.get.side_effect = [healthy, stopped, RuntimeError("missing")]
        docker = SimpleNamespace(available=lambda: True, client=client)
        checks = []
        router_status._doctor_containers(self._cfg(traefik=True, oauth=True, crowdsec=True), docker, lambda *item: checks.append(item))
        self.assertTrue(any(item[0] == "err" and "OAuth2" in item[1] for item in checks))
        self.assertTrue(any(item[0] == "warn" and "CrowdSec" in item[1] for item in checks))

    def test_app_compose_continues_after_failure(self):
        apps = [SimpleNamespace(instance="bad", app_dir="/bad"), SimpleNamespace(instance="good", app_dir="/good")]
        docker = Mock()
        docker.compose_run.side_effect = [(1, "", "invalid"), (0, "", "")]
        checks = []
        with patch("webui.api.router_status.list_installed_apps", return_value=apps), patch("webui.api.router_status.Path.is_file", return_value=True):
            router_status._doctor_apps(docker, lambda *item: checks.append(item))
        self.assertEqual(len(checks), 2)
        self.assertEqual(checks[0][0], "err")
        self.assertEqual(checks[1][0], "ok")

    def test_image_comparison_states(self):
        checks = []
        same = SimpleNamespace(attrs={"Config": {"Image": "app:v1"}, "Image": "sha"}, image=SimpleNamespace(attrs={"RepoDigests": ["app@sha256:1"]}, tags=["app:v1"]))
        different = SimpleNamespace(attrs={"Config": {"Image": "app:v1"}, "Image": "sha"}, image=SimpleNamespace(attrs={"RepoDigests": []}, tags=["app:v2"]))
        latest = SimpleNamespace(attrs={"Config": {"Image": "app:latest"}, "Image": "sha"}, image=SimpleNamespace(attrs={"RepoDigests": []}, tags=[]))
        for container in (same, different, latest): router_status._doctor_image(container, "test", lambda *item: checks.append(item))
        self.assertEqual(checks[0][0], "ok")
        self.assertEqual(checks[1][0], "err")
        self.assertEqual(checks[2][0], "warn")


class JobTests(unittest.TestCase):
    def _with_database(self):
        tmp = tempfile.TemporaryDirectory()
        return tmp, patch.dict(os.environ, {"KSF_WEBUI_DB_PATH": str(Path(tmp.name) / "jobs.db")})

    def test_dry_run_job_is_marked_and_redacts_token(self):
        done = threading.Event()
        updates = []
        async def create(*args, **kwargs): return 7
        async def update(*args):
            updates.append(args)
            if args[1] in {"completed", "failed"}: done.set()
        with patch("webui.core.jobs.create_job", create), patch("webui.core.jobs.update_job", update):
            job_id, error = jobs.start_job("render", "platform", lambda: (0, "token-value\n[DRY-RUN]", ""), dry_run=True, secrets=("token-value",))
            self.assertEqual((job_id, error), (7, ""))
            self.assertTrue(done.wait(2))
        self.assertTrue(any("******" in str(update) for update in updates))
        self.assertTrue(any(update[2] == "Simulation terminee" for update in updates if len(update) > 2))

    def test_empty_database_is_initialized_with_secure_permissions(self):
        tmp, environment = self._with_database()
        with tmp, environment:
            job_id = asyncio.run(jobs.create_job("render", "platform"))
            path = jobs.get_db_path()
            self.assertEqual(job_id, 1)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
            with sqlite3.connect(path) as db:
                versions = [row[0] for row in db.execute("SELECT version FROM schema_migrations")]
            self.assertEqual(versions, [1, 2, 3])

    def test_populated_legacy_database_is_upgraded_and_backed_up(self):
        tmp, environment = self._with_database()
        with tmp, environment:
            path = jobs.get_db_path()
            with sqlite3.connect(path) as db:
                db.execute("""CREATE TABLE jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT NOT NULL,
                    target TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                    message TEXT DEFAULT '', result TEXT DEFAULT '', created_at REAL NOT NULL,
                    finished_at REAL)""")
                db.execute("INSERT INTO jobs (action, target, status, created_at) VALUES ('a', 'same', 'running', 1)")
                db.execute("INSERT INTO jobs (action, target, status, created_at) VALUES ('b', 'same', 'pending', 2)")
            asyncio.run(jobs.list_recent_jobs())
            backups = list(path.parent.glob("jobs.db.v3.pre-migration-*.bak"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].stat().st_mode & 0o777, 0o600)
            with sqlite3.connect(backups[0]) as backup:
                backed_up_active = backup.execute(
                    "SELECT COUNT(*) FROM jobs WHERE status IN ('pending', 'running')"
                ).fetchone()[0]
            with sqlite3.connect(path) as db:
                active = db.execute("SELECT action FROM jobs WHERE status IN ('pending', 'running')").fetchall()
                dry_run = [row[1] for row in db.execute("PRAGMA table_info(jobs)")]
            self.assertEqual(active, [("b",)])
            self.assertIn("dry_run", dry_run)
            self.assertEqual(backed_up_active, 2)

    def test_failed_migration_rolls_back_its_schema_version(self):
        tmp, environment = self._with_database()

        async def broken_migration(_db):
            raise RuntimeError("migration failed")

        with tmp, environment, patch.object(jobs, "MIGRATIONS", [(1, False, broken_migration)]):
            with self.assertRaisesRegex(RuntimeError, "migration failed"):
                asyncio.run(jobs.create_job("render", "platform"))
            with sqlite3.connect(jobs.get_db_path()) as db:
                applied = db.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
            self.assertEqual(applied, 0)

    def test_sqlite_lock_blocks_concurrent_jobs_for_the_same_target(self):
        tmp, environment = self._with_database()
        with tmp, environment:
            async def create_twice():
                # Initialize migrations before exercising only the job-level lock.
                await jobs.create_job("seed", "seed-target")
                return await asyncio.gather(
                    jobs.create_job("render", "platform"),
                    jobs.create_job("render", "platform"),
                    return_exceptions=True,
                )

            results = asyncio.run(create_twice())
            self.assertEqual(sum(isinstance(item, int) for item in results), 1)
            self.assertEqual(sum(isinstance(item, sqlite3.IntegrityError) for item in results), 1)

    def test_retention_removes_only_old_finished_jobs(self):
        tmp, environment = self._with_database()
        with tmp, environment, patch.dict(os.environ, {"KSF_WEBUI_JOB_RETENTION_DAYS": "1"}):
            first = asyncio.run(jobs.create_job("old", "old-target"))
            asyncio.run(jobs.update_job(first, "completed"))
            with sqlite3.connect(jobs.get_db_path()) as db:
                db.execute("UPDATE jobs SET finished_at = ? WHERE id = ?", (time.time() - 172800, first))
            asyncio.run(jobs.create_job("new", "new-target"))
            self.assertIsNone(asyncio.run(jobs.get_job(first)))

    def test_job_redaction_covers_configured_and_named_secrets(self):
        with patch("webui.core.config.get_config", return_value=SimpleNamespace(env={"CF_API_KEY": "known-secret"})):
            self.assertNotIn("known-secret", jobs.redact_secrets("CF_API_KEY=known-secret"))
            self.assertNotIn("other-secret", jobs.redact_secrets("OAUTH2_CLIENT_SECRET=other-secret"))


class ContainerSecurityTests(unittest.TestCase):
    def test_webui_socket_and_runtime_are_explicit_administrative_mounts(self):
        compose = Path(__file__).parents[2] / "compose.yml"
        source = compose.read_text()
        self.assertIn("user: \"${APP_PUID}:${APP_PGID}\"", source)
        self.assertIn("/var/run/docker.sock:/var/run/docker.sock:rw", source)
        self.assertIn("${BASE_DIR}:${BASE_DIR}:rw", source)


class LogRedactionTests(unittest.TestCase):
    @patch("webui.api.router_logs.get_docker")
    @patch("pathlib.Path.exists", return_value=True)
    @patch("webui.core.config.get_config", return_value=SimpleNamespace(env={"CF_API_KEY": "known-secret"}))
    def test_logs_do_not_return_configured_secrets(self, _config, _exists, get_docker):
        get_docker.return_value.compose_logs.return_value = "CF_API_KEY=known-secret"

        response = router_logs.get_logs("traefik")

        self.assertNotIn("known-secret", response["logs"])
        self.assertIn("******", response["logs"])


class RouteTests(unittest.TestCase):
    def test_platform_operation_routes_are_registered(self):
        paths = {route.path for route in app.routes if hasattr(route, "path")}
        for route in app.routes:
            if not hasattr(route, "original_router"):
                continue
            prefix = route.include_context.prefix
            paths.update(prefix + child.path for child in route.original_router.routes)
        self.assertIn("/api/operations/render", paths)
        self.assertIn("/api/operations/apps/update-all", paths)
        self.assertIn("/apps/install", paths)


class AppListTests(unittest.TestCase):
    @patch("webui.api.router_apps.get_docker")
    @patch("webui.api.router_apps.list_installed_apps")
    def test_list_apps_exposes_table_fields(self, list_installed, get_docker):
        list_installed.return_value = [
            AppRecord(instance="films", template="radarr", host="films.example.com", host_port="17878")
        ]
        get_docker.return_value.stack_state.return_value = {
            "state": "running", "running": 1, "total": 1, "services": []
        }

        payload = router_apps.list_apps()

        self.assertEqual(payload["apps"][0]["display_name"], "films [radarr]")
        self.assertEqual(payload["apps"][0]["access_label"], "https://films.example.com +127.0.0.1:17878")
        self.assertEqual(payload["apps"][0]["state"], "running")

    def test_apps_page_has_card_design(self):
        template = Path(__file__).parents[1] / "webui" / "templates" / "pages" / "apps.html"
        source = template.read_text()

        self.assertIn('hx-get="/ui/apps"', source)
        self.assertNotIn("function appsPage", source)


class InfraRouteTests(unittest.TestCase):
    def test_infra_detail_renders_known_services(self):
        client = TestClient(app)
        for name in ["traefik", "oauth2", "crowdsec"]:
            resp = client.get(f"/infrastructure/{name}")
            self.assertEqual(resp.status_code, 200)
            self.assertIn(name, resp.text.lower() if name == "crowdsec" else resp.text)

    def test_infra_detail_returns_404_for_unknown(self):
        client = TestClient(app)
        resp = client.get("/infrastructure/invalid")
        self.assertEqual(resp.status_code, 404)

    def test_infra_index_uses_app_card(self):
        source = Path(__file__).parents[1].joinpath(
            "webui/templates/pages/infrastructure.html").read_text()
        self.assertIn('hx-get="/ui/infrastructure"', source)

    def test_logs_page_renders(self):
        client = TestClient(app)
        response = client.get("/logs")
        self.assertEqual(response.status_code, 200)
        template = Path(__file__).parents[1] / "webui" / "templates" / "pages" / "logs.html"
        self.assertTrue(template.is_file())

    def test_operations_page_renders(self):
        client = TestClient(app)
        response = client.get("/operations")
        self.assertEqual(response.status_code, 200)
        template = Path(__file__).parents[1] / "webui" / "templates" / "pages" / "operations.html"
        self.assertTrue(template.is_file())


class FragmentTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_fragment_has_live_region_and_no_page_alpine_controller(self):
        response = self.client.get("/ui/apps")

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="fragment-content"', response.text)
        self.assertIn('aria-live="polite"', response.text)

    def test_htmx_not_found_returns_an_error_fragment(self):
        response = self.client.get("/ui/unknown", headers={"HX-Request": "true", "host": "webui.example.com", "origin": "https://webui.example.com"})

        self.assertEqual(response.status_code, 404)
        self.assertIn("error-box", response.text)
        self.assertIn('role="alert"', response.text)

    @patch("webui.api.router_fragments.configure_app")
    @patch("webui.api.router_fragments.get_installed_app")
    def test_configure_form_delegates_to_confirmed_configuration_job(self, get_app, configure):
        get_app.return_value = AppRecord(instance="films", template="radarr",
                                         domain="example.com", subdomain="films")
        configure.return_value = JSONResponse({"job_id": 42}, status_code=202)
        response = self.client.post(
            "/ui/apps/films/configure", headers={
                "host": "webui.example.com", "origin": "https://webui.example.com",
            }, data={"subdomain": "cinema", "confirmed": "true"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Reconfiguration en file", response.text)
        request = configure.call_args.args[1]
        self.assertTrue(request.confirmed)
        self.assertEqual(request.subdomain, "cinema")

    def test_configure_form_disables_public_fields_for_local_only_access(self):
        template = (Path(__file__).parents[1] / "webui" / "templates" /
                    "fragments" / "apps_configure.html").read_text()

        self.assertIn('x-model="localOnly"', template)
        self.assertEqual(template.count('x-bind:disabled="localOnly"'), 3)

    @patch("webui.api.router_fragments.start_app")
    @patch("webui.api.router_fragments.get_docker")
    @patch("webui.api.router_fragments.get_installed_app")
    def test_app_detail_renders_enable_control_and_delegates_to_lifecycle_job(
        self, get_app, get_docker, start
    ):
        get_app.return_value = AppRecord(instance="films", template="radarr",
                                         local_only=True, host_port="17878", disabled=True)
        get_docker.return_value.stack_state.return_value = {
            "state": "disabled", "running": 0, "total": 1, "services": []
        }
        start.return_value = JSONResponse({"job_id": 42}, status_code=202)

        detail = self.client.get("/ui/apps/films")
        response = self.client.post(
            "/ui/apps/films/start",
            headers={"host": "webui.example.com", "origin": "https://webui.example.com"},
        )

        self.assertEqual(detail.status_code, 200)
        self.assertIn('hx-post="/ui/apps/films/start"', detail.text)
        self.assertIn("Activer", detail.text)
        self.assertNotIn("https://", detail.text)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Action en file", response.text)
        start.assert_called_once_with("films")

    def test_each_named_screen_category_has_a_fragment_endpoint(self):
        paths = {route.path for route in app.routes if hasattr(route, "path")}
        for route in app.routes:
            if hasattr(route, "original_router"):
                paths.update(route.include_context.prefix + child.path
                             for child in route.original_router.routes)

        expected = {
            "/ui/dashboard", "/ui/apps", "/ui/apps/install",
            "/ui/apps/{instance}", "/ui/apps/{instance}/start",
            "/ui/apps/{instance}/configure",
            "/ui/infrastructure", "/ui/infrastructure/{name}", "/ui/logs",
            "/ui/logs/{target}", "/ui/general", "/ui/general/{surface}",
            "/ui/security", "/ui/security/{surface}", "/ui/maintenance",
            "/ui/maintenance/operations",
        }
        self.assertTrue(expected.issubset(paths))

    @patch("webui.api.router_fragments.get_logs")
    def test_log_errors_are_rendered_as_html_fragments(self, get_logs):
        from fastapi.responses import JSONResponse

        get_logs.return_value = JSONResponse({"error": "Logs indisponibles"}, status_code=503)
        response = self.client.get("/ui/logs/traefik", headers={"HX-Request": "true"})

        self.assertEqual(response.status_code, 503)
        self.assertIn('role="alert"', response.text)
        self.assertIn("Logs indisponibles", response.text)

    def test_fragment_result_covers_empty_success_and_long_output(self):
        template = (Path(__file__).parents[1] / "webui" / "templates" /
                    "fragments" / "result.html").read_text()
        css = (Path(__file__).parents[1] / "webui" / "static" / "input.css").read_text()

        self.assertIn("Aucune donnée à afficher.", template)
        self.assertIn('role="status"', template)
        self.assertIn('role="alert"', template)
        self.assertIn('tabindex="-1"', template)
        self.assertIn(".fragment-output", css)

    def test_htmx_error_and_swap_keep_html_and_focus(self):
        source = (Path(__file__).parents[1] / "webui" / "static" / "app.js").read_text()

        self.assertIn("htmx:responseError", source)
        self.assertIn("target.innerHTML = xhr.responseText", source)
        self.assertIn("htmx:afterSwap", source)
        self.assertIn("afterSwap", source)


class FragmentRegressionTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.headers = {"host": "webui.example.com", "origin": "https://webui.example.com"}

    def test_operations_page_renders(self):
        response = self.client.get("/ui/operations")
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="fragment-content"', response.text)

    def test_security_ban_form_renders(self):
        response = self.client.get("/ui/security/ban")
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="fragment-content"', response.text)

    def test_security_unban_form_renders(self):
        response = self.client.get("/ui/security/unban")
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="fragment-content"', response.text)

    @patch("webui.api.router_fragments.crowdsec_decisions")
    def test_security_decisions_renders(self, mock_decisions):
        mock_decisions.return_value = {"output": "1.2.3.4 | ban | 4h"}
        response = self.client.get("/ui/security/decisions")
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="fragment-result"', response.text)
        self.assertIn("1.2.3.4", response.text)

    @patch("webui.api.router_fragments.crowdsec_metrics")
    def test_security_metrics_renders(self, mock_metrics):
        mock_metrics.return_value = {"output": "metrics-output"}
        response = self.client.get("/ui/security/metrics")
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="fragment-result"', response.text)
        self.assertIn("metrics-output", response.text)

    @patch("webui.api.router_fragments.crowdsec_bouncers")
    def test_security_bouncers_renders(self, mock_bouncers):
        mock_bouncers.return_value = {"output": "bouncers-list"}
        response = self.client.get("/ui/security/bouncers")
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="fragment-result"', response.text)
        self.assertIn("bouncers-list", response.text)

    @patch("webui.api.router_fragments.crowdsec_console_status")
    def test_security_console_renders(self, mock_console):
        mock_console.return_value = {"output": "console-status"}
        response = self.client.get("/ui/security/console")
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="fragment-result"', response.text)
        self.assertIn("console-status", response.text)

    @patch("webui.api.router_apps.app_logs")
    @patch("webui.api.router_fragments.get_installed_app")
    def test_app_logs_fragment_renders(self, mock_get_app, mock_get_logs):
        mock_get_app.return_value = SimpleNamespace(
            instance="films", template="radarr", app_dir="/apps/films",
            docker_service="radarr",
        )
        mock_get_logs.return_value = {"logs": "app log content"}
        response = self.client.get("/ui/apps/films/logs", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="fragment-result"', response.text)
        self.assertIn("app log content", response.text)

    @patch("webui.api.router_maintenance.clean_data_app")
    def test_maintenance_clean_data_post(self, mock_clean):
        async def _mock_clean(name, req):
            return {"success": True, "path": f"/data/{name}"}
        mock_clean.side_effect = _mock_clean
        response = self.client.post(
            "/ui/maintenance/clean-data/radarr",
            headers=self.headers,
            data={"confirmed": "true"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="fragment-result"', response.text)


class FrontendAssetTests(unittest.TestCase):
    def test_compiled_css_keeps_shared_component_selectors(self):
        static = Path(__file__).parents[1] / "webui" / "static"
        source = (static / "input.css").read_text()
        css = (static / "app.css").read_text()

        for selector in (".card", ".btn", ".chip", ".modal", ".spinner"):
            self.assertIn(selector, source)
            self.assertIn(selector, css)

        self.assertFalse(list(static.glob("*legacy*")))

    def test_local_vendor_assets_are_locked_and_referenced(self):
        root = Path(__file__).parents[2]
        base = (root / "src" / "webui" / "templates" / "base.html").read_text()
        package = (root / "package.json").read_text()

        self.assertIn('/static/vendor/htmx-2.0.8.min.js', base)
        self.assertIn('/static/vendor/alpine-3.15.3.min.js', base)
        self.assertIn('"htmx.org": "2.0.8"', package)
        self.assertIn('"alpinejs": "3.15.3"', package)
        self.assertTrue((root / "src" / "webui" / "static" / "vendor" / "htmx-2.0.8.min.js").is_file())
        self.assertTrue((root / "src" / "webui" / "static" / "vendor" / "alpine-3.15.3.min.js").is_file())


if __name__ == "__main__":
    unittest.main()
