import os
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

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

app = FastAPI(title="KSF Web UI")

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
    cfg = get_config()
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
        return HTMLResponse("<h1>404 - Page introuvable</h1>", status_code=404)
    return templates.TemplateResponse(request, template_name, {
        "config": cfg,
        "installed": cfg.loaded,
    })


@app.on_event("startup")
async def startup():
    pass
