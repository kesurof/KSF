"""Blueprints JSON / partials HTML / fichiers."""
import logging
import os
import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse

from app import config as app_config
from app import db as app_db
from app.helpers import (
    LOG_DIR,
    client_actor,
    now_str,
    require_valid_app,
    require_valid_container,
)
from app.services import audit, config_editor, jobs
from app.routes.pages import _T, build_dashboard_data

logger = logging.getLogger("ksf-web")
router = APIRouter()


# ── Dashboard summary (auto-refresh) ───────────────────────

@router.get("/api/dashboard/summary", response_class=HTMLResponse)
async def dashboard_summary(request: Request):
    data = build_dashboard_data()
    return _T(request).TemplateResponse("partials/dashboard_summary.html", {
        "request": request,
        "actions_enabled": app_config.ACTIONS_ENABLED,
        **data,
    })


# ── Container logs (download / stream registration) ────────

@router.get("/containers/{container_id}/logs")
async def container_logs(container_id: str, lines: int = 200):
    require_valid_container(container_id)
    from app import docker_client
    return PlainTextResponse(docker_client.get_container_logs(container_id, tail=min(lines, 500)))


# ── Action log viewer ──────────────────────────────────────

_LOG_NAME_RE = re.compile(r"[a-zA-Z0-9_.\-]+")


