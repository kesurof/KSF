from urllib.parse import urlparse

from fastapi import Request
from fastapi.responses import JSONResponse

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
HEALTH_PATHS = {"/api/status"}


async def enforce_webui_csrf(request: Request, call_next):
    if request.url.path in HEALTH_PATHS or request.url.path.startswith("/static/"):
        return await call_next(request)

    if request.method not in SAFE_METHODS:
        host = request.headers.get("host", "")
        origin = request.headers.get("origin", "")
        referer = request.headers.get("referer", "")

        if origin and host not in urlparse(origin).netloc:
            return JSONResponse({"error": "Origine de la requête invalide."}, status_code=400)
        if not origin and referer and host not in urlparse(referer).netloc:
            return JSONResponse({"error": "Référent de la requête invalide."}, status_code=400)

    return await call_next(request)
