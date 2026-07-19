import json
import asyncio
import os
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from webui.api import router_operations
from webui.api import router_status
from webui.core import ksf_cli
from webui.core import jobs
from webui.core.schemas import InstallRequest, OperationRequest
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


class RouteTests(unittest.TestCase):
    def test_platform_operation_routes_are_registered(self):
        paths = set(app.openapi()["paths"])
        self.assertIn("/api/operations/render", paths)
        self.assertIn("/api/operations/apps/update-all", paths)
        self.assertIn("/apps/install", paths)


if __name__ == "__main__":
    unittest.main()
