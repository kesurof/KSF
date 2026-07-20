import os
import subprocess
import shutil
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..core.config import (get_config, BASE_DIR, INSTALLED_DIR, APPS_DIR, DATA_DIR,
                           TRAEFIK_DYNAMIC_DIR)
from ..core.state import (list_installed_apps, get_installed_app,
                          list_available_templates, get_template,
                          parse_env_file, AppRecord)
from ..core.docker import get_docker
from ..core.routes import render_app_route, remove_route
from ..core.schemas import InstallRequest, ConfigureRequest, RemoveRequest
from ..core.validation import (validate_allowed_domain, validate_allowed_host,
                               validate_host, validate_instance, validate_port,
                               validate_subdomain)
from ..core.ksf_cli import run_dns, run_app
from ..core.jobs import start_job

router = APIRouter()


def _has_build(compose_file: Path) -> bool:
    if not compose_file.exists():
        return False
    content = compose_file.read_text()
    return "build:" in content


def _template_dir(template: str) -> Path:
    return Path(os.environ.get("KSF_SCRIPT_DIR", "/app")) / "templates" / "apps" / template


def _runtime_owner_ids() -> tuple[str, str]:
    try:
        owner = BASE_DIR.stat()
        return str(owner.st_uid), str(owner.st_gid)
    except OSError:
        return str(os.getuid()), str(os.getgid())


def _render_compose(template_dir: Path, app: AppRecord, cfg) -> str:
    template_compose = template_dir / "compose.yml"
    if not template_compose.exists():
        raise ValueError(f"Template compose.yml introuvable pour {app.template}.")

    ports_block = ""
    if app.host_port:
        ports_block = f"ports:\n      - \"127.0.0.1:{app.host_port}:{app.port}\""
    safe = {
        "APP_NAME": app.template,
        "APP_INSTANCE": app.instance,
        "APP_HOST": app.host,
        "APP_PORT": app.port,
        "APP_HOST_PORT": app.host_port,
        "APP_PORTS_BLOCK": ports_block,
        "APP_PROTECTED": "true" if app.protected else "false",
        "APP_PUBLIC": "true" if app.public else "false",
        "APP_LOCAL_ONLY": "true" if app.local_only else "false",
        "APP_DISABLED": "true" if app.disabled else "false",
        "APP_DIR": app.app_dir,
        "APP_DATA": app.app_data,
        "APP_DOCKER_SERVICE": app.docker_service,
        "BASE_DIR": str(BASE_DIR),
        "NETWORK_NAME": cfg.network_name,
        "TZ_VALUE": os.environ.get("KSF_TZ_VALUE", os.environ.get("TZ_VALUE", "UTC")),
        "APP_PUID": app.puid or _runtime_owner_ids()[0],
        "APP_PGID": app.pgid or _runtime_owner_ids()[1],
    }
    import string
    rendered = string.Template(template_compose.read_text()).safe_substitute(safe)
    if "${" in rendered:
        raise ValueError("Le compose rendu contient des variables non resolues.")
    return rendered


def _write_app_env(app: AppRecord) -> None:
    env_file = INSTALLED_DIR / f"{app.instance}.env"
    lines = {
        "APP_NAME": app.template,
        "APP_INSTANCE": app.instance,
        "APP_HOST": app.host,
        "APP_DOMAIN": app.domain,
        "APP_SUBDOMAIN": app.subdomain,
        "APP_PORT": app.port,
        "APP_HOST_PORT": app.host_port,
        "APP_DOCKER_SERVICE": app.docker_service,
        "APP_PROTECTED": str(app.protected).lower(),
        "APP_AUTH": str(app.protected).lower(),
        "APP_PUBLIC": str(app.public).lower(),
        "APP_LOCAL_ONLY": str(app.local_only).lower(),
        "APP_DISABLED": str(app.disabled).lower(),
        "APP_DIR": app.app_dir,
        "APP_DATA": app.app_data,
        "APP_PUID": app.puid,
        "APP_PGID": app.pgid,
        "APP_INSTALLED_AT": app.installed_at,
    }
    env_file.write_text("".join(f"{key}={value}\n" for key, value in lines.items()))
    env_file.chmod(0o600)
    puid = app.puid or os.environ.get("APP_PUID", "")
    pgid = app.pgid or os.environ.get("APP_PGID", "")
    if puid and pgid:
        shutil.chown(env_file, user=int(puid), group=int(pgid))


