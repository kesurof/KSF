import subprocess
import ipaddress
import re
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from ..core.config import get_config, CROWDSEC_DIR
from ..core.docker import get_docker
from ..core.ksf_cli import run_ksf
from ..core.schemas import BanRequest, ConfirmRequest, UnbanRequest

router = APIRouter()


def _cscli(*args: str) -> tuple[int, str, str]:
    cfg = get_config()
    if not cfg.has_crowdsec():
        return -1, "", "CrowdSec n'est pas configure."
    cs_dir = str(CROWDSEC_DIR)
    if not (CROWDSEC_DIR / "docker-compose.yml").exists():
        return -1, "", "La stack CrowdSec est introuvable."
    try:
        result = subprocess.run(
            [*get_docker().compose_command(), "exec", "-T", "crowdsec", "cscli", *args],
            cwd=cs_dir, capture_output=True, text=True, timeout=30
        )
        return result.returncode, result.stdout, result.stderr
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return -1, "", str(e)


@router.get("/status")
def crowdsec_status():
    cfg = get_config()
    if not cfg.has_crowdsec():
        return {"enabled": False}
    from pathlib import Path
    if not (CROWDSEC_DIR / "docker-compose.yml").exists():
        return {"enabled": True, "state": "stack absente"}
    from ..core.docker import get_docker
    docker = get_docker()
    state = docker.stack_state(str(CROWDSEC_DIR))
    return {"enabled": True, **state}


@router.get("/alerts")
def crowdsec_alerts():
    rc, stdout, stderr = _cscli("alerts", "list")
    if rc != 0:
        return JSONResponse({"error": stderr}, status_code=500)
    return {"output": stdout}


@router.get("/metrics")
def crowdsec_metrics():
    rc, stdout, stderr = _cscli("metrics")
    if rc != 0:
        return JSONResponse({"error": stderr}, status_code=500)
    return {"output": stdout}


@router.get("/bouncers")
def crowdsec_bouncers():
    rc, stdout, stderr = _cscli("bouncers", "list")
    if rc != 0:
        return JSONResponse({"error": stderr}, status_code=500)
    return {"output": stdout}


@router.post("/ban")
def crowdsec_ban(req: BanRequest):
    if not req.confirmed:
        return JSONResponse({"error": "Confirmation explicite requise."}, status_code=422)
    try:
        ipaddress.ip_address(req.ip)
    except ValueError:
        return JSONResponse({"error": "Adresse IP invalide."}, status_code=422)
    if not re.fullmatch(r"[1-9][0-9]*[smhdw]", req.duration):
        return JSONResponse({"error": "La duree doit etre par exemple 4h ou 30m."}, status_code=422)
    rc, stdout, stderr = _cscli("decisions", "add", "--ip", req.ip, "-d", req.duration)
    if rc != 0:
        return JSONResponse({"error": stderr}, status_code=500)
    return {"success": True, "output": stdout}


@router.post("/unban")
def crowdsec_unban(req: UnbanRequest):
    if not req.confirmed:
        return JSONResponse({"error": "Confirmation explicite requise."}, status_code=422)
    try:
        ipaddress.ip_address(req.ip)
    except ValueError:
        return JSONResponse({"error": "Adresse IP invalide."}, status_code=422)
    rc, stdout, stderr = _cscli("decisions", "delete", "--ip", req.ip)
    if rc != 0:
        return JSONResponse({"error": stderr}, status_code=500)
    return {"success": True, "output": stdout}


@router.get("/decisions")
def crowdsec_decisions():
    rc, stdout, stderr = _cscli("decisions", "list")
    if rc != 0:
        return JSONResponse({"error": stderr}, status_code=500)
    return {"output": stdout}


@router.get("/console/status")
def crowdsec_console_status():
    rc, stdout, stderr = run_ksf("crowdsec", "console-status", timeout=60)
    if rc != 0:
        return JSONResponse({"error": stderr or stdout or "Console CrowdSec indisponible."}, status_code=500)
    return {"output": stdout}


@router.get("/appsec/status")
def appsec_status():
    cfg = get_config()
    if not cfg.has_crowdsec():
        return {"enabled": False}
    appsec_file = CROWDSEC_DIR / "appsec.yaml"
    return {
        "enabled": cfg.has_appsec(),
        "appsec_yaml_present": appsec_file.exists(),
    }


@router.post("/restart")
def crowdsec_restart(req: ConfirmRequest):
    if not req.confirmed:
        return JSONResponse({"error": "Confirmation explicite requise."}, status_code=422)
    from ..core.docker import get_docker
    docker = get_docker()
    code, stdout, stderr = docker.compose_restart(str(CROWDSEC_DIR))
    if code != 0:
        return JSONResponse({"error": stderr}, status_code=500)
    return {"success": True}


@router.post("/decisions/flush")
def crowdsec_flush(req: ConfirmRequest):
    if not req.confirmed:
        return JSONResponse({"error": "Confirmation explicite requise."}, status_code=422)
    rc, stdout, stderr = _cscli("decisions", "delete", "--all")
    if rc != 0:
        return JSONResponse({"error": stderr}, status_code=500)
    return {"success": True, "output": stdout}
