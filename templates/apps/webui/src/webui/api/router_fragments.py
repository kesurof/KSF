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
from ..core.state import (get_installed_app, list_available_templates,
                          list_installed_apps, list_route_files)
from ..templates import templates
from ..core.schemas import ConfigureRequest, InstallRequest
from .router_apps import configure_app, install_app, start_app
from .router_config import _categorize
from .router_crowdsec import appsec_status, crowdsec_alerts, crowdsec_status
from .router_logs import get_logs

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
    return _render(request, "install", form_success="Installation lancée avec succès.")


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
    action = "Activation" if app.disabled else "Démarrage"
    return _render(request, "app-detail", app=app, state=state,
                   lifecycle_success=f"{action} lancée avec succès.")


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
                   form_success="Reconfiguration lancée avec succès.")


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
    return _render(request, "infrastructure-detail", service_name=name)


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


@router.get("/security/{surface}", response_class=HTMLResponse)
async def security_surface(request: Request, surface: str):
    if surface == "crowdsec":
        return _render(request, "security-detail", title="CrowdSec", security_state=crowdsec_status())
    if surface == "appsec":
        return _render(request, "security-detail", title="AppSec", security_state=appsec_status())
    if surface == "alerts":
        result = crowdsec_alerts()
        if isinstance(result, Response):
            return _result(request, "Alertes CrowdSec", error=result.body.decode(), status_code=result.status_code)
        return _result(request, "Alertes CrowdSec", output=result["output"])
    return _render(request, "error", status_code=404, message="Vue de sécurité inconnue.")


@router.get("/maintenance", response_class=HTMLResponse)
async def maintenance(request: Request):
    from .router_maintenance import list_clean_data
    return _render(request, "maintenance", clean_data=(await list_clean_data())["directories"])


@router.get("/maintenance/operations", response_class=HTMLResponse)
async def maintenance_operations(request: Request):
    return _render(request, "maintenance-operations", jobs=await list_recent_jobs())
