import os
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from .core.config import get_config
from .templates import templates
from .api.router_status import router as status_router
from .api.router_apps import router as apps_router
from .api.router_infra import router as infra_router
from .api.router_crowdsec import router as crowdsec_router
from .api.router_logs import router as logs_router
from .api.router_routes import router as routes_router
from .api.router_config import router as config_router
from .api.router_templates import router as templates_router
from .api.router_jobs import router as jobs_router
from .api.router_maintenance import router as maintenance_router
from .api.router_operations import router as operations_router
from .core.security import enforce_webui_csrf

app = FastAPI(title="KSF Web UI")
app.add_middleware(BaseHTTPMiddleware, dispatch=enforce_webui_csrf)

static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

app.include_router(status_router, prefix="/api", tags=["status"])
app.include_router(apps_router, prefix="/api/apps", tags=["apps"])
app.include_router(infra_router, prefix="/api/services", tags=["infrastructure"])
app.include_router(crowdsec_router, prefix="/api/crowdsec", tags=["crowdsec"])
app.include_router(logs_router, prefix="/api/logs", tags=["logs"])
app.include_router(routes_router, prefix="/api/routes", tags=["routes"])
app.include_router(config_router, prefix="/api/config", tags=["config"])
app.include_router(templates_router, prefix="/api/templates", tags=["templates"])
app.include_router(jobs_router, prefix="/api/jobs", tags=["jobs"])
app.include_router(maintenance_router, prefix="/api", tags=["maintenance"])
app.include_router(operations_router, prefix="/api/operations", tags=["operations"])


def _render_with_context(request: Request, template_name: str) -> HTMLResponse:
    """Rend une page avec le contexte commun (config, installed)."""
    cfg = get_config()
    return templates.TemplateResponse(request, template_name, {
        "config": cfg,
        "installed": cfg.loaded,
    })


@app.get("/favicon.svg", response_class=PlainTextResponse)
async def favicon():
    p = static_dir / "favicon.svg"
    return PlainTextResponse(p.read_text(encoding="utf-8"), media_type="image/svg+xml")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    cfg = get_config()
    return templates.TemplateResponse(request, "pages/dashboard.html", {
        "installed": cfg.loaded,
        "domain": cfg.domain or "non configuré",
        "config": cfg,
    })


@app.get("/apps/install", response_class=HTMLResponse)
async def app_install_page(request: Request):
    cfg = get_config()
    return templates.TemplateResponse(request, "pages/apps/install.html", {
        "config": cfg,
        "installed": cfg.loaded,
    })


@app.get("/apps/{instance}", response_class=HTMLResponse)
async def app_detail_page(request: Request, instance: str):
    cfg = get_config()
    return templates.TemplateResponse(request, "pages/apps/detail.html", {
        "config": cfg,
        "installed": cfg.loaded,
        "instance": instance,
    })


@app.get("/{path:path}", response_class=HTMLResponse)
async def catch_all(request: Request, path: str):
    page_map = {
        "overview": "pages/overview.html",
        "apps": "pages/apps/index.html",
        "apps/install": "pages/apps/install.html",
        "infrastructure": "pages/infrastructure/index.html",
        "security": "pages/security/index.html",
        "security/alerts": "pages/security/alerts.html",
        "security/metrics": "pages/security/metrics.html",
        "security/bouncers": "pages/security/bouncers.html",
        "security/decisions": "pages/security/decisions.html",
        "security/appsec": "pages/security/appsec.html",
        "logs": "pages/logs/index.html",
        "maintenance": "pages/maintenance/index.html",
        "operations": "pages/operations/index.html",
        "jobs": "pages/jobs/index.html",
        "config": "pages/config/index.html",
        "routes": "pages/routes.html",
        "doctor": "pages/doctor.html",
    }
    template_name = page_map.get(path)
    if not template_name:
        return _render_error(request, 404, None)
    return _render_with_context(request, template_name)


@app.exception_handler(StarletteHTTPException)
async def ksf_http_exception_handler(request: Request, exc: StarletteHTTPException):
    # Pages d'erreur statiques rendues dans le layout de base.
    if exc.status_code == 404:
        return _render_error(request, 404, None)
    # 403, 405 etc. → on rend aussi une 404, message informatif
    return _render_error(request, exc.status_code, str(exc.detail) if exc.detail else None)


@app.exception_handler(Exception)
async def ksf_unhandled_exception_handler(request: Request, exc: Exception):
    import traceback
    traceback.print_exc()  # journalisé côté serveur stdout (Docker logs)
    return _render_error(request, 500, None)


def _render_error(request: Request, status: int, detail) -> HTMLResponse:
    cfg = get_config()
    template = {404: "pages/error/404.html"}.get(status, "pages/error/500.html")
    return templates.TemplateResponse(request, template, {
        "config": cfg,
        "installed": cfg.loaded,
        "detail": detail,
    }, status_code=status)


@app.on_event("startup")
async def startup():
    pass