def _app_with_disabled(app: AppRecord, disabled: bool) -> AppRecord:
    return AppRecord(
        instance=app.instance, template=app.template, host=app.host,
        domain=app.domain, subdomain=app.subdomain, port=app.port,
        host_port=app.host_port, docker_service=app.docker_service,
        protected=app.protected, public=app.public, local_only=app.local_only,
        disabled=disabled, app_dir=app.app_dir, app_data=app.app_data,
        puid=app.puid, pgid=app.pgid, installed_at=app.installed_at,
    )


def _enable_app(app: AppRecord) -> tuple[bool, str]:
    cfg = get_config()
    if not app.local_only and app.public:
        if not app.host:
            return False, "L'app ne possede pas de host public configure."
        if app.protected and not cfg.has_oauth2():
            return False, "OAuth2 Proxy n'est pas configure."

    docker = get_docker()
    code, stdout, stderr = docker.compose_up(app.app_dir)
    if code != 0:
        return False, stderr or stdout or "Echec du demarrage de la stack."

    try:
        if not app.local_only and app.public:
            render_app_route(app.instance, app.host, app.port,
                             protected=app.protected,
                             docker_service=app.docker_service)
        _write_app_env(_app_with_disabled(app, False))
    except (OSError, ValueError) as exc:
        return False, str(exc)
    return True, ""


def _host_parts(host: str, cfg) -> tuple[str, str]:
    _, domain, subdomain = validate_allowed_host(host, cfg.domains)
    return subdomain, domain


def _is_direct_child(path: Path, parent: Path) -> bool:
    try:
        return path.resolve().parent == parent.resolve()
    except OSError:
        return False


@router.get("")
def list_apps():
    apps = list_installed_apps()
    docker = get_docker()
    results = []
    for app in apps:
        state = docker.stack_state(app.app_dir, app.docker_service)
        results.append({
            **app.to_dict(),
            "state": state["state"],
            "running": state["running"],
            "total": state["total"],
            "services": state["services"],
            "route_present": (TRAEFIK_DYNAMIC_DIR / f"route-{app.instance}.yml").exists(),
        })
    return {"apps": results}


@router.get("/{instance}")
def app_detail(instance: str):
    app = get_installed_app(instance)
    if not app:
        return JSONResponse({"error": "App not found"}, status_code=404)
    docker = get_docker()
    state = docker.stack_state(app.app_dir, app.docker_service)
    return {
        **app.to_dict(),
        "state": state["state"],
        "running": state["running"],
        "total": state["total"],
        "unhealthy": state["unhealthy"],
        "services": state["services"],
        "primary_service": state.get("primary_service", ""),
        "primary_name": state.get("primary_name", ""),
        "primary_state": state.get("primary_state", ""),
        "primary_health": state.get("primary_health", ""),
        "route_present": (TRAEFIK_DYNAMIC_DIR / f"route-{instance}.yml").exists(),
    }


