"""Point d'entrée FastAPI de ksf-web.

Structure :
- `app/main.py` (ce fichier) : app, lifespan, middleware, exception handlers, routers.
- `app/helpers.py` : utilitaires (validation, format, audit).
- `app/routes/pages.py` : GET HTML.
- `app/routes/actions.py` : POST/DELETE mutations.
- `app/routes/api.py` : JSON / partials / fichiers.
- `app/routes/sse.py` : EventSource streaming.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from itsdangerous import URLSafeTimedSerializer, BadSignature
import secrets

from app import config, db
from app.helpers import wants_json
from app.middleware.rate_limit import RateLimitMiddleware
from app.routes import pages as pages_routes
from app.routes import actions as actions_routes
from app.routes import api as api_routes
from app.routes import sse as sse_routes
from app.services import jobs

logger = logging.getLogger("ksf-web")


@asynccontextmanager
async def lifespan(app):
    await db.init()
    # Backfill des secrets/payloads en clair vers *_encrypted (Phase 2).
    # Idempotent, no-op si déjà chiffré.
    from app.services import audit, webhooks
    try:
        await webhooks.backfill_legacy_secrets()
        await audit.backfill_legacy_payloads()
    except Exception:
        logger.exception("Backfill chiffrement a échoué (non-bloquant)")
    # Rétention jobs 30 jours (Phase 4.10) : supprime anciennes entrées + .log.
    try:
        await _prune_old_jobs()
    except Exception:
        logger.exception("Prune jobs a échoué (non-bloquant)")
    # Prune notifications dédupliquées > 1 jour (review post-implementation).
    # Sans cela, l'index unique partiel `idx_notif_dedup` accumule des
    # entrées qui ne sont jamais évincées et bloquent les nouveaux INSERT
    # avec le même dedup_key pour toujours.
    try:
        await _prune_old_deduped_notifications()
    except Exception:
        logger.exception("Prune notifications a échoué (non-bloquant)")
    await jobs.start_worker()
    logger.info("ksf-web démarré (DB=%s, jobs worker actif)", config.DB_PATH)
    try:
        yield
    finally:
        await jobs.stop_worker()
        await db.close()


async def _prune_old_jobs(retention_days: int = 30) -> int:
    """Supprime les jobs de plus de `retention_days` jours + leurs .log."""
    import os
    import glob
    async for conn in db.get_conn():
        cur = await conn.execute(
            "SELECT id, output_path FROM jobs WHERE created_at < datetime('now', ?)",
            (f"-{retention_days} days",),
        )
        rows = await cur.fetchall()
        await cur.close()
        if not rows:
            return 0
        ids = [r["id"] for r in rows]
        # Supprime les .log
        for r in rows:
            if r["output_path"]:
                try:
                    if os.path.isfile(r["output_path"]):
                        os.remove(r["output_path"])
                except OSError:
                    pass
        # Aussi rm les .log orphelins dans JOB_LOG_DIR (pas trackés en DB)
        for path in glob.glob(os.path.join(config.JOB_LOG_DIR, "*.log")):
            try:
                if os.path.getmtime(path) < (os.path.getmtime(__file__) - retention_days * 86400):
                    pass  # best-effort, on n'efface que ceux trackés pour l'instant
            except OSError:
                pass
        # DELETE en DB
        placeholders = ",".join("?" * len(ids))
        await conn.execute(f"DELETE FROM jobs WHERE id IN ({placeholders})", ids)
        await conn.commit()
        logger.info("Rétention: %d job(s) > %d jours supprimés", len(ids), retention_days)
        return len(ids)


async def _prune_old_deduped_notifications(retention_days: int = 1) -> int:
    """Supprime les notifications dédupliquées > `retention_days` jours.

    Sans cela, l'index unique partiel `idx_notif_dedup` (qui couvre
    `created_at > '-1 day'` côté INSERT) accumule des entrées qui ne sont
    jamais évincées et bloquent définitivement les nouveaux INSERT avec
    le même dedup_key (le `WHERE` n'est pas ré-évalué sur les entrées
    existantes).
    """
    async for conn in db.get_conn():
        cur = await conn.execute(
            "DELETE FROM notifications "
            "WHERE dedup_key IS NOT NULL AND created_at < datetime('now', ?)",
            (f"-{retention_days} days",),
        )
        n = cur.rowcount
        await conn.commit()
        await cur.close()
        if n:
            logger.info("Prune notifications: %d notif(s) dédupliquée(s) > %d jour(s) supprimée(s)",
                        n, retention_days)
        return n


app = FastAPI(title="KSF Web", docs_url=None, redoc_url=None, lifespan=lifespan)

app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")

_templates = Jinja2Templates(directory=config.TEMPLATE_DIR)
pages_routes.set_templates(_templates)

ACTIONS_ENABLED = config.ACTIONS_ENABLED

_csrf_signer = URLSafeTimedSerializer(config.CSRF_SECRET, salt=config.CSRF_SALT)


# ── CSRF middleware (double-submit cookie) ─────────────────

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


# Rate limit AVANT CSRF pour rejeter tôt (économise le coût de CSRF).
app.add_middleware(RateLimitMiddleware)
app.add_middleware(CSRFMiddleware)


# ── Cache-Control middleware (mitige Cloudflare bypass) ───

class NoCacheHTMLMiddleware(BaseHTTPMiddleware):
    """Force `Cache-Control: no-cache` sur les pages HTML.

    Pendant le dev, on veut que les modifs CSS/HTML soient visibles
    immédiatement. Les JSON et les events SSE sont exemptés.
    """

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        ct = response.headers.get("content-type", "")
        path = request.url.path
        if (ct.startswith("text/html")
                and not path.startswith("/static")
                and path != "/health"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
        return response


app.add_middleware(NoCacheHTMLMiddleware)


# ── Error pages ────────────────────────────────────────────

@app.exception_handler(404)
async def not_found_handler(request: Request, exc: HTTPException):
    if wants_json(request):
        return JSONResponse({"detail": "Page introuvable"}, status_code=404)
    return _templates.TemplateResponse("errors/404.html", {
        "request": request, "path": str(request.url.path),
    }, status_code=404)


@app.exception_handler(500)
async def server_error_handler(request: Request, exc: Exception):
    logger.exception("Erreur 500 sur %s %s", request.method, request.url.path)
    if wants_json(request):
        return JSONResponse({"detail": "Erreur interne du serveur"}, status_code=500)
    return _templates.TemplateResponse("errors/500.html", {
        "request": request, "status": 500,
        "message": str(exc) if ACTIONS_ENABLED or not isinstance(exc, HTTPException) else None,
    }, status_code=500)


# ── Routers ────────────────────────────────────────────────

app.include_router(pages_routes.router)
app.include_router(actions_routes.router)
app.include_router(api_routes.router)
app.include_router(sse_routes.router)
