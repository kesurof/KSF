import os
import logging
from datetime import datetime, timezone

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import docker_client, ksf_commands, security

logger = logging.getLogger("ksf-web")

app = FastAPI(title="KSF Web", docs_url=None, redoc_url=None)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATE_DIR)

ACTIONS_ENABLED = os.environ.get("KSF_WEB_ACTIONS_ENABLED", "true").lower() == "true"


def _now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _action_result(success: bool, message: str, output: str = "") -> dict:
    return {
        "success": success,
        "message": message,
        "output": output[:2000] if output else "",
        "timestamp": _now(),
    }


def _require_action():
    if not ACTIONS_ENABLED:
        raise HTTPException(status_code=403, detail="Actions desactivees")


def _require_valid_app(name: str):
    if not security.validate_app_name(name):
        raise HTTPException(status_code=400, detail="Nom d'application invalide")


def _require_valid_container(name: str):
    if not security.validate_container_name(name, docker_client.get_container_names()):
        raise HTTPException(status_code=404, detail="Container inconnu")


# ── Pages ──────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    containers, docker_error = [], None
    installed_apps, backups, backups_error = [], [], None

    try:
        containers, docker_error = docker_client.list_containers()
    except Exception:
        logger.exception("Erreur Docker")
        docker_error = "Docker indisponible"

    try:
        installed_apps = ksf_commands.list_installed_apps()
    except Exception:
        logger.exception("Erreur lecture apps")

    try:
        backups, backups_error = ksf_commands.list_backups()
    except Exception:
        logger.exception("Erreur lecture backups")

    running = sum(1 for c in containers if c["status"] == "running")
    stopped = sum(1 for c in containers if c["status"] in ("exited", "dead", "created"))
    unhealthy = sum(1 for c in containers if c["health"] == "unhealthy")

    infra = {
        "traefik": any(c["name"] == "traefik" and c["status"] == "running" for c in containers),
        "oauth2": any(c["name"] == "oauth2-proxy" and c["status"] == "running" for c in containers),
        "crowdsec": any(c["name"] == "crowdsec" and c["status"] == "running" for c in containers),
    }

    try:
        appsec_state = ksf_commands.get_appsec_state()
    except Exception:
        appsec_state = "indeterminate"

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "running": running, "stopped": stopped, "unhealthy": unhealthy,
        "total": len(containers), "docker_error": docker_error,
        "infra": infra, "appsec_state": appsec_state,
        "latest_backup": backups[0] if backups else None,
        "backups_error": backups_error,
        "installed_apps": installed_apps,
        "actions_enabled": ACTIONS_ENABLED, "now": _now(),
    })


@app.get("/containers", response_class=HTMLResponse)
async def containers_page(request: Request):
    containers, docker_error = [], None
    try:
        containers, docker_error = docker_client.list_containers()
    except Exception:
        logger.exception("Erreur Docker")
        docker_error = "Docker indisponible"
    return templates.TemplateResponse("containers.html", {
        "request": request, "containers": containers,
        "docker_error": docker_error, "now": _now(),
    })


@app.get("/containers/{container_id}", response_class=HTMLResponse)
async def container_detail(request: Request, container_id: str):
    _require_valid_container(container_id)
    container = docker_client.get_container(container_id)
    if container is None:
        raise HTTPException(status_code=404, detail="Container introuvable")
    logs = docker_client.get_container_logs(container_id, tail=200)
    return templates.TemplateResponse("container_detail.html", {
        "request": request, "container": container, "logs": logs,
        "actions_enabled": ACTIONS_ENABLED, "now": _now(),
    })


@app.get("/apps", response_class=HTMLResponse)
async def apps_page(request: Request):
    installed_apps, available_apps, docker_error = [], [], None
    try:
        installed_apps = ksf_commands.list_installed_apps()
    except Exception:
        logger.exception("Erreur lecture apps")
    try:
        available_apps = ksf_commands.list_available_apps()
    except Exception:
        logger.exception("Erreur lecture apps disponibles")
    try:
        containers, _ = docker_client.list_containers()
    except Exception:
        containers = []

    installed_names = {a["name"] for a in installed_apps}
    for app_info in installed_apps:
        app_containers = [
            c for c in containers
            if c["name"] == app_info["name"]
            or c["labels"].get("com.docker.compose.project", "") == app_info["name"]
        ]
        app_info["containers"] = app_containers
        app_info["status"] = "running" if any(c["status"] == "running" for c in app_containers) else "stopped"
        app_info["health"] = next((c["health"] for c in app_containers if c["health"] != "-"), "-")
        template_env = ksf_commands.get_installed_app_env(app_info["name"])
        app_info["description"] = template_env.get("APP_DESCRIPTION", "")
        app_info["category"] = template_env.get("APP_CATEGORY", "other")

    for app_info in available_apps:
        if app_info["name"] in installed_names:
            match = next(a for a in installed_apps if a["name"] == app_info["name"])
            app_info["status"] = match["status"]
            app_info["disabled"] = match.get("disabled", False)
        else:
            app_info["status"] = "available"
            app_info["disabled"] = False

    categories = sorted({a.get("category", "other") for a in available_apps})

    return templates.TemplateResponse("apps.html", {
        "request": request, "apps": installed_apps, "available_apps": available_apps,
        "categories": categories, "docker_error": docker_error,
        "actions_enabled": ACTIONS_ENABLED, "now": _now(),
    })


