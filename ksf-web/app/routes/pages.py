"""Blueprints GET HTML (pages)."""
import logging
import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app import config, docker_client, ksf_commands
from app.helpers import now_str, require_valid_container
from app.services import audit, config_editor, jobs, notifications, webhooks

logger = logging.getLogger("ksf-web")
router = APIRouter()
_templates: Jinja2Templates | None = None


def set_templates(t: Jinja2Templates) -> None:
    global _templates
    _templates = t


def _T(request: Request):
    assert _templates is not None, "Templates not set"
    return _templates


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
        _, crowdsec_status = await ksf_commands.run_command("crowdsec_status")
        _, crowdsec_alerts = await ksf_commands.run_command("crowdsec_alerts")
        _, crowdsec_bouncers = await ksf_commands.run_command("crowdsec_bouncers")

    if appsec_state == "active":
        _, appsec_status = await ksf_commands.run_command("appsec_status")

    return _T(request).TemplateResponse("security.html", {
        "request": request, "crowdsec_enabled": crowdsec_enabled,
        "appsec_state": appsec_state, "crowdsec_status": crowdsec_status,
        "crowdsec_alerts": crowdsec_alerts, "crowdsec_bouncers": crowdsec_bouncers,
        "appsec_status": appsec_status, "actions_enabled": config.ACTIONS_ENABLED, "now": now_str(),
    })


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


@router.get("/notifications", response_class=HTMLResponse)
async def notifications_page(request: Request):
    items = await notifications.list_all(limit=100)
    unread = await notifications.count_unread()
    return _T(request).TemplateResponse("notifications.html", {
        "request": request, "notifications": items, "unread": unread, "now": now_str(),
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


# ── Phase 3a : pages de gestion plateforme ──────────────────

@router.get("/status", response_class=HTMLResponse)
async def status_page(request: Request):
    """Vue d'ensemble globale via ksf.sh status + ksf.sh config."""
    ksf_status, _ = await ksf_commands.run_command("status", timeout=30)
    _, ksf_config = await ksf_commands.run_command("config", timeout=30)
    return _T(request).TemplateResponse("status.html", {
        "request": request,
        "ksf_status": ksf_status or "Indisponible",
        "ksf_config": ksf_config or "Indisponible",
        "now": now_str(),
    })


@router.get("/routes", response_class=HTMLResponse)
async def routes_page(request: Request):
    """Analyse des routes Traefik dynamiques."""
    _, output = await ksf_commands.run_command("routes", timeout=30)
    return _T(request).TemplateResponse("routes.html", {
        "request": request, "output": output or "Indisponible", "now": now_str(),
    })


@router.get("/data", response_class=HTMLResponse)
async def clean_data_page(request: Request):
    """Liste les apps avec données préservées."""
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
    return _T(request).TemplateResponse("clean_data.html", {
        "request": request, "items": items, "now": now_str(),
        "actions_enabled": config.ACTIONS_ENABLED,
    })


@router.get("/maintenance", response_class=HTMLResponse)
async def maintenance_page(request: Request):
    """Page d'actions de maintenance (restart, update ciblé)."""
    return _T(request).TemplateResponse("maintenance.html", {
        "request": request, "now": now_str(),
        "actions_enabled": config.ACTIONS_ENABLED,
    })


@router.get("/security/crowdsec", response_class=HTMLResponse)
async def security_crowdsec_page(request: Request):
    """Page dédiée CrowdSec : décisions, ban/unban/flush."""
    enabled = False
    try:
        ksf_env = ksf_commands.get_ksf_env()
        enabled = ksf_env.get("WITH_CROWDSEC", "false").lower() == "true"
    except Exception:
        logger.exception("Erreur lecture ksf.env")
    _, decisions = await ksf_commands.run_command("crowdsec_decisions", timeout=30)
    return _T(request).TemplateResponse("security_crowdsec.html", {
        "request": request, "crowdsec_enabled": enabled,
        "decisions": decisions or "Indisponible",
        "now": now_str(), "actions_enabled": config.ACTIONS_ENABLED,
    })


@router.get("/security/appsec", response_class=HTMLResponse)
async def security_appsec_page(request: Request):
    """Page toggle AppSec / WAF."""
    ksf_env = ksf_commands.get_ksf_env()
    enabled = ksf_env.get("CROWDSEC_APPSEC_ENABLED", "false").lower() == "true"
    appsec_state = ksf_commands.get_appsec_state()
    return _T(request).TemplateResponse("security_appsec.html", {
        "request": request,
        "appsec_enabled": enabled,
        "appsec_state": appsec_state,
        "ksf_env": ksf_env,
        "now": now_str(), "actions_enabled": config.ACTIONS_ENABLED,
    })


@router.get("/security/trusted-ips", response_class=HTMLResponse)
async def security_trusted_ips_page(request: Request):
    """Page trusted IPs Cloudflare."""
    _, cidrs = await ksf_commands.run_command("trusted_ips_cloudflare", timeout=30)
    return _T(request).TemplateResponse("security_trusted_ips.html", {
        "request": request, "cidrs": cidrs or "Indisponible",
        "now": now_str(), "actions_enabled": config.ACTIONS_ENABLED,
    })