@router.post("/install")
def install_app(req: InstallRequest):
    cfg = get_config()
    template_info = get_template(req.template)
    if not template_info:
        return JSONResponse({"error": f"Template '{req.template}' not found"}, status_code=404)

    try:
        instance = validate_instance(req.instance or req.template)
        host_port = validate_port(req.host_port)
        host = validate_allowed_host(req.host, cfg.domains)[0] if req.host else ""
        domain = validate_allowed_domain(req.domain, cfg.domains) if req.domain else ""
        subdomain = validate_subdomain(req.subdomain)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=422)

    installed_env = INSTALLED_DIR / f"{instance}.env"

    if installed_env.exists():
        return JSONResponse({"error": f"Instance '{instance}' already installed"}, status_code=409)

    app_dir = APPS_DIR / instance
    app_data = DATA_DIR / instance
    template_dir = _template_dir(req.template)
    template_compose = template_dir / "compose.yml"
    template_app_env = template_dir / "app.env"

    if not template_compose.exists():
        return JSONResponse({"error": f"Template compose.yml not found for {req.template}"},
                            status_code=500)

    template_vars = parse_env_file(template_app_env)
    try:
        port = validate_port(req.port or template_vars.get("APP_PORT", template_info.get("port", "")))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=422)
    docker_service = template_vars.get("APP_DOCKER_SERVICE", "")

    if req.local_only or not cfg.has_traefik():
        local_only = True
        host = ""
        domain = ""
        subdomain = ""
    else:
        local_only = False
        if not host:
            if not domain:
                domain = cfg.default_domain
            if not subdomain:
                subdomain = template_info.get("default_host", instance)
            try:
                domain = validate_allowed_domain(domain, cfg.domains)
                subdomain = validate_subdomain(subdomain)
            except ValueError as exc:
                return JSONResponse({"error": str(exc)}, status_code=422)
            host = f"{subdomain}.{domain}"

    protected = template_info.get("protected", True)
    if req.no_auth:
        protected = False
    elif req.auth is not None:
        protected = req.auth

    public = template_info.get("public", True)
    if not public and (host or domain or subdomain):
        return JSONResponse({"error": "Cette app n'est pas publique et doit etre installee en mode local."}, status_code=422)
    if local_only and not host_port:
        return JSONResponse(
            {"error": "Un port hote local est requis lorsque Traefik n'est pas utilise."},
            status_code=422,
        )
    if protected and not local_only and not cfg.has_oauth2():
        return JSONResponse(
            {"error": "OAuth2 Proxy n'est pas configure. Desactivez la protection ou configurez OAuth2 Proxy."},
            status_code=422,
        )

    try:
        app_dir.mkdir(parents=True, exist_ok=True)
        app_data.mkdir(parents=True, exist_ok=True)
        INSTALLED_DIR.mkdir(parents=True, exist_ok=True)
        owner_uid, owner_gid = _runtime_owner_ids()
        app = AppRecord(
            instance=instance, template=req.template, host=host, domain=domain,
            subdomain=subdomain, port=port, host_port=host_port,
            docker_service=docker_service, protected=protected, public=public,
            local_only=local_only, app_dir=str(app_dir), app_data=str(app_data),
            puid=owner_uid,
            pgid=owner_gid,
            installed_at=datetime.now(timezone.utc).isoformat(),
        )
        (app_dir / "docker-compose.yml").write_text(_render_compose(template_dir, app, cfg))
        _write_app_env(app)

        env = os.environ.copy()
        env.update({
            "APP_NAME": req.template,
            "APP_INSTANCE": instance,
            "APP_DIR": str(app_dir),
            "APP_DATA": str(app_data),
            "APP_HOST": host,
            "APP_PORT": port,
            "APP_HOST_PORT": host_port,
            "APP_TEMPLATE_DIR": str(template_dir),
            "BASE_DIR": str(BASE_DIR),
            "NETWORK_NAME": cfg.network_name,
            "TZ_VALUE": env.get("KSF_TZ_VALUE", env.get("TZ_VALUE", "UTC")),
            "APP_PUID": owner_uid,
            "APP_PGID": owner_gid,
            "DRY_RUN": "false",
            "AUTO_YES": "true",
        })
        pre_hook = template_dir / "pre_install.sh"
        if pre_hook.exists():
            subprocess.run(["bash", str(pre_hook)], env=env, check=True, timeout=300)

        if not local_only and host and public:
            render_app_route(instance, host, port, protected=protected,
                             docker_service=docker_service)

        docker = get_docker()
        if _has_build(app_dir / "docker-compose.yml"):
            code, stdout, stderr = docker.compose_build(str(app_dir))
            if code != 0:
                return JSONResponse({"error": stderr or stdout}, status_code=500)
        code, stdout, stderr = docker.compose_up(str(app_dir))
        if code != 0:
            return JSONResponse({
                "error": stderr or stdout or "Echec du demarrage de la stack.",
                "instance": instance,
            }, status_code=500)

        post_hook = template_dir / "post_install.sh"
        if post_hook.exists():
            subprocess.run(["bash", str(post_hook)], env=env, check=True, timeout=300)

        if not local_only and host:
            code, stdout, stderr = run_dns("ensure", host)
            if code != 0:
                return JSONResponse({"error": stderr or stdout or "Echec de la creation DNS."}, status_code=500)

        return {"success": True, "instance": instance, "host": host}

    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/{instance}/start")