@app.get("/backups", response_class=HTMLResponse)
async def backups_page(request: Request):
    backups, backups_error = [], None
    try:
        backups, backups_error = ksf_commands.list_backups()
    except Exception:
        logger.exception("Erreur lecture backups")
        backups_error = "Erreur lecture backups"
    return templates.TemplateResponse("backups.html", {
        "request": request, "backups": backups, "backups_error": backups_error,
        "actions_enabled": ACTIONS_ENABLED, "now": _now(),
    })


@app.get("/security", response_class=HTMLResponse)
async def security_page(request: Request):
    crowdsec_enabled, appsec_state = False, "indeterminate"
    crowdsec_status, crowdsec_alerts, crowdsec_bouncers, appsec_status = "", "", "", ""

    try:
        ksf_env = ksf_commands.get_ksf_env()
        crowdsec_enabled = ksf_env.get("WITH_CROWDSEC", "false").lower() == "true"
    except Exception:
        logger.exception("Erreur lecture ksf.env")

    try:
        appsec_state = ksf_commands.get_appsec_state()
    except Exception:
        appsec_state = "indeterminate"

    if crowdsec_enabled:
        _, crowdsec_status = ksf_commands.run_command("crowdsec_status")
        _, crowdsec_alerts = ksf_commands.run_command("crowdsec_alerts")
        _, crowdsec_bouncers = ksf_commands.run_command("crowdsec_bouncers")

    if appsec_state == "active":
        _, appsec_status = ksf_commands.run_command("appsec_status")

    return templates.TemplateResponse("security.html", {
        "request": request, "crowdsec_enabled": crowdsec_enabled,
        "appsec_state": appsec_state, "crowdsec_status": crowdsec_status,
        "crowdsec_alerts": crowdsec_alerts, "crowdsec_bouncers": crowdsec_bouncers,
        "appsec_status": appsec_status, "actions_enabled": ACTIONS_ENABLED, "now": _now(),
    })


# ── Container actions ──────────────────────────────

@app.get("/containers/{container_id}/logs")
async def container_logs(container_id: str, lines: int = 200):
    _require_valid_container(container_id)
    return PlainTextResponse(docker_client.get_container_logs(container_id, tail=min(lines, 500)))


@app.post("/containers/{container_id}/restart")
async def container_restart(container_id: str):
    _require_action()
    _require_valid_container(container_id)
    ok = docker_client.restart_container(container_id)
    return _action_result(ok, f"Container {container_id} redemarre." if ok else f"Echec du redemarrage de {container_id}.")


@app.post("/containers/{container_id}/stop")
async def container_stop(container_id: str):
    _require_action()
    _require_valid_container(container_id)
    ok = docker_client.stop_container(container_id)
    return _action_result(ok, f"Container {container_id} arrete." if ok else f"Echec de l'arret de {container_id}.")


@app.post("/containers/{container_id}/start")
async def container_start(container_id: str):
    _require_action()
    _require_valid_container(container_id)
    ok = docker_client.start_container(container_id)
    return _action_result(ok, f"Container {container_id} demarre." if ok else f"Echec du demarrage de {container_id}.")


# ── App actions ────────────────────────────────────

@app.get("/apps/install-form/{app_name}", response_class=HTMLResponse)
async def app_install_form(app_name: str):
    _require_valid_app(app_name)
    available = ksf_commands.list_available_apps()
    template = next((a for a in available if a["name"] == app_name), None)
    if not template or template["installed"]:
        raise HTTPException(status_code=400, detail="Application non disponible")

    checked = "checked" if template["protected"] else ""
    html = (
        '<div class="install-form">'
        '<div class="form-field"><label>Sous-domaine</label>'
        '<input type="text" id="install-subdomain" value="' + app_name + '" class="form-input"></div>'
        '<div class="form-field"><label>Port</label>'
        '<input type="text" id="install-port" value="' + template["port"] + '" class="form-input"></div>'
        '<div class="form-field"><label class="form-checkbox">'
        '<input type="checkbox" id="install-protected" ' + checked + '> Protéger avec OAuth2'
        '</label></div>'
        '<button class="btn btn-primary" style="width:100%;margin-top:0.5rem"'
        ' hx-post="/apps/' + app_name + '/install"'
        " hx-vals='js:{\"subdomain\":document.getElementById(\"install-subdomain\").value,\"port\":document.getElementById(\"install-port\").value,\"protected\":document.getElementById(\"install-protected\").checked}'"
        ' hx-on::after-request="if(event.detail.xhr.status===200){closeInstallModal();showToast(JSON.parse(event.detail.xhr.responseText).message,true)}else{showToast(JSON.parse(event.detail.xhr.responseText).detail,false)}">'
        "Confirmer</button></div>"
    )
    return HTMLResponse(content=html)


