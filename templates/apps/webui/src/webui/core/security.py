import hmac
import os
import secrets

from fastapi import Request
from fastapi.responses import JSONResponse, PlainTextResponse

from .config import get_config


SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
HEALTH_PATHS = {"/api/status"}


def _allowed_users() -> set[str]:
    cfg = get_config()
    configured = cfg.get("WEBUI_ADMIN_USERS", cfg.get("OAUTH2_GITHUB_USER", ""))
    return {user.strip().lower() for user in configured.split(",") if user.strip()}


def _authenticated_user(request: Request) -> str:
    token = os.environ.get("WEBUI_ADMIN_TOKEN", "")
    authorization = request.headers.get("authorization", "")
    if token and authorization.startswith("Bearer "):
        if hmac.compare_digest(authorization.removeprefix("Bearer "), token):
            return "token-admin"

    # OAuth2 Proxy forwards this header after a successful forward-auth check.
    user = (request.headers.get("x-auth-request-user", "")
            or request.headers.get("x-auth-request-preferred-username", ""))
    allowed = _allowed_users()
    if user and allowed and user.lower() in allowed:
        return user
    return ""


async def enforce_webui_security(request: Request, call_next):
    if request.url.path in HEALTH_PATHS or request.url.path.startswith("/static/"):
        return await call_next(request)

    user = _authenticated_user(request)
    if not user:
        if request.url.path.startswith("/api/"):
            return JSONResponse({"error": "Authentification administrateur requise."}, status_code=401)
        return PlainTextResponse("Authentification administrateur requise.", status_code=401)

    request.state.user = user
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
