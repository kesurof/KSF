import os
import re
import secrets
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, PlainTextResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from itsdangerous import URLSafeTimedSerializer, BadSignature

from app import config
from app import db
from app import docker_client, ksf_commands, security
from app.services import events, jobs, backups as backups_svc, config_editor, audit
from app.services import notifications, webhooks

logger = logging.getLogger("ksf-web")


@asynccontextmanager
async def lifespan(app):
    await db.init()
    await jobs.start_worker()
    logger.info("ksf-web démarré (DB=%s, jobs worker actif)", config.DB_PATH)
    try:
        yield
    finally:
        await jobs.stop_worker()
        await db.close()


app = FastAPI(title="KSF Web", docs_url=None, redoc_url=None, lifespan=lifespan)

app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")
templates = Jinja2Templates(directory=config.TEMPLATE_DIR)

ACTIONS_ENABLED = config.ACTIONS_ENABLED
LOG_DIR = config.LOG_DIR
OUTPUT_TRUNCATE_BYTES = config.OUTPUT_TRUNCATE_BYTES

_csrf_signer = URLSafeTimedSerializer(config.CSRF_SECRET, salt=config.CSRF_SALT)


# ── CSRF middleware (double-submit cookie) ─────────

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
CSRF_EXEMPT_PATHS = ("/static",)


def _issue_csrf() -> str:
    return _csrf_signer.dumps(secrets.token_urlsafe(24))


def _verify_csrf(token: str) -> bool:
    try:
        _csrf_signer.loads(token, max_age=config.CSRF_MAX_AGE)
        return True
    except BadSignature:
        return False


class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path
        if path.startswith(CSRF_EXEMPT_PATHS):
            return await call_next(request)

        if request.method in SAFE_METHODS:
            response = await call_next(request)
            if config.CSRF_COOKIE not in request.cookies:
                response.set_cookie(
                    config.CSRF_COOKIE, _issue_csrf(),
                    max_age=config.CSRF_MAX_AGE, httponly=False,
                    samesite="lax", secure=config.CSRF_COOKIE_SECURE, path="/",
                )
            return response

        cookie = request.cookies.get(config.CSRF_COOKIE, "")
        header = request.headers.get(config.CSRF_HEADER, "")

        if not cookie or not _verify_csrf(cookie):
            logger.warning("CSRF: cookie manquant ou invalide pour %s %s", request.method, path)
            return JSONResponse({"detail": "Jeton CSRF manquant ou invalide"}, status_code=403)

        if header:
            if header != cookie:
                logger.warning("CSRF: token header invalide pour %s %s", request.method, path)
                return JSONResponse({"detail": "Jeton CSRF invalide"}, status_code=403)
        else:
            ctype = request.headers.get("content-type", "")
            if "application/x-www-form-urlencoded" in ctype or "multipart/form-data" in ctype:
                form = await request.form()
                form_token = form.get(config.CSRF_FORM_FIELD, "")
                if not form_token or form_token != cookie:
                    logger.warning("CSRF: token form invalide pour %s %s", request.method, path)
                    return JSONResponse({"detail": "Jeton CSRF invalide"}, status_code=403)
            else:
                return JSONResponse({"detail": "Jeton CSRF manquant (header requis)"}, status_code=403)

        return await call_next(request)


app.add_middleware(CSRFMiddleware)


def _now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _truncate_output(output: str) -> tuple[str, str | None]:
    if not output:
        return "", None
    data = output.encode("utf-8", errors="replace")
    if len(data) <= OUTPUT_TRUNCATE_BYTES:
        return output, None
    truncated = data[:OUTPUT_TRUNCATE_BYTES].decode("utf-8", errors="replace")
    return truncated, "Sortie tronquee. Voir la sortie complete dans les logs."


def _action_result(success: bool, message: str, output: str = "", log_path: str | None = None) -> dict:
    truncated, note = _truncate_output(output)
    return {
        "success": success,
        "message": message,
        "output": truncated,
        "truncated": note is not None,
        "log_path": log_path,
        "timestamp": _now(),
    }