@app.post("/apps/{app_name}/install")
async def app_install(app_name: str):
    _require_action()
    _require_valid_app(app_name)
    available = ksf_commands.list_available_apps()
    template = next((a for a in available if a["name"] == app_name), None)
    if not template or template["installed"]:
        raise HTTPException(status_code=400, detail="Application non disponible")
    ok, output = ksf_commands.run_app_command(app_name, "install")
    return _action_result(ok, f"Installation de {app_name} lancee." if ok else f"Echec de l'installation de {app_name}.", output)


@app.post("/apps/{app_name}/update")
async def app_update(app_name: str):
    _require_action()
    _require_valid_app(app_name)
    ok, output = ksf_commands.run_app_command(app_name, "update")
    return _action_result(ok, f"Mise a jour de {app_name} lancee." if ok else f"Echec de la mise a jour de {app_name}.", output)


@app.post("/apps/{app_name}/restart")
async def app_restart(app_name: str):
    _require_action()
    _require_valid_app(app_name)
    ok, output = ksf_commands.run_app_command(app_name, "restart")
    return _action_result(ok, f"Redemarrage de {app_name} lance." if ok else f"Echec du redemarrage de {app_name}.", output)


@app.post("/apps/{app_name}/start")
async def app_start(app_name: str):
    _require_action()
    _require_valid_app(app_name)
    ok, output = ksf_commands.run_app_command(app_name, "start")
    return _action_result(ok, f"Demarrage de {app_name} lance." if ok else f"Echec du demarrage de {app_name}.", output)


@app.post("/apps/{app_name}/stop")
async def app_stop(app_name: str):
    _require_action()
    _require_valid_app(app_name)
    ok, output = ksf_commands.run_app_command(app_name, "stop")
    return _action_result(ok, f"Arret de {app_name} lance." if ok else f"Echec de l'arret de {app_name}.", output)


@app.post("/apps/{app_name}/disable")
async def app_disable(app_name: str):
    _require_action()
    _require_valid_app(app_name)
    ok, output = ksf_commands.run_app_command(app_name, "disable")
    return _action_result(ok, f"Desactivation de {app_name} lancee." if ok else f"Echec de la desactivation de {app_name}.", output)


@app.post("/apps/{app_name}/remove")
async def app_remove(app_name: str):
    _require_action()
    _require_valid_app(app_name)
    ok, output = ksf_commands.run_app_command(app_name, "remove")
    return _action_result(ok, f"Suppression de {app_name} lancee." if ok else f"Echec de la suppression de {app_name}.", output)


# ── Backup actions ─────────────────────────────────

@app.post("/backups/create")
async def backup_create():
    _require_action()
    ok, output = ksf_commands.run_command("backup_create")
    return _action_result(ok, "Backup creee." if ok else "Echec de la creation du backup.", output)


@app.post("/backups/verify")
async def backup_verify():
    _require_action()
    ok, output = ksf_commands.run_command("backup_verify_latest")
    return _action_result(ok, "Verification terminee." if ok else "Echec de la verification.", output)


@app.post("/backups/restore-dryrun")
async def backup_restore_dryrun():
    _require_action()
    ok, output = ksf_commands.run_command("backup_restore_latest_dryrun")
    return _action_result(ok, "Simulation de restauration terminee." if ok else "Echec de la simulation.", output)


# ── System actions ─────────────────────────────────

@app.post("/security/refresh")
async def security_refresh():
    _require_action()
    results = {}
    try:
        ksf_env = ksf_commands.get_ksf_env()
        if ksf_env.get("WITH_CROWDSEC", "false").lower() == "true":
            ok1, out1 = ksf_commands.run_command("crowdsec_alerts")
            results["alerts"] = _action_result(ok1, "Alertes rafraichies.", out1)
            ok2, out2 = ksf_commands.run_command("crowdsec_bouncers")
            results["bouncers"] = _action_result(ok2, "Bouncers rafraichis.", out2)
    except Exception:
        pass
    return results


@app.post("/system/doctor")
async def system_doctor():
    _require_action()
    ok, output = ksf_commands.run_command("doctor")
    return _action_result(ok, "Diagnostic termine." if ok else "Erreur lors du diagnostic.", output)


@app.post("/system/update-all")
async def system_update_all():
    _require_action()
    ok, output = ksf_commands.run_command("update_all")
    return _action_result(ok, "Mise a jour lancee." if ok else "Echec de la mise a jour.", output)
