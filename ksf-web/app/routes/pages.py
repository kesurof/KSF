"""Blueprints GET HTML (pages)."""
import logging
import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app import config, docker_client, ksf_commands
from app.helpers import now_str, require_valid_container
from app.services import audit, config_editor, jobs, webhooks

logger = logging.getLogger("ksf-web")
router = APIRouter()
_templates: Jinja2Templates | None = None


def set_templates(t: Jinja2Templates) -> None:
    global _templates
    _templates = t


def _T(request: Request):
    assert _templates is not None, "Templates not set"
    return _templates


def _T_redirect(request: Request, location: str, status_code: int = 307) -> RedirectResponse:
    """Helper pour les redirections inter-pages (compat URLs legacy)."""
    return RedirectResponse(url=location, status_code=status_code)


def build_dashboard_data() -> dict:
    containers, docker_error = [], None
    installed_apps, backups, backups_error = [], [], None
    try:
        containers, docker_error = docker_client.list_containers_cached()
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

    for app_info in installed_apps:
        match = next((c for c in containers if c["name"] == app_info["name"]
                      or c["labels"].get("com.docker.compose.project", "") == app_info["name"]), None)
        app_info["status"] = "running" if match and match["status"] == "running" else "stopped"

    infra = {
        "traefik": any(c["name"] == "traefik" and c["status"] == "running" for c in containers),
        "oauth2": any(c["name"] == "oauth2-proxy" and c["status"] == "running" for c in containers),
        "crowdsec": any(c["name"] == "crowdsec" and c["status"] == "running" for c in containers),
    }
    try:
        appsec_state = ksf_commands.get_appsec_state()
    except Exception:
        appsec_state = "indeterminate"

    return {
        "running": running, "stopped": stopped, "unhealthy": unhealthy,
        "total": len(containers), "docker_error": docker_error,
        "infra": infra, "appsec_state": appsec_state,
        "latest_backup": backups[0] if backups else None,
        "backups_error": backups_error,
        "installed_apps": installed_apps,
    }


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    data = build_dashboard_data()
    return _T(request).TemplateResponse("dashboard.html", {
        "request": request,
        **data,
        "actions_enabled": config.ACTIONS_ENABLED, "now": now_str(),
    })


@router.get("/containers", response_class=HTMLResponse)
async def containers_page(request: Request):
    containers, docker_error = [], None
    try:
        containers, docker_error = docker_client.list_containers()
    except Exception:
        logger.exception("Erreur Docker")
        docker_error = "Docker indisponible"
    return _T(request).TemplateResponse("containers.html", {
        "request": request, "containers": containers,
        "docker_error": docker_error, "now": now_str(),
    })


@router.get("/containers/{container_id}", response_class=HTMLResponse)
async def container_detail(request: Request, container_id: str):
    require_valid_container(container_id)
    container = docker_client.get_container(container_id)
    if container is None:
        raise HTTPException(status_code=404, detail="Container introuvable")
    logs = docker_client.get_container_logs(container_id, tail=200)
    return _T(request).TemplateResponse("container_detail.html", {
        "request": request, "container": container, "logs": logs,
        "actions_enabled": config.ACTIONS_ENABLED, "now": now_str(),
    })


@router.get("/apps", response_class=HTMLResponse)
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

    return _T(request).TemplateResponse("apps.html", {
        "request": request, "apps": installed_apps, "available_apps": available_apps,
        "categories": categories, "docker_error": docker_error,
        "actions_enabled": config.ACTIONS_ENABLED, "now": now_str(),
    })


@router.get("/backups", response_class=HTMLResponse)
async def backups_page(request: Request):
    backups, backups_error = [], None
    try:
        backups, backups_error = ksf_commands.list_backups()
    except Exception:
        logger.exception("Erreur lecture backups")
        backups_error = "Erreur lecture backups"
    return _T(request).TemplateResponse("backups.html", {
        "request": request, "backups": backups, "backups_error": backups_error,
        "actions_enabled": config.ACTIONS_ENABLED, "now": now_str(),
    })