@router.get("/actions/logs/{log_name}", response_class=PlainTextResponse)
async def action_log(log_name: str):
    if not _LOG_NAME_RE.fullmatch(log_name):
        raise HTTPException(status_code=400, detail="Nom de log invalide")
    path = os.path.join(LOG_DIR, log_name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Log introuvable")
    try:
        with open(path, "r") as f:
            return PlainTextResponse(f.read())
    except OSError:
        raise HTTPException(status_code=500, detail="Impossible de lire le log")


# ── Apps install form (modal partial) ──────────────────────

@router.get("/apps/install-form/{app_name}", response_class=HTMLResponse)
async def app_install_form(app_name: str):
    require_valid_app(app_name)
    from app import ksf_commands
    available = ksf_commands.list_available_apps()
    template = next((a for a in available if a["name"] == app_name), None)
    if not template or template["installed"]:
        raise HTTPException(status_code=400, detail="Application non disponible")

    return _T(Request).TemplateResponse("partials/install_form.html", {
        "request": Request,
        "app_name": template["name"],
        "subdomain": template["name"],
        "port": str(template.get("port", "")),
        "protected": template.get("protected", True),
    })


# ── Jobs list (partial) ────────────────────────────────────

@router.get("/api/jobs/list", response_class=HTMLResponse)
async def jobs_list_partial(request: Request):
    items = await jobs.list_recent(limit=100)
    return _T(request).TemplateResponse("partials/jobs_list.html", {
        "request": request, "jobs": items, "now": now_str(),
    })


# ── Audit export ───────────────────────────────────────────

@router.get("/api/audit/export")
async def audit_export(fmt: str = "json", action: str | None = None,
                       target: str | None = None, actor: str | None = None):
    entries = await audit.list_entries(limit=10000, action=action, target=target, actor=actor)
    if fmt == "csv":
        return PlainTextResponse(audit.export_csv(entries), media_type="text/csv",
                                  headers={"Content-Disposition": 'attachment; filename="audit.csv"'})
    return PlainTextResponse(audit.export_json(entries), media_type="application/json",
                              headers={"Content-Disposition": 'attachment; filename="audit.json"'})


# ── Config editor ──────────────────────────────────────────

_PREVIEW_COOKIE = "ksf_config_preview"


@router.post("/api/config/preview")
async def config_preview(request: Request):
    form = await request.form()
    values = {k: v for k, v in form.items() if not k.startswith("_")}
    result = await config_editor.preview(values)
    if result.get("ok") and result.get("preview_id"):
        # Pose un cookie de session liant l'user à un preview récent.
        # Le commit doit présenter CE cookie (signature + non expiré).
        cookie = config_editor._sign_preview_cookie(result["preview_id"])
        result = JSONResponse(result)
        result.set_cookie(
            _PREVIEW_COOKIE, cookie,
            max_age=config_editor.PREVIEW_TOKEN_MAX_AGE,
            httponly=True, samesite="lax",
            secure=False,  # ksf-web est derrière OAuth2 Proxy qui gère TLS
            path="/",
        )
        return result
    return JSONResponse(result)


@router.post("/api/config/commit")
async def config_commit(request: Request):
    body = await request.json()
    proposed = body.get("proposed", "")
    if not proposed:
        raise HTTPException(status_code=400, detail="Contenu vide")
    preview_cookie = request.cookies.get(_PREVIEW_COOKIE)
    result = await config_editor.commit(proposed, preview_cookie, actor=client_actor(request))
    response = JSONResponse(result)
    # Sur succès, efface le cookie (un seul commit par preview)
    if result.get("ok") and result.get("stage") != "noop":
        response.delete_cookie(_PREVIEW_COOKIE, path="/")
    return response


# ── Backup download ────────────────────────────────────────

@router.get("/backups/{backup_name}/download")
async def backup_download(backup_name: str):
    from app.services import backups as backups_svc
    path = backups_svc._safe_path(backup_name)
    if path is None or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Backup introuvable")
    return FileResponse(
        path, filename=backup_name,
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="{backup_name}"'},
    )


# ── Status / config / routes (output ksf.sh) ───────────────

@router.get("/api/status")
async def api_status():
    """Output brut de `ksf.sh status`."""
    from app import ksf_commands
    ok, output = await ksf_commands.run_command("status", timeout=30)
    return PlainTextResponse(output, media_type="text/plain; charset=utf-8")


@router.get("/api/config-view")
async def api_config_view():
    """Output brut de `ksf.sh config` (secrets masqués côté script)."""
    from app import ksf_commands
    ok, output = await ksf_commands.run_command("config", timeout=30)
    return PlainTextResponse(output, media_type="text/plain; charset=utf-8")


@router.get("/api/routes")
async def api_routes():
    """Output brut de `ksf.sh routes` (analyse routes Traefik dynamiques)."""
    from app import ksf_commands
    ok, output = await ksf_commands.run_command("routes", timeout=30)
    return PlainTextResponse(output, media_type="text/plain; charset=utf-8")


# ── CrowdSec décisions (read-only) ─────────────────────────

@router.get("/api/security/crowdsec/decisions")
async def crowdsec_decisions():
    from app import ksf_commands
    ok, output = await ksf_commands.run_command("crowdsec_decisions", timeout=30)
    return PlainTextResponse(output, media_type="text/plain; charset=utf-8")


@router.get("/api/security/trusted-ips")
async def trusted_ips_list():
    from app import ksf_commands
    ok, output = await ksf_commands.run_command("trusted_ips_cloudflare", timeout=30)
    return PlainTextResponse(output, media_type="text/plain; charset=utf-8")


# ── Clean-data listing (apps avec données préservées) ──────

_DATA_DIR = os.path.join(app_config.BASE_DIR, "data")


@router.get("/api/data/list")
async def clean_data_list():
    """Liste les apps avec des données préservées dans ${BASE_DIR}/data."""
    items = []
    try:
        if os.path.isdir(_DATA_DIR):
            for name in sorted(os.listdir(_DATA_DIR)):
                path = os.path.join(_DATA_DIR, name)
                if not os.path.isdir(path):
                    continue
                try:
                    total = 0
                    file_count = 0
                    for root, _, files in os.walk(path):
                        for f in files:
                            try:
                                total += os.path.getsize(os.path.join(root, f))
                                file_count += 1
                            except OSError:
                                pass
                    items.append({
                        "name": name,
                        "size_bytes": total,
                        "file_count": file_count,
                    })
                except OSError:
                    items.append({"name": name, "size_bytes": 0, "file_count": 0})
    except Exception:
        logger.exception("Erreur listing data dir")
    return items


# ── Health endpoint (Phase 4.1) ────────────────────────────

@router.get("/health")
async def health():
    """Endpoint de monitoring : DB lisible + Docker joignable."""
    from app import docker_client
    db_status = "err"
    try:
        async for conn in app_db.get_conn():
            await conn.execute("SELECT 1")
            db_status = "ok"
            break
    except Exception:
        logger.exception("Health: DB check failed")
    docker_status = "err"
    try:
        client = docker_client.get_client()
        if client is not None:
            client.ping()
            docker_status = "ok"
    except Exception:
        logger.exception("Health: Docker check failed")
    overall = "ok" if (db_status == "ok" and docker_status == "ok") else "err"
    return JSONResponse({
        "status": overall,
        "db": db_status,
        "docker": docker_status,
        "version": __import__("app").__version__,
    }, status_code=200 if overall == "ok" else 503)


# ── Audit lazy-load endpoint (Phase 4.4) ──────────────────

@router.get("/api/audit/{entry_id}")
async def audit_entry(entry_id: int):
    """Renvoie une entrée d'audit unique avec before/after déchiffrés."""
    from app.services import audit
    entry = await audit.get_entry(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entrée d'audit introuvable")
    return entry


# ── Locks API (Phase 4.11) ─────────────────────────────────

@router.get("/api/locks")
async def list_locks():
    """Renvoie les lock_key actifs (jobs en cours)."""
    from app.services import jobs
    async for conn in app_db.get_conn():
        cur = await conn.execute(
            "SELECT lock_key, id, kind, started_at FROM jobs "
            "WHERE status='running' AND lock_key IS NOT NULL"
        )
        rows = await cur.fetchall()
        await cur.close()
        return [
            {"lock_key": r["lock_key"], "job_id": r["id"], "kind": r["kind"], "since": r["started_at"]}
            for r in rows
        ]