def _save_full_output(prefix: str, output: str) -> str:
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = os.path.join(LOG_DIR, f"{prefix}-{ts}.log")
        with open(path, "w") as f:
            f.write(output)
        return path
    except OSError:
        return ""


def _require_action():
    if not ACTIONS_ENABLED:
        raise HTTPException(status_code=403, detail="Actions desactivees")


def _require_valid_app(name: str):
    if not security.validate_app_name(name):
        raise HTTPException(status_code=400, detail="Nom d'application invalide")


def _require_valid_container(name: str):
    if not security.validate_container_name(name, docker_client.get_container_names()):
        raise HTTPException(status_code=404, detail="Container inconnu")


def _validate_subdomain(value: str) -> str | None:
    if not value or not re.fullmatch(r"[a-z0-9]([a-z0-9\-]*[a-z0-9])?", value):
        return "Sous-domaine invalide (lettres minuscules, chiffres, tirets)."
    return None


def _validate_port(value: str) -> str | None:
    if not value or not value.isdigit():
        return "Port invalide (nombre entier requis)."
    port = int(value)
    if port < 1 or port > 65535:
        return "Port hors plage (1-65535)."
    return None


def _client_actor(request: Request) -> str:
    """Identifie l'acteur : X-Forwarded-User/Email posé par OAuth2 Proxy, sinon 'admin'."""
    user = request.headers.get("x-forwarded-user") or request.headers.get("x-forwarded-email")
    if user:
        # Normalisation : strip + max 64 chars, alphanumeric + quelques spéciaux
        user = user.strip()[:64]
        # Rejeter caractères de contrôle / null bytes
        user = "".join(c for c in user if c.isprintable())
    return user or "admin"


def _client_ip(request: Request) -> str | None:
    return request.headers.get("x-forwarded-for") or request.headers.get("x-real-ip")


async def _audit(request: Request, action: str, target: str | None = None,
                  before: Any = None, after: Any = None, job_id: str | None = None) -> None:
    actor = _client_actor(request)
    ip = _client_ip(request)
    ua = request.headers.get("user-agent")
    try:
        await audit.log(actor=actor, action=action, target=target,
                        before=before, after=after, job_id=job_id, ip=ip, ua=ua)
    except Exception:
        logger.exception("Erreur audit %s/%s", action, target)


# ── Error pages ────────────────────────────────────