@router.get("/security", response_class=HTMLResponse)
async def security_page(request: Request, tab: str = "overview"):
    """Page sécurité unifiée avec 4 onglets : overview, crowdsec, appsec, trusted-ips."""
    crowdsec_enabled, appsec_state = False, "indeterminate"
    crowdsec_status, crowdsec_alerts, crowdsec_bouncers, appsec_status = "", "", "", ""
    decisions, trusted_ips_cidrs = "", ""

    try:
        ksf_env = ksf_commands.get_ksf_env()
        crowdsec_enabled = ksf_env.get("WITH_CROWDSEC", "false").lower() == "true"
        appsec_enabled = ksf_env.get("CROWDSEC_APPSEC_ENABLED", "false").lower() == "true"
    except Exception:
        logger.exception("Erreur lecture ksf.env")
        ksf_env, appsec_enabled = {}, False

    try:
        appsec_state = ksf_commands.get_appsec_state()
    except Exception:
        appsec_state = "indeterminate"

    if crowdsec_enabled and tab in ("overview", "crowdsec"):
        _, crowdsec_status = await ksf_commands.run_command("crowdsec_status")
        _, crowdsec_alerts = await ksf_commands.run_command("crowdsec_alerts")
        _, crowdsec_bouncers = await ksf_commands.run_command("crowdsec_bouncers")
    if tab == "crowdsec":
        _, decisions = await ksf_commands.run_command("crowdsec_decisions", timeout=30)
    if appsec_state == "active" and tab in ("overview", "appsec"):
        _, appsec_status = await ksf_commands.run_command("appsec_status")
    if tab == "trusted-ips":
        _, trusted_ips_cidrs = await ksf_commands.run_command("trusted_ips_cloudflare", timeout=30)

    return _T(request).TemplateResponse("security.html", {
        "request": request, "tab": tab,
        "crowdsec_enabled": crowdsec_enabled,
        "appsec_enabled": appsec_enabled,
        "appsec_state": appsec_state,
        "crowdsec_status": crowdsec_status,
        "crowdsec_alerts": crowdsec_alerts,
        "crowdsec_bouncers": crowdsec_bouncers,
        "appsec_status": appsec_status,
        "decisions": decisions or "Indisponible",
        "trusted_ips_cidrs": trusted_ips_cidrs or "Indisponible",
        "ksf_env": ksf_env,
        "actions_enabled": config.ACTIONS_ENABLED, "now": now_str(),
    })


# Redirections pour les anciennes URLs (compatibilité bookmarks)
@router.get("/security/crowdsec", response_class=HTMLResponse)
async def security_crowdsec_legacy(request: Request):
    return _T_redirect(request, "/security?tab=crowdsec")


@router.get("/security/appsec", response_class=HTMLResponse)
async def security_appsec_legacy(request: Request):
    return _T_redirect(request, "/security?tab=appsec")


@router.get("/security/trusted-ips", response_class=HTMLResponse)
async def security_trusted_ips_legacy(request: Request):
    return _T_redirect(request, "/security?tab=trusted-ips")


@router.get("/jobs", response_class=HTMLResponse)
async def jobs_page(request: Request):
    items = await jobs.list_recent(limit=100)
    return _T(request).TemplateResponse("jobs.html", {
        "request": request, "jobs": items, "now": now_str(),
    })


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_detail(request: Request, job_id: str):
    job = await jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job introuvable")
    return _T(request).TemplateResponse("job_detail.html", {
        "request": request, "job": job, "now": now_str(),
    })


@router.get("/audit", response_class=HTMLResponse)
async def audit_page(request: Request,
                     action: str | None = None,
                     target: str | None = None,
                     actor: str | None = None):
    entries = await audit.list_entries(limit=200, action=action, target=target, actor=actor)
    return _T(request).TemplateResponse("audit.html", {
        "request": request, "entries": entries,
        "action": action, "target": target, "actor": actor, "now": now_str(),
    })


@router.get("/config", response_class=HTMLResponse)
async def config_page(request: Request):
    fields = config_editor.form_from_current()
    sections = {}
    for f in fields:
        sections.setdefault(f.get("section", "other"), []).append(f)
    versions = await config_editor.list_versions(limit=10)
    return _T(request).TemplateResponse("config.html", {
        "request": request, "fields": fields, "sections": sections,
        "versions": versions, "now": now_str(),
    })


