from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..core.config import get_config
from ..core.jobs import start_job
from ..core.ksf_cli import run_ksf
from ..core.ksf_cli import run_app
from ..core.schemas import ConfirmRequest, CrowdsecEnrollRequest, OperationRequest
from ..core.state import list_installed_apps


router = APIRouter()


DRY_RUN_SUPPORTED = {
    "restart-infrastructure", "update-infrastructure", "update-applications",
    "render-platform", "protect-apps", "apply-trusted-ips", "appsec-enable",
    "appsec-disable", "appsec-metrics", "appsec-test",
}


def _queue(action: str, target: str, args: tuple[str, ...], req: OperationRequest):
    if not req.confirmed:
        return JSONResponse({"error": "Confirmation explicite requise."}, status_code=422)
    if req.dry_run and action not in DRY_RUN_SUPPORTED:
        return JSONResponse({"error": "Cette operation ne supporte pas de simulation."}, status_code=422)
    job_id, error = start_job(action, target, lambda: run_ksf(*args, dry_run=req.dry_run), dry_run=req.dry_run)
    if job_id is None:
        return JSONResponse({"error": error}, status_code=409)
    return JSONResponse({"job_id": job_id, "status": "pending"}, status_code=202)


@router.get("/dns")
def dns_configuration():
    cfg = get_config()
    return {
        "enabled": cfg.get_bool("DNS_AUTO_CREATE"),
        "provider": cfg.get("DNS_PROVIDER", "cloudflare"),
        "email_configured": bool(cfg.get("CF_API_EMAIL")),
        "api_key_configured": bool(cfg.get("CF_API_KEY")),
        "server_public_ip_configured": bool(cfg.get("SERVER_PUBLIC_IP")),
    }


@router.post("/infrastructure/restart")
def restart_infrastructure(req: OperationRequest):
    return _queue("restart-infrastructure", "infrastructure", ("restart",), req)


@router.post("/infrastructure/update-all")
def update_infrastructure(req: OperationRequest):
    return _queue("update-infrastructure", "infrastructure", ("update", "all"), req)


@router.post("/apps/update-all")
def update_all_apps(req: OperationRequest):
    if not req.confirmed:
        return JSONResponse({"error": "Confirmation explicite requise."}, status_code=422)

    def runner():
        output = []
        failed = False
        for app in list_installed_apps():
            if app.disabled:
                output.append(f"{app.instance}: ignoree (desactivee)")
                continue
            code, stdout, stderr = run_app(
                "update", app.instance, dry_run=req.dry_run, confirmed=True
            )
            output.append(f"=== {app.instance} ===\n{stdout}{stderr}".strip())
            failed = failed or code != 0
        doctor_code, doctor_stdout, doctor_stderr = run_ksf("doctor", timeout=180, dry_run=req.dry_run)
        output.append(f"=== doctor ===\n{doctor_stdout}{doctor_stderr}".strip())
        return (1 if failed or doctor_code != 0 else 0, "\n\n".join(output), "")

    job_id, error = start_job("update-applications", "applications", runner, dry_run=req.dry_run)
    if job_id is None:
        return JSONResponse({"error": error}, status_code=409)
    return JSONResponse({"job_id": job_id, "status": "pending"}, status_code=202)


@router.post("/render")
def render_platform(req: OperationRequest):
    return _queue("render-platform", "platform-render", ("render",), req)


@router.post("/protect")
def protect_apps(req: OperationRequest):
    return _queue("protect-apps", "platform-protect", ("protect",), req)


@router.post("/trusted-ips/cloudflare")
def fetch_cloudflare_ips(req: ConfirmRequest):
    return _queue("fetch-trusted-ips", "trusted-ips", ("trusted-ips", "cloudflare"), req)


@router.post("/trusted-ips/cloudflare/apply")
def apply_cloudflare_ips(req: OperationRequest):
    return _queue("apply-trusted-ips", "trusted-ips", ("trusted-ips", "apply", "cloudflare"), req)


@router.post("/crowdsec/enroll")
def enroll_crowdsec(req: CrowdsecEnrollRequest):
    if not req.confirmed:
        return JSONResponse({"error": "Confirmation explicite requise."}, status_code=422)
    job_id, error = start_job("crowdsec-enroll", "crowdsec", lambda: run_ksf("crowdsec", "enroll", req.token), secrets=(req.token,))
    if job_id is None:
        return JSONResponse({"error": error}, status_code=409)
    return JSONResponse({"job_id": job_id, "status": "pending"}, status_code=202)


@router.post("/crowdsec/appsec/{action}")
def appsec_action(action: str, req: OperationRequest):
    if action not in {"enable", "disable", "metrics", "test"}:
        return JSONResponse({"error": "Action AppSec inconnue."}, status_code=404)
    return _queue(f"appsec-{action}", "crowdsec-appsec", ("crowdsec", "appsec", action), req)