def start_app(instance: str):
    app = get_installed_app(instance)
    if not app:
        return JSONResponse({"error": "App not found"}, status_code=404)
    if app.disabled:
        enabled, message = _enable_app(app)
        if not enabled:
            return JSONResponse({"error": message}, status_code=500)
        return {"success": True, "instance": instance, "enabled": True}
    docker = get_docker()
    code, stdout, stderr = docker.compose_up(app.app_dir)
    if code != 0:
        return JSONResponse({"error": stderr or stdout}, status_code=500)
    return {"success": True, "instance": instance}


@router.post("/{instance}/stop")
def stop_app(instance: str):
    app = get_installed_app(instance)
    if not app:
        return JSONResponse({"error": "App not found"}, status_code=404)
    if app.disabled:
        return JSONResponse({"error": "L'app est deja desactivee."}, status_code=409)
    docker = get_docker()
    code, stdout, stderr = docker.compose_stop(app.app_dir)
    if code != 0:
        return JSONResponse({"error": stderr or stdout}, status_code=500)
    return {"success": True, "instance": instance}


@router.post("/{instance}/restart")
def restart_app(instance: str):
    app = get_installed_app(instance)
    if not app:
        return JSONResponse({"error": "App not found"}, status_code=404)
    if app.disabled:
        return JSONResponse({"error": "L'app est desactivee. Activez-la avant de la redemarrer."}, status_code=409)
    docker = get_docker()
    code, stdout, stderr = docker.compose_restart(app.app_dir)
    if code != 0:
        return JSONResponse({"error": stderr or stdout}, status_code=500)
    return {"success": True, "instance": instance}


@router.post("/{instance}/disable")
def disable_app(instance: str):
    app = get_installed_app(instance)
    if not app:
        return JSONResponse({"error": "App not found"}, status_code=404)
    if app.disabled:
        return JSONResponse({"error": "L'app est deja desactivee."}, status_code=409)
    docker = get_docker()
    code, stdout, stderr = docker.compose_down(app.app_dir)
    if code != 0:
        return JSONResponse({"error": stderr or stdout or "Echec de l'arret de la stack."}, status_code=500)
    try:
        remove_route(instance)
        _write_app_env(_app_with_disabled(app, True))
    except OSError as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)
    return {"success": True, "instance": instance}


@router.post("/{instance}/enable")
def enable_app(instance: str):
    app = get_installed_app(instance)
    if not app:
        return JSONResponse({"error": "App not found"}, status_code=404)
    if not app.disabled:
        return JSONResponse({"error": "L'app est deja activee."}, status_code=409)
    enabled, message = _enable_app(app)
    if not enabled:
        return JSONResponse({"error": message}, status_code=500)
    return {"success": True, "instance": instance}