@router.get("/settings/webhooks", response_class=HTMLResponse)
async def webhooks_page(request: Request):
    items = await webhooks.list_all()
    return _T(request).TemplateResponse("webhooks.html", {
        "request": request, "webhooks": items, "now": now_str(),
    })


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, tab: str = "general"):
    """Page Paramètres avec onglets : general, security, webhooks (alias)."""
    if tab not in ("general", "security"):
        tab = "general"
    ksf_env = ksf_commands.get_ksf_env()
    return _T(request).TemplateResponse("settings.html", {
        "request": request, "tab": tab, "now": now_str(),
        "actions_enabled": config.ACTIONS_ENABLED,
        "ksf_web_version": __import__("app").__version__,
        "base_dir": config.BASE_DIR,
        "tz_value": ksf_env.get("TZ_VALUE", "UTC"),
        "csrf_max_age_human": _human_duration(config.CSRF_MAX_AGE),
        "csrf_header": config.CSRF_HEADER,
        "fernet_key_path": config.FERNET_KEY_PATH,
        "audit_max_kb": 8,
        "job_retention_days": 30,
    })


def _human_duration(seconds: int) -> str:
    """Formate une durée en secondes en texte lisible."""
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}min"
    if seconds < 86400:
        h = seconds // 3600
        m = (seconds % 3600) // 60
        return f"{h}h{m:02d}min" if m else f"{h}h"
    d = seconds // 86400
    h = (seconds % 86400) // 3600
    return f"{d}j{h:02d}h" if h else f"{d}j"


# ── Phase 3a : pages de gestion plateforme ──────────────────

def _list_data_dir() -> list[dict]:
    """Liste les apps avec données préservées dans ${BASE_DIR}/data."""
    base = config.BASE_DIR
    data_dir = os.path.join(base, "data")
    items = []
    try:
        if os.path.isdir(data_dir):
            for name in sorted(os.listdir(data_dir)):
                p = os.path.join(data_dir, name)
                if not os.path.isdir(p):
                    continue
                total = 0
                file_count = 0
                for root, _, files in os.walk(p):
                    for f in files:
                        try:
                            total += os.path.getsize(os.path.join(root, f))
                            file_count += 1
                        except OSError:
                            pass
                items.append({"name": name, "size_bytes": total, "file_count": file_count})
    except Exception:
        logger.exception("Erreur listing data dir")
    return items


@router.get("/diagnostics", response_class=HTMLResponse)
async def diagnostics_page(request: Request, tab: str = "status"):
    """Page unifiée de diagnostics : status, routes, data."""
    output = {"status": "Indisponible", "routes": "Indisponible", "config": "Indisponible"}
    data_items: list[dict] = []

    if tab in ("status", "config"):
        status_out, _ = await ksf_commands.run_command("status", timeout=30)
        output["status"] = status_out or "Indisponible"
    if tab == "config":
        _, config_out = await ksf_commands.run_command("config", timeout=30)
        output["config"] = config_out or "Indisponible"
    if tab == "routes":
        _, routes_out = await ksf_commands.run_command("routes", timeout=30)
        output["routes"] = routes_out or "Indisponible"
    if tab == "data":
        data_items = _list_data_dir()

    return _T(request).TemplateResponse("diagnostics.html", {
        "request": request, "tab": tab, "output": output,
        "data_items": data_items, "now": now_str(),
        "actions_enabled": config.ACTIONS_ENABLED,
    })


# Redirections pour les anciennes URLs
@router.get("/status", response_class=HTMLResponse)
async def status_legacy(request: Request):
    return _T_redirect(request, "/diagnostics?tab=status")


@router.get("/routes", response_class=HTMLResponse)
async def routes_legacy(request: Request):
    return _T_redirect(request, "/diagnostics?tab=routes")


@router.get("/data", response_class=HTMLResponse)
async def data_legacy(request: Request):
    return _T_redirect(request, "/diagnostics?tab=data")


@router.get("/maintenance", response_class=HTMLResponse)
async def maintenance_page(request: Request):
    """Page d'actions de maintenance (restart, update ciblé)."""
    return _T(request).TemplateResponse("maintenance.html", {
        "request": request, "now": now_str(),
        "actions_enabled": config.ACTIONS_ENABLED,
    })


@router.get("/security/crowdsec", response_class=HTMLResponse)
async def security_crowdsec_page(request: Request):
    """Deprecated : redirige vers /security?tab=crowdsec."""
    return _T_redirect(request, "/security?tab=crowdsec")


@router.get("/security/appsec", response_class=HTMLResponse)
async def security_appsec_page(request: Request):
    """Deprecated : redirige vers /security?tab=appsec."""
    return _T_redirect(request, "/security?tab=appsec")


@router.get("/security/trusted-ips", response_class=HTMLResponse)
async def security_trusted_ips_page(request: Request):
    """Deprecated : redirige vers /security?tab=trusted-ips."""
    return _T_redirect(request, "/security?tab=trusted-ips")
