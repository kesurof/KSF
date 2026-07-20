from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..core.config import TRAEFIK_DYNAMIC_DIR, get_config
from ..core.docker import get_docker
from ..core.jobs import start_job
from ..core.ksf_cli import run_app
from ..core.schemas import ConfirmRequest, ConfigureRequest, InstallRequest, RemoveRequest
from ..core.security import redact_secrets
from ..core.state import get_installed_app, get_template, list_installed_apps
from ..core.validation import (validate_allowed_domain, validate_allowed_host,
                               validate_instance, validate_port, validate_subdomain)


router = APIRouter()


def _job(action: str, instance: str, *args: str, remove_data: bool = False):
    """Run application lifecycle changes exclusively through the versioned CLI."""
    job_id, error = start_job(
        action,
        instance,
        lambda: run_app(*args, confirmed=True, remove_data=remove_data),
    )
    if job_id is None:
        return JSONResponse({"error": error}, status_code=409)
    return JSONResponse({"job_id": job_id, "status": "pending"}, status_code=202)


def _require_app(instance: str):
    try:
        instance = validate_instance(instance)
    except ValueError as exc:
        return None, JSONResponse({"error": str(exc)}, status_code=422)
    app = get_installed_app(instance)
    if not app:
        return None, JSONResponse({"error": "App not found"}, status_code=404)
    return app, None


def _append_access_args(args: list[str], *, host: str = "", domain: str = "",
                        subdomain: str = "", host_port: str = "",
                        no_host_port: bool = False, local_only: bool = False) -> None:
    if host:
        args.extend(("--host", host))
    if domain:
        args.extend(("--domain", domain))
    if subdomain:
        args.extend(("--subdomain", subdomain))
    if host_port:
        args.extend(("--host-port", host_port))
    if no_host_port:
        args.append("--no-host-port")
    if local_only:
        args.append("--local-only")


def _enable_args(app) -> list[str]:
    """Reinstall through app.sh because its lifecycle has no separate enable command."""
    args = ["install", app.template, "--instance", app.instance]
    if app.port:
        args.extend(("--port", app.port))
    _append_access_args(
        args,
        host=app.host,
        host_port=app.host_port,
        local_only=app.local_only,
    )
    args.append("--auth" if app.protected else "--no-auth")
    args.append("--force")
    return args


@router.get("")
def list_apps():
    docker = get_docker()
    results = []
    for app in list_installed_apps():
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
    app, error = _require_app(instance)
    if error:
        return error
    state = get_docker().stack_state(app.app_dir, app.docker_service)
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
    template = get_template(req.template)
    if not template:
        return JSONResponse({"error": f"Template '{req.template}' not found"}, status_code=404)
    try:
        instance = validate_instance(req.instance or req.template)
        host_port = validate_port(req.host_port)
        port = validate_port(req.port)
        host = validate_allowed_host(req.host, cfg.domains)[0] if req.host else ""
        domain = validate_allowed_domain(req.domain, cfg.domains) if req.domain else ""
        subdomain = validate_subdomain(req.subdomain)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=422)
    if get_installed_app(instance):
        return JSONResponse({"error": f"Instance '{instance}' already installed"}, status_code=409)
    if req.local_only and not host_port:
        return JSONResponse({"error": "Un port hote local est requis en mode local."}, status_code=422)
    if req.no_auth and req.auth:
        return JSONResponse({"error": "Les options auth et no_auth sont incompatibles."}, status_code=422)
    if req.auth and not req.local_only and not cfg.has_oauth2():
        return JSONResponse({"error": "OAuth2 Proxy n'est pas configure."}, status_code=422)

    args = ["install", req.template, "--instance", instance]
    if port:
        args.extend(("--port", port))
    _append_access_args(args, host=host, domain=domain, subdomain=subdomain,
                        host_port=host_port, local_only=req.local_only)
    if req.auth:
        args.append("--auth")
    if req.no_auth:
        args.append("--no-auth")
    return _job(f"install-{instance}", instance, *args)


@router.post("/{instance}/start")
def start_app(instance: str):
    app, error = _require_app(instance)
    if error:
        return error
    if app.disabled:
        return _job(f"enable-{app.instance}", app.instance, *_enable_args(app))
    return _job(f"start-{app.instance}", app.instance, "start", app.instance)