@router.post("/{instance}/remove")
def remove_app(instance: str, req: RemoveRequest):
    app = get_installed_app(instance)
    if not app:
        return JSONResponse({"error": "App not found"}, status_code=404)
    if not req.confirmed:
        return JSONResponse({"error": "Confirmation explicite requise."}, status_code=422)
    app_dir = Path(app.app_dir)
    data_dir = Path(app.app_data)
    if not _is_direct_child(app_dir, APPS_DIR):
        return JSONResponse({"error": "Le chemin de stack est invalide."}, status_code=500)
    if req.remove_data and not _is_direct_child(data_dir, DATA_DIR):
        return JSONResponse({"error": "Le chemin de donnees est invalide."}, status_code=500)

    docker = get_docker()
    code, stdout, stderr = docker.compose_down(app.app_dir)
    if code != 0:
        return JSONResponse({"error": stderr or stdout or "Echec de l'arret de la stack."}, status_code=500)
    try:
        remove_route(instance)
        if app.host and not app.local_only:
            run_dns("delete", app.host)
        if app_dir.exists():
            shutil.rmtree(app_dir)
        if req.remove_data and data_dir.exists():
            shutil.rmtree(data_dir)
        env_file = INSTALLED_DIR / f"{instance}.env"
        if env_file.exists():
            env_file.unlink()
    except OSError as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)
    return {"success": True, "instance": instance, "data_removed": req.remove_data}


@router.get("/{instance}/logs")
def app_logs(instance: str, tail: int = 200):
    app = get_installed_app(instance)
    if not app:
        return JSONResponse({"error": "App not found"}, status_code=404)
    tail = max(1, min(tail, 5000))
    docker = get_docker()
    logs = docker.compose_logs(app.app_dir, tail=tail)
    return {"logs": logs}


@router.post("/{instance}/configure")
def configure_app(instance: str, req: ConfigureRequest):
    app = get_installed_app(instance)
    if not app:
        return JSONResponse({"error": "App not found"}, status_code=404)
    cfg = get_config()

    try:
        host = validate_allowed_host(req.host, cfg.domains)[0] if req.host else app.host
        domain = validate_allowed_domain(req.domain, cfg.domains) if req.domain else app.domain
        subdomain = validate_subdomain(req.subdomain) if req.subdomain else app.subdomain
        host_port = "" if req.no_host_port else validate_port(req.host_port or app.host_port)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=422)

    local_only = app.local_only if req.local_only is None else req.local_only
    if req.local_only:
        host = domain = subdomain = ""
    elif req.host:
        local_only = False
        if not req.domain and not req.subdomain:
            subdomain, domain = _host_parts(host, cfg)
    elif req.domain or req.subdomain:
        local_only = False
        if not domain or not subdomain:
            return JSONResponse({"error": "Le domaine et le sous-domaine sont requis."}, status_code=422)
        host = f"{subdomain}.{domain}"

    if local_only and not host_port:
        return JSONResponse({"error": "Un port hote local est requis en mode local."}, status_code=422)
    if not local_only and app.public and not host:
        return JSONResponse({"error": "Un host public ou le mode local est requis."}, status_code=422)
    if not app.public and not local_only:
        return JSONResponse({"error": "Cette app n'est pas publique et doit rester en mode local."}, status_code=422)
    if not local_only and app.protected and not cfg.has_oauth2():
        return JSONResponse({"error": "OAuth2 Proxy n'est pas configure."}, status_code=422)

    updated = AppRecord(
        instance=app.instance, template=app.template, host=host, domain=domain,
        subdomain=subdomain, port=app.port, host_port=host_port,
        docker_service=app.docker_service, protected=app.protected, public=app.public,
        local_only=local_only, disabled=app.disabled, app_dir=app.app_dir,
        app_data=app.app_data, puid=app.puid, pgid=app.pgid,
        installed_at=app.installed_at,
    )
    try:
        template_dir = _template_dir(updated.template)
        (Path(updated.app_dir) / "docker-compose.yml").write_text(_render_compose(template_dir, updated, cfg))
        _write_app_env(updated)
        if not local_only and host and updated.public:
            render_app_route(instance, host, updated.port,
                             protected=updated.protected,
                             docker_service=updated.docker_service)
        else:
            remove_route(instance)
        if app.host and app.host != host and not app.local_only:
            run_dns("delete", app.host)
        if host and app.host != host and not local_only:
            code, stdout, stderr = run_dns("ensure", host)
            if code != 0:
                return JSONResponse({"error": stderr or stdout or "Echec de la creation DNS."}, status_code=500)
        if not updated.disabled:
            code, stdout, stderr = get_docker().compose_up(updated.app_dir)
            if code != 0:
                return JSONResponse({"error": stderr or stdout}, status_code=500)
    except (OSError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)
    return {"success": True, "instance": instance, "host": host, "host_port": host_port}