def _wants_json(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    if "application/json" in accept and "text/html" not in accept:
        return True
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return True
    return False


@app.exception_handler(404)
async def not_found_handler(request: Request, exc: HTTPException):
    if _wants_json(request):
        return JSONResponse({"detail": "Page introuvable"}, status_code=404)
    return templates.TemplateResponse("errors/404.html", {
        "request": request, "path": str(request.url.path),
    }, status_code=404)


@app.exception_handler(500)
async def server_error_handler(request: Request, exc: Exception):
    logger.exception("Erreur 500 sur %s %s", request.method, request.url.path)
    if _wants_json(request):
        return JSONResponse({"detail": "Erreur interne du serveur"}, status_code=500)
    return templates.TemplateResponse("errors/500.html", {
        "request": request, "status": 500,
        "message": str(exc) if ACTIONS_ENABLED or not isinstance(exc, HTTPException) else None,
    }, status_code=500)


# ── Dashboard summary (auto-refresh) ───────────────

def _dashboard_summary() -> dict:
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


@app.get("/api/dashboard/summary", response_class=HTMLResponse)
async def dashboard_summary():
    return templates.TemplateResponse("partials/dashboard_summary.html", {
        "request": Request,
        "actions_enabled": ACTIONS_ENABLED,
        **_dashboard_summary(),
    })


# ── Jobs : page list, detail, SSE stream ───────────────────────

@app.get("/jobs", response_class=HTMLResponse)
async def jobs_page(request: Request):
    items = await jobs.list_recent(limit=100)
    return templates.TemplateResponse("jobs.html", {
        "request": request, "jobs": items, "now": _now(),
    })


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_detail(request: Request, job_id: str):
    job = await jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job introuvable")
    return templates.TemplateResponse("job_detail.html", {
        "request": request, "job": job, "now": _now(),
    })


@app.post("/jobs/{job_id}/cancel")
async def job_cancel(job_id: str):
    _require_action()
    ok = await jobs.cancel(job_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Job non annulable")
    return {"success": True}


@app.get("/jobs/{job_id}/stream")
async def job_stream(job_id: str, request: Request):
    """SSE stream des events d'un job (lignes, status, end)."""
    job = await jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job introuvable")
    last_event_id = int(request.headers.get("last-event-id", "0") or "0")

    async def event_gen():
        yield events.sse_format("snapshot", {
            "id": job["id"], "kind": job["kind"], "status": job["status"],
            "output_size": job.get("output_size") or 0,
        }, event_id=str(last_event_id))
        seen = last_event_id
        async for payload in events.bus.subscribe(f"jobs:{job_id}"):
            if await request.is_disconnected():
                return
            if payload["event"] == "line":
                line_n = payload["data"].get("n", 0)
                if line_n <= seen:
                    continue
                seen = line_n
                yield events.sse_format("line", payload["data"], event_id=str(seen))
            elif payload["event"] == "finished":
                yield events.sse_format("finished", payload["data"], event_id=str(seen))
                return

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/jobs/{job_id}/log", response_class=PlainTextResponse)
async def job_log(job_id: str):
    job = await jobs.get(job_id)
    if not job or not job.get("output_path"):
        raise HTTPException(status_code=404, detail="Log introuvable")
    try:
        with open(job["output_path"], "r") as f:
            return PlainTextResponse(f.read())
    except OSError:
        raise HTTPException(status_code=500, detail="Impossible de lire le log")


@app.get("/api/jobs/list", response_class=HTMLResponse)
async def jobs_list_partial(request: Request):
    items = await jobs.list_recent(limit=100)
    return templates.TemplateResponse("partials/jobs_list.html", {
        "request": request, "jobs": items, "now": _now(),
    })


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
        _, crowdsec_status = await ksf_commands.run_command("crowdsec_status")
        _, crowdsec_alerts = await ksf_commands.run_command("crowdsec_alerts")
        _, crowdsec_bouncers = await ksf_commands.run_command("crowdsec_bouncers")

    if appsec_state == "active":
        _, appsec_status = await ksf_commands.run_command("appsec_status")

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


@app.get("/containers/{container_id}/logs/stream")
async def container_logs_stream(container_id: str, request: Request):
    _require_valid_container(container_id)

    async def event_gen():
        import threading
        loop = asyncio.get_event_loop()
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        stop = threading.Event()

        def _reader():
            try:
                for line in docker_client.stream_container_logs(container_id, tail=100, stop_event=stop):
                    loop.call_soon_threadsafe(q.put_nowait, line)
            except Exception:
                pass
            finally:
                loop.call_soon_threadsafe(q.put_nowait, None)

        reader = threading.Thread(target=_reader, daemon=True)
        reader.start()
        yield events.sse_format("start", {"container": container_id})
        try:
            while True:
                if await request.is_disconnected():
                    stop.set()
                    return
                line = await q.get()
                if line is None:
                    yield events.sse_format("end", {})
                    return
                yield events.sse_format("line", {"text": line})
        finally:
            stop.set()

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.post("/containers/{container_id}/restart")
async def container_restart(container_id: str, request: Request):
    _require_action()
    _require_valid_container(container_id)
    ok = docker_client.restart_container(container_id)
    await _audit(request, "container.restart", container_id)
    return _action_result(ok, f"Container {container_id} redemarre." if ok else f"Echec du redemarrage de {container_id}.")


@app.post("/containers/{container_id}/stop")
async def container_stop(container_id: str, request: Request):
    _require_action()
    _require_valid_container(container_id)
    ok = docker_client.stop_container(container_id)
    await _audit(request, "container.stop", container_id)
    return _action_result(ok, f"Container {container_id} arrete." if ok else f"Echec de l'arret de {container_id}.")


@app.post("/containers/{container_id}/start")
async def container_start(container_id: str, request: Request):
    _require_action()
    _require_valid_container(container_id)
    ok = docker_client.start_container(container_id)
    await _audit(request, "container.start", container_id)
    return _action_result(ok, f"Container {container_id} demarre." if ok else f"Echec du demarrage de {container_id}.")


# ── Action log viewer ──────────────────────────────

@app.get("/actions/logs/{log_name}", response_class=PlainTextResponse)
async def action_log(log_name: str):
    if not re.fullmatch(r"[a-zA-Z0-9_.\-]+", log_name):
        raise HTTPException(status_code=400, detail="Nom de log invalide")
    path = os.path.join(LOG_DIR, log_name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Log introuvable")
    try:
        with open(path, "r") as f:
            return PlainTextResponse(f.read())
    except OSError:
        raise HTTPException(status_code=500, detail="Impossible de lire le log")


# ── App actions ────────────────────────────────────

@app.get("/apps/install-form/{app_name}", response_class=HTMLResponse)
async def app_install_form(app_name: str):
    _require_valid_app(app_name)
    available = ksf_commands.list_available_apps()
    template = next((a for a in available if a["name"] == app_name), None)
    if not template or template["installed"]:
        raise HTTPException(status_code=400, detail="Application non disponible")

    return templates.TemplateResponse("partials/install_form.html", {
        "request": Request,
        "app_name": template["name"],
        "subdomain": template["name"],
        "port": str(template.get("port", "")),
        "protected": template.get("protected", True),
    })


@app.post("/apps/{app_name}/install")
async def app_install(
    app_name: str,
    request: Request,
    subdomain: str = Form(...),
    port: str = Form(...),
    protected: str = Form("false"),
):
    _require_action()
    _require_valid_app(app_name)
    available = ksf_commands.list_available_apps()
    template = next((a for a in available if a["name"] == app_name), None)
    if not template or template["installed"]:
        raise HTTPException(status_code=400, detail="Application non disponible")

    err = _validate_subdomain(subdomain) or _validate_port(port)
    if err:
        raise HTTPException(status_code=400, detail=err)

    extra_args = ["--subdomain", subdomain, "--port", port]
    if protected.lower() in ("true", "on", "1"):
        extra_args.append("--auth")
    else:
        extra_args.append("--no-auth")

    ok, output = await ksf_commands.run_app_command(app_name, "install", extra_args=extra_args)
    log_path = _save_full_output(f"install-{app_name}", output) if ok or output else ""
    await _audit(request, "app.install", app_name,
                  after={"subdomain": subdomain, "port": port, "protected": protected})
    return _action_result(
        ok,
        f"Installation de {app_name} lancee." if ok else f"Echec de l'installation de {app_name}.",
        output,
        log_path=log_path or None,
    )


@app.post("/apps/{app_name}/update")
async def app_update(app_name: str):
    _require_action()
    _require_valid_app(app_name)
    ok, output = await ksf_commands.run_app_command(app_name, "update")
    log_path = _save_full_output(f"update-{app_name}", output)
    return _action_result(ok, f"Mise a jour de {app_name} lancee." if ok else f"Echec de la mise a jour de {app_name}.", output, log_path=log_path or None)


@app.post("/apps/{app_name}/restart")
async def app_restart(app_name: str):
    _require_action()
    _require_valid_app(app_name)
    ok, output = await ksf_commands.run_app_command(app_name, "restart")
    log_path = _save_full_output(f"restart-{app_name}", output)
    return _action_result(ok, f"Redemarrage de {app_name} lance." if ok else f"Echec du redemarrage de {app_name}.", output, log_path=log_path or None)


@app.post("/apps/{app_name}/start")
async def app_start(app_name: str):
    _require_action()
    _require_valid_app(app_name)
    ok, output = await ksf_commands.run_app_command(app_name, "start")
    log_path = _save_full_output(f"start-{app_name}", output)
    return _action_result(ok, f"Demarrage de {app_name} lance." if ok else f"Echec du demarrage de {app_name}.", output, log_path=log_path or None)


@app.post("/apps/{app_name}/stop")
async def app_stop(app_name: str):
    _require_action()
    _require_valid_app(app_name)
    ok, output = await ksf_commands.run_app_command(app_name, "stop")
    log_path = _save_full_output(f"stop-{app_name}", output)
    return _action_result(ok, f"Arret de {app_name} lance." if ok else f"Echec de l'arret de {app_name}.", output, log_path=log_path or None)


@app.post("/apps/{app_name}/disable")
async def app_disable(app_name: str):
    _require_action()
    _require_valid_app(app_name)
    ok, output = await ksf_commands.run_app_command(app_name, "disable")
    log_path = _save_full_output(f"disable-{app_name}", output)
    return _action_result(ok, f"Desactivation de {app_name} lancee." if ok else f"Echec de la desactivation de {app_name}.", output, log_path=log_path or None)


@app.post("/apps/{app_name}/remove")
async def app_remove(app_name: str, request: Request):
    _require_action()
    _require_valid_app(app_name)
    ok, output = await ksf_commands.run_app_command(app_name, "remove")
    log_path = _save_full_output(f"remove-{app_name}", output)
    await _audit(request, "app.remove", app_name)
    return _action_result(ok, f"Suppression de {app_name} lancee." if ok else f"Echec de la suppression de {app_name}.", output, log_path=log_path or None)


# ── Backup actions ─────────────────────────────────

@app.post("/backups/create")
async def backup_create():
    _require_action()
    job = await jobs.enqueue(
        "backup.create",
        [config.REPO_DIR + "/ksf.sh", "backup", "create", "--yes"],
        lock_key="backup",
        triggered_by="admin",
    )
    return {"success": True, "message": "Backup lance en arriere-plan.", "job_id": job["id"]}


@app.post("/backups/verify")
async def backup_verify():
    _require_action()
    job = await jobs.enqueue(
        "backup.verify",
        [config.REPO_DIR + "/ksf.sh", "backup", "verify", "latest"],
        triggered_by="admin",
    )
    return {"success": True, "message": "Verification lancee en arriere-plan.", "job_id": job["id"]}


@app.post("/backups/restore-dryrun")
async def backup_restore_dryrun():
    _require_action()
    job = await jobs.enqueue(
        "backup.verify",
        [config.REPO_DIR + "/ksf.sh", "backup", "restore", "latest", "--dry-run"],
        triggered_by="admin",
    )
    return {"success": True, "message": "Simulation lancee en arriere-plan.", "job_id": job["id"]}


@app.get("/backups/{backup_name}/download")
async def backup_download(backup_name: str):
    from fastapi.responses import FileResponse
    path = backups_svc._safe_path(backup_name)
    if path is None or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Backup introuvable")
    return FileResponse(
        path, filename=backup_name,
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="{backup_name}"'},
    )


@app.post("/backups/{backup_name}/delete")
async def backup_delete(backup_name: str, request: Request):
    _require_action()
    ok, msg = backups_svc.delete_backup(backup_name)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    await _audit(request, "backup.delete", backup_name)
    return {"success": True, "message": msg}


@app.post("/backups/{backup_name}/restore")
async def backup_restore(backup_name: str, request: Request):
    _require_action()
    if backups_svc._safe_path(backup_name) is None:
        raise HTTPException(status_code=400, detail="Nom de backup invalide")
    job = await jobs.enqueue(
        "backup.restore",
        [config.REPO_DIR + "/ksf.sh", "backup", "restore", backup_name, "--yes"],
        lock_key="backup-restore",
        triggered_by=_client_actor(request),
    )
    await _audit(request, "backup.restore", backup_name, job_id=job["id"])
    return {"success": True, "message": "Restauration lancee en arriere-plan.", "job_id": job["id"]}


@app.post("/backups/{backup_name}/verify")
async def backup_verify_one(backup_name: str, request: Request):
    _require_action()
    if backups_svc._safe_path(backup_name) is None:
        raise HTTPException(status_code=400, detail="Nom de backup invalide")
    job = await jobs.enqueue(
        "backup.verify",
        [config.REPO_DIR + "/ksf.sh", "backup", "verify", backup_name],
        triggered_by=_client_actor(request),
    )
    await _audit(request, "backup.verify", backup_name, job_id=job["id"])
    return {"success": True, "message": "Verification lancee.", "job_id": job["id"]}


@app.post("/backups/prune")
async def backup_prune(request: Request, keep: int = 5):
    _require_action()
    if not (1 <= keep <= 100):
        raise HTTPException(status_code=400, detail="Valeur --keep doit être entre 1 et 100")
    job = await jobs.enqueue(
        "backup.prune",
        [config.REPO_DIR + "/ksf.sh", "backup", "prune", "--keep", str(keep), "--yes"],
        triggered_by=_client_actor(request),
    )
    await _audit(request, "backup.prune", after={"keep": keep}, job_id=job["id"])
    return {"success": True, "message": f"Purge en cours (garder {keep}).", "job_id": job["id"]}


# ── Config editor (ksf.env) ────────────────────────────────────

# ── Audit log ──────────────────────────────────────────────────

@app.get("/audit", response_class=HTMLResponse)
async def audit_page(request: Request, action: str | None = None, target: str | None = None):
    entries = await audit.list_entries(limit=200, action=action, target=target)
    return templates.TemplateResponse("audit.html", {
        "request": request, "entries": entries,
        "action": action, "target": target, "now": _now(),
    })


@app.get("/api/audit/export")
async def audit_export(fmt: str = "json", action: str | None = None, target: str | None = None):
    entries = await audit.list_entries(limit=10000, action=action, target=target)
    if fmt == "csv":
        return PlainTextResponse(audit.export_csv(entries), media_type="text/csv",
                                  headers={"Content-Disposition": 'attachment; filename="audit.csv"'})
    return PlainTextResponse(audit.export_json(entries), media_type="application/json",
                              headers={"Content-Disposition": 'attachment; filename="audit.json"'})


# ── Notifications ─────────────────────────────────────────────

@app.get("/notifications", response_class=HTMLResponse)
async def notifications_page(request: Request):
    items = await notifications.list_all(limit=100)
    unread = await notifications.count_unread()
    return templates.TemplateResponse("notifications.html", {
        "request": request, "notifications": items, "unread": unread, "now": _now(),
    })


@app.post("/notifications/{notif_id}/read")
async def notification_read(notif_id: str):
    await notifications.mark_read(notif_id)
    return {"success": True}


@app.post("/notifications/read-all")
async def notification_read_all():
    n = await notifications.mark_all_read()
    return {"success": True, "marked": n}


@app.delete("/notifications/{notif_id}")
async def notification_delete(notif_id: str):
    ok = await notifications.delete(notif_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Notification introuvable")
    return {"success": True}


@app.get("/api/notifications/unread-count")
async def notification_unread_count():
    return {"unread": await notifications.count_unread()}


@app.get("/api/notifications/list", response_class=HTMLResponse)
async def notifications_list_partial(request: Request):
    items = await notifications.list_all(limit=100)
    unread = await notifications.count_unread()
    return templates.TemplateResponse("partials/notifications_list.html", {
        "request": request, "notifications": items, "unread": unread,
    })


# ── Webhooks ───────────────────────────────────────────────────

@app.get("/settings/webhooks", response_class=HTMLResponse)
async def webhooks_page(request: Request):
    items = await webhooks.list_all()
    return templates.TemplateResponse("webhooks.html", {
        "request": request, "webhooks": items, "now": _now(),
    })


@app.post("/api/webhooks")
async def webhook_create(request: Request):
    body = await request.json()
    name = (body.get("name") or "").strip()
    url = (body.get("url") or "").strip()
    events_list = body.get("events") or ["*"]
    secret = (body.get("secret") or "").strip() or None
    if not name or not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="name et url (http/https) requis")
    ok, err = webhooks._is_safe_webhook_target(url, allow_private=False)
    if not ok:
        raise HTTPException(status_code=400, detail=f"URL refusée : {err}")
    try:
        eid = await webhooks.create(name, url, events_list, secret)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    await _audit(request, "webhook.create", eid, after={"name": name})
    return {"success": True, "id": eid}


@app.post("/api/webhooks/{endpoint_id}")
async def webhook_update(endpoint_id: str, request: Request):
    body = await request.json()
    if "url" in body:
        ok, err = webhooks._is_safe_webhook_target(str(body["url"]), allow_private=False)
        if not ok:
            raise HTTPException(status_code=400, detail=f"URL refusée : {err}")
    await webhooks.update(endpoint_id, **body)
    await _audit(request, "webhook.update", endpoint_id, after=body)
    return {"success": True}


@app.delete("/api/webhooks/{endpoint_id}")
async def webhook_delete(endpoint_id: str, request: Request):
    ok = await webhooks.delete(endpoint_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Webhook introuvable")
    await _audit(request, "webhook.delete", endpoint_id)
    return {"success": True}


@app.post("/api/webhooks/{endpoint_id}/test")
async def webhook_test(endpoint_id: str, request: Request):
    ep = await webhooks.get(endpoint_id)
    if not ep:
        raise HTTPException(status_code=404, detail="Webhook introuvable")
    payload = {
        "test": True,
        "title": "Test webhook ksf-web",
        "body": f"Ceci est un test envoyé à {ep['name']}.",
        "level": "info",
        "category": "test",
    }
    await webhooks._send_with_retry(ep, payload)
    return {"success": True}

@app.get("/config", response_class=HTMLResponse)
async def config_page(request: Request):
    fields = config_editor.form_from_current()
    sections = {}
    for f in fields:
        sections.setdefault(f.get("section", "other"), []).append(f)
    versions = await config_editor.list_versions(limit=10)
    return templates.TemplateResponse("config.html", {
        "request": request, "fields": fields, "sections": sections,
        "versions": versions, "now": _now(),
    })


@app.post("/api/config/preview")
async def config_preview(request: Request):
    form = await request.form()
    values = {k: v for k, v in form.items() if not k.startswith("_")}
    result = await config_editor.preview(values)
    return JSONResponse(result)


@app.post("/api/config/commit")
async def config_commit(request: Request):
    body = await request.json()
    proposed = body.get("proposed", "")
    token = body.get("token", "")
    if not proposed:
        raise HTTPException(status_code=400, detail="Contenu vide")
    if not token:
        raise HTTPException(status_code=400, detail="Token de binding manquant (relancez la prévisualisation)")
    result = await config_editor.commit(proposed, token)
    return JSONResponse(result)


# ── System actions ─────────────────────────────────

@app.post("/security/refresh")
async def security_refresh():
    _require_action()
    results = {}
    try:
        ksf_env = ksf_commands.get_ksf_env()
        if ksf_env.get("WITH_CROWDSEC", "false").lower() == "true":
            ok1, out1 = await ksf_commands.run_command("crowdsec_alerts")
            log1 = _save_full_output("crowdsec-alerts", out1)
            results["alerts"] = _action_result(ok1, "Alertes rafraichies.", out1, log_path=log1 or None)
            ok2, out2 = await ksf_commands.run_command("crowdsec_bouncers")
            log2 = _save_full_output("crowdsec-bouncers", out2)
            results["bouncers"] = _action_result(ok2, "Bouncers rafraichis.", out2, log_path=log2 or None)
    except Exception:
        pass
    return results


@app.post("/system/doctor")
async def system_doctor():
    _require_action()
    job = await jobs.enqueue(
        "system.doctor",
        [config.REPO_DIR + "/ksf.sh", "doctor"],
        triggered_by="admin",
    )
    return {"success": True, "message": "Diagnostic lance en arriere-plan.", "job_id": job["id"]}


@app.post("/system/update-all")
async def system_update_all():
    _require_action()
    job = await jobs.enqueue(
        "system.update",
        [config.REPO_DIR + "/ksf.sh", "update", "all", "--yes"],
        lock_key="system-update",
        triggered_by="admin",
    )
    return {"success": True, "message": "Mise a jour lancee en arriere-plan.", "job_id": job["id"]}
