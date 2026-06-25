"""Middleware de log des requêtes avec correlation_id.

Génère un correlation_id unique par requête HTTP, le pose dans le contexte
contextvars (visible par tous les loggers via ContextFilter), et le renvoie
dans le header `X-Request-Id` de la réponse.

Exempté : /static, /health (bruit inutile).
"""
import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.logging_config import (
    reset_actor,
    reset_correlation_id,
    set_actor,
    set_correlation_id,
)

logger = logging.getLogger("ksf-web.request")

EXEMPT_PREFIXES = ("/static", "/health")
HEADER_REQUEST_ID = "X-Request-Id"


class RequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if any(path.startswith(p) for p in EXEMPT_PREFIXES):
            return await call_next(request)

        # Génère un correlation_id court (12 chars) ou réutilise celui du
        # client (utile pour le debug cross-service).
        cid = request.headers.get(HEADER_REQUEST_ID) or uuid.uuid4().hex[:12]
        cid_token = set_correlation_id(cid)

        # Capture l'acteur (posé par les routes via client_actor()).
        actor = (
            request.headers.get("x-forwarded-user")
            or request.headers.get("x-forwarded-email")
            or "anonymous"
        )
        actor_token = set_actor(actor.strip()[:64] or "anonymous")

        ip = request.headers.get("x-forwarded-for") or request.headers.get("x-real-ip")
        started = time.monotonic()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers[HEADER_REQUEST_ID] = cid
            return response
        finally:
            duration_ms = int((time.monotonic() - started) * 1000)
            try:
                logger.info(
                    "request",
                    extra={
                        "method": request.method,
                        "path": path,
                        "status": status,
                        "duration_ms": duration_ms,
                        "ip": ip,
                        "ua": request.headers.get("user-agent"),
                    },
                )
            except Exception:
                pass
            try:
                reset_actor(actor_token)
            except Exception:
                pass
            try:
                reset_correlation_id(cid_token)
            except Exception:
                pass
