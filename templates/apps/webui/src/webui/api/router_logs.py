from fastapi import APIRouter
from fastapi.responses import JSONResponse
from ..core.config import TRAEFIK_DIR, OAUTH2_DIR, CROWDSEC_DIR
from ..core.docker import get_docker
from ..core.security import redact_secrets

router = APIRouter()


@router.get("/{target}")
def get_logs(target: str, tail: int = 200):
    tail = max(1, min(tail, 5000))
    dir_map = {
        "traefik": str(TRAEFIK_DIR),
        "oauth2": str(OAUTH2_DIR),
        "crowdsec": str(CROWDSEC_DIR),
    }
    from pathlib import Path
    if target in dir_map:
        stack_dir = dir_map[target]
        if not Path(stack_dir).exists():
            return JSONResponse({"error": "Stack directory not found"}, status_code=404)
        docker = get_docker()
        logs = docker.compose_logs(stack_dir, tail=tail)
        return {"logs": redact_secrets(logs)}
    from ..core.state import get_installed_app
    app = get_installed_app(target)
    if not app:
        return JSONResponse({"error": f"Unknown target '{target}'"}, status_code=404)
    docker = get_docker()
    logs = docker.compose_logs(app.app_dir, tail=tail)
    return {"logs": redact_secrets(logs)}