@router.post("/{instance}/update")
def update_app(instance: str):
    app = get_installed_app(instance)
    if not app:
        return JSONResponse({"error": "App not found"}, status_code=404)
    template_dir = _template_dir(app.template)
    template_compose = template_dir / "compose.yml"
    if not template_compose.exists():
        return JSONResponse({"error": f"Template compose.yml not found for {app.template}"},
                            status_code=404)
    try:
        (Path(app.app_dir) / "docker-compose.yml").write_text(_render_compose(template_dir, app, get_config()))
    except (OSError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)
    docker = get_docker()
    if _has_build(Path(app.app_dir) / "docker-compose.yml"):
        code, stdout, stderr = docker.compose_build(app.app_dir)
        if code != 0:
            return JSONResponse({"error": stderr or stdout}, status_code=500)
    else:
        code, stdout, stderr = docker.compose_pull(app.app_dir)
        if code != 0:
            return JSONResponse({"error": stderr or stdout}, status_code=500)
    if app.disabled:
        return {"success": True, "instance": instance, "started": False}
    code, stdout, stderr = docker.compose_up(app.app_dir)
    if code != 0:
        return JSONResponse({"error": stderr}, status_code=500)
    return {"success": True, "instance": instance}


@router.post("/{instance}/rebuild")
def rebuild_app(instance: str):
    app = get_installed_app(instance)
    if not app:
        return JSONResponse({"error": "App not found"}, status_code=404)
    if app.disabled:
        return JSONResponse({"error": "L'app est desactivee."}, status_code=409)

    if instance == "webui":
        import docker as _docker
        client = _docker.from_env()
        container = client.containers.run(
            "webui-webui:latest",
            command=["bash", "/app/ksf/app.sh", "rebuild", "webui",
                     "--base-dir", str(BASE_DIR), "--yes"],
            volumes={
                str(BASE_DIR): {"bind": str(BASE_DIR), "mode": "rw"},
                "/var/run/docker.sock": {"bind": "/var/run/docker.sock", "mode": "rw"},
            },
            network_mode="host",
            detach=True,
            remove=True,
            name="ksf-rebuild-webui",
        )
        return {
            "success": True, "instance": instance,
            "notice": "Rebuild lancé dans un conteneur helper. Le Web UI redémarre dans quelques instants, reconnectez-vous."
        }

    job_id, error = start_job(f"rebuild-{instance}", instance,
                               lambda: run_app("rebuild", instance))
    if job_id is None:
        return JSONResponse({"error": error}, status_code=409)
    return JSONResponse({"job_id": job_id, "status": "pending"}, status_code=202)


@router.get("/{instance}/services")
def app_services(instance: str):
    app = get_installed_app(instance)
    if not app:
        return JSONResponse({"error": "App not found"}, status_code=404)
    docker = get_docker()
    state = docker.stack_state(app.app_dir, app.docker_service)
    return {"services": state.get("services", [])}
