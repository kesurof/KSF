"""Blueprints JSON / partials HTML / fichiers."""
import json
import logging
import os
import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates

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
async def app_install_form(request: Request, app_name: str):
    require_valid_app(app_name)
    from app import ksf_commands
    available = ksf_commands.list_available_apps()
    template = next((a for a in available if a["name"] == app_name), None)
    if not template or template["installed"]:
        raise HTTPException(status_code=400, detail="Application non disponible")

    return _T(request).TemplateResponse("partials/install_form.html", {
        "request": request,
        "app_name": template["name"],
        "description": template.get("description", ""),
        "category": template.get("category", "other"),
        "subdomain": template["name"],
        "port": str(template.get("port", "")),
        "protected": template.get("protected", True),
    })


# ── Jobs list (partial) ────────────────────────────────────

@router.get("/api/jobs/list", response_class=HTMLResponse)
async def jobs_list_partial(request: Request, before: str | None = None):
    items = await jobs.list_recent(limit=100, before=before)
    return _T(request).TemplateResponse("partials/jobs_list.html", {
        "request": request, "jobs": items, "now": now_str(),
        "next_before": items[-1]["created_at"] if items else None,
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


# ── Container stats (P3.12) ─────────────────────────────────

@router.get("/api/containers/{container_id}/stats")
async def container_stats(container_id: str):
    """Stats one-shot (CPU%, mem, net) pour un container."""
    from app import docker_client
    require_valid_container(container_id)
    stats = docker_client.get_container_stats(container_id)
    if stats is None:
        raise HTTPException(status_code=404, detail="Stats indisponibles")
    return stats


# ── Webhook health check (P3.13) ────────────────────────────

@router.post("/api/webhooks/{endpoint_id}/health")
async def webhook_health_check(endpoint_id: str, request: Request):
    """Ping un webhook pour vérifier qu'il est joignable.
    Renvoie {ok, status, latency_ms, error}."""
    from app.services import webhooks as webhooks_svc
    ep = await webhooks_svc.get(endpoint_id)
    if not ep:
        raise HTTPException(status_code=404, detail="Webhook introuvable")
    result = await webhooks_svc.ping(ep)
    await audit_log(request, "webhook.health", endpoint_id, after=result)
    return result


# ── Logs viewer (Phase 7 — structured logs unifiés) ──────────


def _read_log_tail(log_path: str, max_lines: int) -> list[dict]:
    """Lit les N dernières lignes JSONL du fichier log, en ordre DESC puis reverse.

    Robuste aux lignes malformées (skip silencieusement).
    """
    out: list[dict] = []
    if not os.path.isfile(log_path):
        return out
    try:
        # Lecture efficace : seek à la fin, lire par blocs jusqu'à obtenir N lignes.
        block_size = 8192
        with open(log_path, "rb") as f:
            f.seek(0, os.SEEK_END)
            pos = f.tell()
            buf = b""
            lines: list[bytes] = []
            while pos > 0 and len(lines) < max_lines + 50:
                read_size = min(block_size, pos)
                pos -= read_size
                f.seek(pos)
                buf = f.read(read_size) + buf
                lines = buf.splitlines()
            # Tronque au bon nombre et parse
            for raw in lines[-max_lines:]:
                try:
                    out.append(json.loads(raw.decode("utf-8", errors="replace")))
                except (ValueError, UnicodeDecodeError):
                    continue
    except OSError:
        return out
    # Garde l'ordre chronologique (DESC → on inverse pour ASC).
    out.reverse()
    return out


def _filter_events(events: list[dict], levels: list[str] | None,
                   logger: str | None, target: str | None,
                   correlation_id: str | None) -> list[dict]:
    if levels:
        levels_u = {x.upper() for x in levels}
        events = [e for e in events if e.get("level", "").upper() in levels_u]
    if logger:
        events = [e for e in events if e.get("logger") == logger]
    if target:
        t = target.strip().lower()
        events = [
            e for e in events
            if (e.get("target") and t in str(e.get("target")).lower())
            or (e.get("args") and any(t in str(a).lower() for a in (e.get("args") or [])))
        ]
    if correlation_id:
        cid = correlation_id.strip()
        events = [e for e in events if e.get("correlation_id") == cid]
    return events


@router.get("/api/logs/recent", response_class=HTMLResponse)
async def logs_recent(
    request: Request,
    level: list[str] | None = None,
    logger: str | None = None,
    target: str | None = None,
    correlation_id: str | None = None,
    limit: int = 200,
):
    """Renvoie un partial HTML avec les derniers events du log structuré.

    `level` peut être fourni plusieurs fois (?level=INFO&level=ERROR) ou en
    virgules (level=INFO,ERROR). Les deux formes sont acceptées.
    """
    if limit > 1000:
        limit = 1000
    if limit < 1:
        limit = 50
    levels = []
    if level:
        for item in level:
            if not item:
                continue
            levels.extend([x.strip().upper() for x in item.split(",") if x.strip()])

    log_path = os.path.join(app_config.LOG_DIR, "ksf-web.log")
    events = _read_log_tail(log_path, limit)
    events = _filter_events(events, levels or None, logger, target, correlation_id)
    # Tronque les events aux fields utiles + formatte la date
    out = []
    for e in events[-limit:]:
        out.append({
            "ts": e.get("ts", ""),
            "level": e.get("level", "INFO"),
            "logger": e.get("logger", ""),
            "correlation_id": e.get("correlation_id", "-"),
            "msg": e.get("msg", ""),
            "stream": e.get("stream"),
            "target": e.get("target"),
            "n": e.get("n"),
        })

    templates = Jinja2Templates(directory=app_config.TEMPLATE_DIR)
    return templates.TemplateResponse("partials/logs_viewer.html", {
        "request": request,
        "events": out,
        "filters": {
            "levels": levels or [],
            "logger": logger or "",
            "target": target or "",
            "correlation_id": correlation_id or "",
            "limit": limit,
        },
    })


@router.get("/api/logs/correlation/{cid}", response_class=HTMLResponse)
async def logs_correlation(cid: str, request: Request, format: str = "html"):
    """Renvoie tous les events d'un correlation_id donné.

    Sources combinées : ksf-web.log (filtre) + audit_log SQLite (col correlation_id).
    Format par défaut : HTML partial (utilisé par l'expand panel). Avec
    ?format=json : JSON brut.
    """
    if not cid or len(cid) > 64 or not re.fullmatch(r"[a-zA-Z0-9_\-]+", cid):
        raise HTTPException(status_code=400, detail="correlation_id invalide")

    log_path = os.path.join(app_config.LOG_DIR, "ksf-web.log")
    raw = _read_log_tail(log_path, 10000)
    events = [e for e in raw if e.get("correlation_id") == cid]
    # Audit row lié
    audit_entry = None
    try:
        async for conn in app_db.get_conn():
            cur = await conn.execute(
                "SELECT id, actor, action, target, ip, ua, created_at, job_id "
                "FROM audit_log WHERE correlation_id=? ORDER BY id DESC LIMIT 1",
                (cid,),
            )
            row = await cur.fetchone()
            await cur.close()
            if row:
                audit_entry = dict(row)
    except Exception:
        logger.exception("logs_correlation: audit query failed")

    if format == "json":
        return JSONResponse({"events": events, "audit": audit_entry})

    templates = Jinja2Templates(directory=app_config.TEMPLATE_DIR)
    return templates.TemplateResponse("partials/log_correlation.html", {
        "request": request,
        "events": events,
        "audit": audit_entry,
    })


@router.get("/api/logs/download", response_class=PlainTextResponse)
async def logs_download(request: Request, file: str = "ksf-web.log"):
    """Renvoie le fichier log brut (ksf-web.log ou une rotation ksf-web.log.N)."""
    if not re.fullmatch(r"ksf-web\.log(\.[0-9]+)?", file):
        raise HTTPException(status_code=400, detail="Nom de fichier invalide")
    path = os.path.join(app_config.LOG_DIR, file)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Log introuvable")
    try:
        with open(path, "r", errors="replace") as f:
            content = f.read()
    except OSError:
        raise HTTPException(status_code=500, detail="Impossible de lire le log")
    return PlainTextResponse(content, media_type="text/plain; charset=utf-8")
