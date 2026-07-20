import re
from urllib.parse import urlparse

from fastapi import Request
from fastapi.responses import JSONResponse

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
HEALTH_PATHS = {"/api/status"}
SENSITIVE_KEY_PATTERN = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:SECRET|PASSWORD|TOKEN|API_KEY|COOKIE|PRIVATE_KEY|BOUNCER_KEY)[A-Z0-9_]*)"
    r"(\s*[=:]\s*)([^\s,;]+)"
)


def redact_secrets(value: str) -> str:
    """Remove configured and conventionally named credentials from persisted output."""
    from .config import get_config

    for key, secret in get_config().env.items():
        if secret and any(token in key.upper() for token in (
            "SECRET", "PASSWORD", "TOKEN", "API_KEY", "COOKIE", "PRIVATE_KEY", "BOUNCER_KEY",
        )):
            value = value.replace(secret, "******")
    value = re.sub(r"(?i)(authorization:\s*bearer\s+)[^\s]+", r"\1******", value)
    return SENSITIVE_KEY_PATTERN.sub(r"\1\2******", value)


def _same_origin(value: str, host: str) -> bool:
    parsed = urlparse(value)
    return (
        parsed.scheme in {"http", "https"}
        and parsed.netloc.casefold() == host.casefold()
        and parsed.username is None
        and parsed.password is None
    )


async def enforce_webui_csrf(request: Request, call_next):
    if request.url.path in HEALTH_PATHS or request.url.path.startswith("/static/") or request.url.path == "/favicon.svg":
        return await call_next(request)

    if request.method not in SAFE_METHODS:
        host = request.headers.get("host", "")
        origin = request.headers.get("origin", "")
        referer = request.headers.get("referer", "")

        # A browser mutation must prove it originated from the exact Host served
        # by Traefik. Substring matching would accept attacker.example.com.
        if not host or "," in host or " " in host:
            return _csrf_error(request, "Hôte de la requête invalide.")
        if origin:
            if not _same_origin(origin, host):
                return _csrf_error(request, "Origine de la requête invalide.")
        elif referer:
            if not _same_origin(referer, host):
                return _csrf_error(request, "Référent de la requête invalide.")
        else:
            return _csrf_error(request, "Une origine ou un référent valide est requis.")

    return await call_next(request)


def _csrf_error(request: Request, message: str):
    is_htmx = request.headers.get("HX-Request") == "true"
    if is_htmx:
        from fastapi.responses import HTMLResponse

        return HTMLResponse(
            f'<div class="error-box" role="alert" tabindex="-1">{message}</div>',
            status_code=400,
            headers={"HX-Retarget": "#fragment-content"},
        )
    return JSONResponse({"error": message}, status_code=400)
