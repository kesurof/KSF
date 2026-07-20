"""Server-rendered HTMX surfaces for the administration UI.

The JSON API remains available to CLI consumers.  Browser pages use this router
so that the server, rather than Alpine, owns displayed platform state.
"""
import json

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, Response

from ..core.config import CROWDSEC_DIR, OAUTH2_DIR, TRAEFIK_DIR, get_config
from ..core.docker import get_docker
from ..core.jobs import list_recent_jobs
from ..core.security import redact_secrets
from ..core.state import (get_installed_app, list_available_templates,
                          list_installed_apps, list_route_files)
from ..templates import templates
from ..core.schemas import ConfigureRequest, InstallRequest
from .router_apps import configure_app, install_app, start_app
from .router_config import _categorize
from .router_crowdsec import (appsec_status, crowdsec_alerts, crowdsec_status,
                              crowdsec_bouncers, crowdsec_decisions, crowdsec_metrics,
                              crowdsec_console_status)
from .router_logs import get_logs
from .router_operations import dns_configuration

router = APIRouter()


def _apps():
    docker = get_docker()
    result = []
    for app in list_installed_apps():
        result.append((app, docker.stack_state(app.app_dir, app.docker_service)))
    return result


def _context(view: str, **extra):
    cfg = get_config()
    context = {
        "view": view,
        "config": cfg,
        "apps": _apps(),
        "routes": list_route_files(),
        "templates_available": list_available_templates(),
    }
    context.update(extra)
    return context


def _render(request: Request, view: str, status_code: int = 200, **extra):
    return templates.TemplateResponse(
        request, "fragments/content.html", _context(view, **extra), status_code=status_code
    )


def _result(request: Request, title: str, output: str = "", status_code: int = 200,
            error: str = ""):
    return templates.TemplateResponse(request, "fragments/result.html", {
        "title": title, "output": output, "error": error,
    }, status_code=status_code)


def _dns_status(cfg):
    dns = dns_configuration()
    return {
        "enabled": dns.get("enabled", False),
        "provider": dns.get("provider", ""),
        "email_configured": dns.get("email_configured", False),
        "api_key_configured": dns.get("api_key_configured", False),
        "server_public_ip_configured": dns.get("server_public_ip_configured", False),
    }


@router.get("/operations", response_class=HTMLResponse)
async def operations(request: Request):
    cfg = get_config()
    return _render(request, "operations", dns_status=_dns_status(cfg))


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    return _render(request, "dashboard")


@router.get("/apps", response_class=HTMLResponse)
async def apps(request: Request):
    return _render(request, "apps")


@router.get("/apps/install", response_class=HTMLResponse)
async def app_install(request: Request):
    return _render(request, "install")


@router.post("/apps/install", response_class=HTMLResponse)
async def install_from_form(
    request: Request, template: str = Form(...), instance: str = Form("")
):
    """Adapt the existing validated install operation to an HTMX form response."""
    result = install_app(InstallRequest(template=template, instance=instance or template))
    if isinstance(result, Response) and result.status_code >= 400:
        return _render(request, "install", status_code=result.status_code,
                       form_error=result.body.decode())
    return _render(request, "install", form_success="Installation en file d'attente.")


@router.get("/apps/{instance}", response_class=HTMLResponse)
async def app_detail(request: Request, instance: str):
    app = get_installed_app(instance)
    if not app:
        return _render(request, "error", status_code=404,
                       message="Cette application est introuvable.")
    state = get_docker().stack_state(app.app_dir, app.docker_service)
    return _render(request, "app-detail", app=app, state=state)


@router.post("/apps/{instance}/start", response_class=HTMLResponse)
async def start_from_fragment(request: Request, instance: str):
    """Delegate the fragment control to the server-confirmed lifecycle job."""
    result = start_app(instance)
    app = get_installed_app(instance)
    if not app:
        return _render(request, "error", status_code=404,
                       message="Cette application est introuvable.")
    state = get_docker().stack_state(app.app_dir, app.docker_service)
    if isinstance(result, Response) and result.status_code >= 400:
        try:
            error = json.loads(result.body).get("error", "Action indisponible.")
        except json.JSONDecodeError:
            error = "Action indisponible."
        return _render(request, "app-detail", status_code=result.status_code,
                       app=app, state=state, lifecycle_error=error)
    return _render(request, "app-detail", app=app, state=state,
                   lifecycle_success="Action en file d'attente.")


