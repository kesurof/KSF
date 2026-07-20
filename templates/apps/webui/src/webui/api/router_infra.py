from fastapi import APIRouter
from fastapi.responses import JSONResponse
from ..core.config import get_config, TRAEFIK_DIR, OAUTH2_DIR, CROWDSEC_DIR
from ..core.docker import get_docker
from ..core.schemas import ConfirmRequest
from ..core.security import redact_secrets

router = APIRouter()


SERVICE_NAMES = {
    "traefik": "traefik",
    "oauth2": "oauth2-proxy",
    "crowdsec": "crowdsec",
}


@router.get("")
def list_services():
    cfg = get_config()
    services = []
    for name in ["traefik", "oauth2", "crowdsec"]:
        enabled = {
            "traefik": cfg.has_traefik(),
            "oauth2": cfg.has_oauth2(),
            "crowdsec": cfg.has_crowdsec(),
        }[name]
        if not enabled:
            services.append({"name": name, "enabled": False, "state": "non configuré"})
            continue
        stack_dir = {
            "traefik": str(TRAEFIK_DIR),
            "oauth2": str(OAUTH2_DIR),
            "crowdsec": str(CROWDSEC_DIR),
        }[name]
        from pathlib import Path
        if not Path(stack_dir).exists():
            services.append({"name": name, "enabled": True, "state": "stack absente"})
            continue
        docker = get_docker()
        state = docker.stack_state(stack_dir)
        services.append({
            "name": name,
            "enabled": True,
            "state": state["state"],
            "running": state["running"],
            "total": state["total"],
            "services": state["services"],
        })
    return {"services": services}


@router.get("/{name}/status")
def service_status(name: str):
    cfg = get_config()
    enabled_map = {
        "traefik": cfg.has_traefik(),
        "oauth2": cfg.has_oauth2(),
        "crowdsec": cfg.has_crowdsec(),
    }
    dir_map = {
        "traefik": str(TRAEFIK_DIR),
        "oauth2": str(OAUTH2_DIR),
        "crowdsec": str(CROWDSEC_DIR),
    }
    if name not in enabled_map:
        return JSONResponse({"error": "Unknown service"}, status_code=404)
    if not enabled_map[name]:
        return {"name": name, "enabled": False}
    stack_dir = dir_map[name]
    from pathlib import Path
    if not Path(stack_dir).exists():
        return {"name": name, "enabled": True, "state": "stack absente"}
    docker = get_docker()
    state = docker.stack_state(stack_dir)
    return {"name": name, "enabled": True, **state}


@router.get("/{name}/logs")
def service_logs(name: str, tail: int = 200):
    dir_map = {
        "traefik": str(TRAEFIK_DIR),
        "oauth2": str(OAUTH2_DIR),
        "crowdsec": str(CROWDSEC_DIR),
    }
    if name not in dir_map:
        return JSONResponse({"error": "Unknown service"}, status_code=404)
    from pathlib import Path
    stack_dir = dir_map[name]
    if not Path(stack_dir).exists():
        return JSONResponse({"error": "Stack directory not found"}, status_code=404)
    docker = get_docker()
    logs = docker.compose_logs(stack_dir, tail=tail)
    return {"logs": redact_secrets(logs)}


@router.post("/{name}/restart")
def service_restart(name: str, req: ConfirmRequest):
    if not req.confirmed:
        return JSONResponse({"error": "Confirmation explicite requise."}, status_code=422)
    dir_map = {
        "traefik": str(TRAEFIK_DIR),
        "oauth2": str(OAUTH2_DIR),
        "crowdsec": str(CROWDSEC_DIR),
    }
    if name not in dir_map:
        return JSONResponse({"error": "Unknown service"}, status_code=404)
    from pathlib import Path
    stack_dir = dir_map[name]
    if not Path(stack_dir).exists():
        return JSONResponse({"error": "Stack directory not found"}, status_code=404)
    docker = get_docker()
    code, stdout, stderr = docker.compose_restart(stack_dir)
    if code != 0:
        return JSONResponse({"error": stderr}, status_code=500)
    return {"success": True, "name": name}


@router.post("/{name}/update")
def service_update(name: str, req: ConfirmRequest):
    if not req.confirmed:
        return JSONResponse({"error": "Confirmation explicite requise."}, status_code=422)
    dir_map = {
        "traefik": str(TRAEFIK_DIR),
        "oauth2": str(OAUTH2_DIR),
        "crowdsec": str(CROWDSEC_DIR),
    }
    if name not in dir_map:
        return JSONResponse({"error": "Unknown service"}, status_code=404)
    from pathlib import Path
    stack_dir = dir_map[name]
    if not Path(stack_dir).exists():
        return JSONResponse({"error": "Stack directory not found"}, status_code=404)
    docker = get_docker()
    code, stdout, stderr = docker.compose_pull(stack_dir)
    if code != 0:
        return JSONResponse({"error": stderr or stdout}, status_code=500)
    code, stdout, stderr = docker.compose_up(stack_dir)
    if code != 0:
        return JSONResponse({"error": stderr}, status_code=500)
    return {"success": True, "name": name}
