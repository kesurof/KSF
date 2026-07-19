import hmac
import secrets

from fastapi import Request
from fastapi.responses import JSONResponse


SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
HEALTH_PATHS = {"/api/status"}


async def enforce_webui_security(request: Request, call_next):
    if request.url.path in HEALTH_PATHS or request.url.path.startswith("/static/"):
        return await call_next(request)

    # The WebUI has no published host port. Traefik's oauth2-chain is the
    # authentication boundary and forwards requests only after OAuth2 Proxy.
    csrf_token = request.session.get("csrf_token")
    if not csrf_token:
        csrf_token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = csrf_token
    request.state.csrf_token = csrf_token

    if request.method not in SAFE_METHODS:
        supplied = request.headers.get("x-csrf-token", "")
        if not supplied or not hmac.compare_digest(supplied, csrf_token):
            return JSONResponse({"error": "Jeton CSRF invalide ou absent."}, status_code=403)

    return await call_next(request)