@router.post("/apps/{instance}/stop", response_class=HTMLResponse)
async def stop_app_fragment(request: Request, instance: str):
    from .router_apps import stop_app as api_stop_app
    app = get_installed_app(instance)
    if not app:
        return _render(request, "error", status_code=404,
                       message="Cette application est introuvable.")
    result = api_stop_app(instance)
    state = get_docker().stack_state(app.app_dir, app.docker_service)
    if isinstance(result, Response) and result.status_code >= 400:
        try:
            error = json.loads(result.body).get("error", "Action indisponible.")
        except json.JSONDecodeError:
            error = "Action indisponible."
        return _render(request, "app-detail", status_code=result.status_code,
                       app=app, state=state, lifecycle_error=error)
    return _render(request, "app-detail", app=app, state=state,
                   lifecycle_success="Action en file d'attente.")


@router.post("/apps/{instance}/restart", response_class=HTMLResponse)
async def restart_app_fragment(request: Request, instance: str):
    from .router_apps import restart_app as api_restart_app
    app = get_installed_app(instance)
    if not app:
        return _render(request, "error", status_code=404,
                       message="Cette application est introuvable.")
    result = api_restart_app(instance)
    state = get_docker().stack_state(app.app_dir, app.docker_service)
    if isinstance(result, Response) and result.status_code >= 400:
        try:
            error = json.loads(result.body).get("error", "Action indisponible.")
        except json.JSONDecodeError:
            error = "Action indisponible."
        return _render(request, "app-detail", status_code=result.status_code,
                       app=app, state=state, lifecycle_error=error)
    return _render(request, "app-detail", app=app, state=state,
                   lifecycle_success="Action en file d'attente.")


@router.post("/apps/{instance}/update", response_class=HTMLResponse)
async def update_app_fragment(request: Request, instance: str):
    from .router_apps import update_app as api_update_app
    app = get_installed_app(instance)
    if not app:
        return _render(request, "error", status_code=404,
                       message="Cette application est introuvable.")
    from ..core.schemas import ConfirmRequest
    result = api_update_app(instance, ConfirmRequest(confirmed=True))
    state = get_docker().stack_state(app.app_dir, app.docker_service)
    if isinstance(result, Response) and result.status_code >= 400:
        try:
            error = json.loads(result.body).get("error", "Action indisponible.")
        except json.JSONDecodeError:
            error = "Action indisponible."
        return _render(request, "app-detail", status_code=result.status_code,
                       app=app, state=state, lifecycle_error=error)
    return _render(request, "app-detail", app=app, state=state,
                   lifecycle_success="Action en file d'attente.")


@router.post("/apps/{instance}/rebuild", response_class=HTMLResponse)
async def rebuild_app_fragment(request: Request, instance: str):
    from .router_apps import rebuild_app as api_rebuild_app
    app = get_installed_app(instance)
    if not app:
        return _render(request, "error", status_code=404,
                       message="Cette application est introuvable.")
    from ..core.schemas import ConfirmRequest
    result = api_rebuild_app(instance, ConfirmRequest(confirmed=True))
    state = get_docker().stack_state(app.app_dir, app.docker_service)
    if isinstance(result, Response) and result.status_code >= 400:
        try:
            error = json.loads(result.body).get("error", "Action indisponible.")
        except json.JSONDecodeError:
            error = "Action indisponible."
        return _render(request, "app-detail", status_code=result.status_code,
                       app=app, state=state, lifecycle_error=error)
    return _render(request, "app-detail", app=app, state=state,
                   lifecycle_success="Action en file d'attente.")


@router.post("/apps/{instance}/disable", response_class=HTMLResponse)
async def disable_app_fragment(request: Request, instance: str):
    from .router_apps import disable_app as api_disable_app
    app = get_installed_app(instance)
    if not app:
        return _render(request, "error", status_code=404,
                       message="Cette application est introuvable.")
    from ..core.schemas import ConfirmRequest
    result = api_disable_app(instance, ConfirmRequest(confirmed=True))
    state = get_docker().stack_state(app.app_dir, app.docker_service)
    if isinstance(result, Response) and result.status_code >= 400:
        try:
            error = json.loads(result.body).get("error", "Action indisponible.")
        except json.JSONDecodeError:
            error = "Action indisponible."
        return _render(request, "app-detail", status_code=result.status_code,
                       app=app, state=state, lifecycle_error=error)
    return _render(request, "app-detail", app=app, state=state,
                   lifecycle_success="Action en file d'attente.")