@router.post("/{instance}/stop")
def stop_app(instance: str):
    app, error = _require_app(instance)
    if error:
        return error
    if app.disabled:
        return JSONResponse({"error": "L'app est deja desactivee."}, status_code=409)
    return _job(f"stop-{app.instance}", app.instance, "stop", app.instance)


@router.post("/{instance}/restart")
def restart_app(instance: str):
    app, error = _require_app(instance)
    if error:
        return error
    if app.disabled:
        return JSONResponse({"error": "L'app est desactivee. Activez-la avant de la redemarrer."}, status_code=409)
    return _job(f"restart-{app.instance}", app.instance, "restart", app.instance)


@router.post("/{instance}/disable")
def disable_app(instance: str, req: ConfirmRequest):
    app, error = _require_app(instance)
    if error:
        return error
    if app.disabled:
        return JSONResponse({"error": "L'app est deja desactivee."}, status_code=409)
    if not req.confirmed:
        return JSONResponse({"error": "Confirmation explicite requise."}, status_code=422)
    return _job(f"disable-{app.instance}", app.instance, "disable", app.instance)


@router.post("/{instance}/enable")
def enable_app(instance: str):
    app, error = _require_app(instance)
    if error:
        return error
    if not app.disabled:
        return JSONResponse({"error": "L'app est deja activee."}, status_code=409)
    return _job(f"enable-{app.instance}", app.instance, *_enable_args(app))


@router.post("/{instance}/remove")
def remove_app(instance: str, req: RemoveRequest):
    app, error = _require_app(instance)
    if error:
        return error
    if not req.confirmed:
        return JSONResponse({"error": "Confirmation explicite requise."}, status_code=422)
    return _job(f"remove-{app.instance}", app.instance, "remove", app.instance,
                remove_data=req.remove_data)


@router.get("/{instance}/logs")
def app_logs(instance: str, tail: int = 200):
    app, error = _require_app(instance)
    if error:
        return error
    logs = get_docker().compose_logs(app.app_dir, tail=max(1, min(tail, 5000)))
    return {"logs": redact_secrets(logs)}


@router.post("/{instance}/configure")
def configure_app(instance: str, req: ConfigureRequest):
    app, error = _require_app(instance)
    if error:
        return error
    cfg = get_config()
    try:
        host = validate_allowed_host(req.host, cfg.domains)[0] if req.host and not req.local_only else ""
        domain = validate_allowed_domain(req.domain, cfg.domains) if req.domain and not req.local_only else ""
        subdomain = validate_subdomain(req.subdomain) if not req.local_only else ""
        host_port = validate_port(req.host_port)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=422)
    if req.local_only and not host_port and not app.host_port:
        return JSONResponse({"error": "Un port hote local est requis en mode local."}, status_code=422)
    if not req.local_only and not app.public and (host or domain or subdomain):
        return JSONResponse({"error": "Cette app n'est pas publique et doit rester en mode local."}, status_code=422)
    if not req.confirmed:
        return JSONResponse({"error": "Confirmation explicite requise."}, status_code=422)

    args = ["configure", app.instance]
    _append_access_args(args, host=host, domain=domain, subdomain=subdomain,
                        host_port=host_port, no_host_port=req.no_host_port,
                        local_only=req.local_only is True)
    return _job(f"configure-{app.instance}", app.instance, *args)


@router.post("/{instance}/update")
def update_app(instance: str, req: ConfirmRequest):
    app, error = _require_app(instance)
    if error:
        return error
    if not req.confirmed:
        return JSONResponse({"error": "Confirmation explicite requise."}, status_code=422)
    return _job(f"update-{app.instance}", app.instance, "update", app.instance)


@router.post("/{instance}/rebuild")
def rebuild_app(instance: str, req: ConfirmRequest):
    app, error = _require_app(instance)
    if error:
        return error
    if app.disabled:
        return JSONResponse({"error": "L'app est desactivee."}, status_code=409)
    if instance == "webui":
        return JSONResponse({"error": "Le Web UI ne peut pas se reconstruire lui-meme. Utilisez app.sh rebuild webui depuis le serveur."}, status_code=403)
    if not req.confirmed:
        return JSONResponse({"error": "Confirmation explicite requise."}, status_code=422)
    return _job(f"rebuild-{app.instance}", app.instance, "rebuild", app.instance)


@router.get("/{instance}/services")
def app_services(instance: str):
    app, error = _require_app(instance)
    if error:
        return error
    state = get_docker().stack_state(app.app_dir, app.docker_service)
    return {"services": state.get("services", [])}