@router.post("/apps/{instance}/remove", response_class=HTMLResponse)
async def remove_app_fragment(request: Request, instance: str):
    from ..core.schemas import RemoveRequest
    from .router_apps import remove_app as api_remove_app
    form = await request.form()
    confirmed = form.get("confirmed", "false") == "true"
    if not confirmed:
        return _render(request, "error", status_code=422, message="Confirmation requise.")
    remove_data = form.get("remove_data", "false") == "true"
    result = api_remove_app(instance, RemoveRequest(confirmed=confirmed, remove_data=remove_data))
    app = get_installed_app(instance)
    if isinstance(result, Response) and result.status_code >= 400:
        state = get_docker().stack_state(app.app_dir, app.docker_service) if app else {}
        lifecycle_error = json.loads(result.body).get("error", "Échec de la suppression.")
        return _render(request, "app-detail", status_code=result.status_code,
                       app=app, state=state, lifecycle_error=lifecycle_error)
    return _render(request, "apps")


@router.get("/apps/{instance}/logs", response_class=HTMLResponse)
async def app_logs(request: Request, instance: str, tail: int = 200):
    app = get_installed_app(instance)
    if not app:
        return _render(request, "error", status_code=404, message="Application introuvable.")
    from .router_apps import app_logs as get_app_logs
    result = get_app_logs(instance, tail)
    if isinstance(result, Response):
        return _result(request, f"Logs — {instance}", error=result.body.decode(), status_code=result.status_code)
    return _result(request, f"Logs — {instance}", output=redact_secrets(result.get("logs", "")))


@router.get("/apps/{instance}/configure", response_class=HTMLResponse)
async def app_configure(request: Request, instance: str):
    app = get_installed_app(instance)
    if not app:
        return _render(request, "error", status_code=404,
                       message="Cette application est introuvable.")
    return _render(request, "app-configure", app=app)


@router.post("/apps/{instance}/configure", response_class=HTMLResponse)
async def configure_from_form(
    request: Request, instance: str, domain: str = Form(""), subdomain: str = Form(""),
    host: str = Form(""), host_port: str = Form(""), no_host_port: bool = Form(False),
    local_only: bool = Form(False), confirmed: bool = Form(False),
):
    """Adapt the validated configuration operation to an HTMX form response."""
    result = configure_app(instance, ConfigureRequest(
        domain=domain, subdomain=subdomain, host=host, host_port=host_port,
        no_host_port=no_host_port, local_only=local_only, confirmed=confirmed,
    ))
    app = get_installed_app(instance)
    if isinstance(result, Response) and result.status_code >= 400:
        if not app:
            return _render(request, "error", status_code=result.status_code,
                           message="Cette application est introuvable.")
        try:
            error = json.loads(result.body).get("error", "Configuration invalide.")
        except json.JSONDecodeError:
            error = "Configuration invalide."
        return _render(request, "app-configure", status_code=result.status_code,
                       app=app, form_error=error)
    return _render(request, "app-configure", app=app,
                   form_success="Reconfiguration en file d'attente.")


@router.get("/infrastructure", response_class=HTMLResponse)
async def infrastructure(request: Request):
    cfg = get_config()
    docker = get_docker()
    services = []
    for name, enabled, directory in (
        ("traefik", cfg.has_traefik(), TRAEFIK_DIR),
        ("oauth2", cfg.has_oauth2(), OAUTH2_DIR),
        ("crowdsec", cfg.has_crowdsec(), CROWDSEC_DIR),
    ):
        state = docker.stack_state(str(directory)) if enabled and directory.exists() else {}
        services.append({"name": name, "enabled": enabled, "state": state})
    return _render(request, "infrastructure", services=services)


@router.get("/infrastructure/{name}", response_class=HTMLResponse)
async def infrastructure_detail(request: Request, name: str):
    if name not in {"traefik", "oauth2", "crowdsec"}:
        return _render(request, "error", status_code=404, message="Service inconnu.")
    return _render(request, "infrastructure-detail", service_name=name,
                   services_available=["traefik", "oauth2", "crowdsec"])


@router.get("/logs", response_class=HTMLResponse)
async def logs(request: Request):
    return _render(request, "logs")


@router.get("/logs/{target}", response_class=HTMLResponse)
async def log_output(request: Request, target: str, tail: int = 200):
    result = get_logs(target, tail)
    if isinstance(result, Response):
        return _result(request, "Logs", error=result.body.decode(),
                       status_code=result.status_code)
    return _result(request, "Logs", output=result["logs"])


@router.get("/general", response_class=HTMLResponse)
async def general(request: Request):
    from .router_status import _doctor_check
    return _render(request, "general", doctor=_doctor_check(get_config()),
                    jobs=await list_recent_jobs())


@router.get("/general/{surface}", response_class=HTMLResponse)
async def general_surface(request: Request, surface: str):
    if surface == "doctor":
        from .router_status import _doctor_check
        return _render(request, "general-detail", title="Diagnostic",
                       doctor=_doctor_check(get_config()))
    if surface == "routes":
        return _render(request, "general-detail", title="Routes", routes=list_route_files())
    if surface == "config":
        return _render(request, "general-detail", title="Configuration",
                       config_sections=_categorize(get_config().to_public_dict()))
    return _render(request, "error", status_code=404, message="Vue générale inconnue.")


@router.get("/security", response_class=HTMLResponse)
async def security(request: Request):
    return _render(request, "security")


@router.get("/security/ban", response_class=HTMLResponse)
async def security_ban_form(request: Request):
    return _render(request, "security-ban")


@router.get("/security/unban", response_class=HTMLResponse)
async def security_unban_form(request: Request):
    return _render(request, "security-unban")


@router.get("/security/{surface}", response_class=HTMLResponse)
async def security_surface(request: Request, surface: str):
    if surface == "crowdsec":
        result = crowdsec_status()
        if isinstance(result, dict):
            formatted = json.dumps(result, indent=2, ensure_ascii=False)
            return _result(request, "CrowdSec", output=formatted)
        return _render(request, "security-detail", title="CrowdSec", security_state=result)
    if surface == "appsec":
        result = appsec_status()
        if isinstance(result, dict):
            formatted = json.dumps(result, indent=2, ensure_ascii=False)
            return _result(request, "AppSec", output=formatted)
        return _render(request, "security-detail", title="AppSec", security_state=result)
    if surface == "alerts":
        result = crowdsec_alerts()
        if isinstance(result, Response):
            return _result(request, "Alertes CrowdSec", error=result.body.decode(), status_code=result.status_code)
        return _result(request, "Alertes CrowdSec", output=result["output"])
    if surface == "decisions":
        result = crowdsec_decisions()
        if isinstance(result, Response):
            return _result(request, "Décisions CrowdSec", error=result.body.decode(), status_code=result.status_code)
        return _result(request, "Décisions CrowdSec", output=result.get("output", ""))
    if surface == "metrics":
        result = crowdsec_metrics()
        if isinstance(result, Response):
            return _result(request, "Métriques CrowdSec", error=result.body.decode(), status_code=result.status_code)
        return _result(request, "Métriques CrowdSec", output=result.get("output", ""))
    if surface == "bouncers":
        result = crowdsec_bouncers()
        if isinstance(result, Response):
            return _result(request, "Bouncers CrowdSec", error=result.body.decode(), status_code=result.status_code)
        return _result(request, "Bouncers CrowdSec", output=result.get("output", ""))
    if surface == "console":
        result = crowdsec_console_status()
        if isinstance(result, Response):
            return _result(request, "Console CrowdSec", error=result.body.decode(), status_code=result.status_code)
        return _result(request, "Console CrowdSec", output=result.get("output", ""))
    return _render(request, "error", status_code=404, message="Vue de sécurité inconnue.")


@router.get("/maintenance", response_class=HTMLResponse)
async def maintenance(request: Request):
    from .router_maintenance import list_clean_data
    return _render(request, "maintenance", clean_data=(await list_clean_data())["directories"])


@router.get("/maintenance/operations", response_class=HTMLResponse)
async def maintenance_operations(request: Request):
    return _render(request, "maintenance-operations", jobs=await list_recent_jobs())


@router.post("/maintenance/clean-data/{app_name}", response_class=HTMLResponse)
async def clean_data_fragment(request: Request, app_name: str):
    from ..core.schemas import ConfirmRequest
    form = await request.form()
    confirmed = form.get("confirmed", "false") == "true"
    if not confirmed:
        return _result(request, "Nettoyage", error="Confirmation explicite requise.", status_code=422)
    from .router_maintenance import clean_data_app as api_clean_data
    result = await api_clean_data(app_name, ConfirmRequest(confirmed=True))
    if isinstance(result, Response) and result.status_code >= 400:
        try:
            error = json.loads(result.body).get("error", "Nettoyage impossible.")
        except json.JSONDecodeError:
            error = "Nettoyage impossible."
        return _result(request, "Nettoyage", error=error, status_code=result.status_code)
    return _result(request, "Nettoyage", output=f"Données de {app_name} supprimées avec succès.")
