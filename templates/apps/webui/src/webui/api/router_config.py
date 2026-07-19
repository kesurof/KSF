from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from ..core.config import get_config
from ..templates import templates

router = APIRouter()


@router.get("")
async def get_config_endpoint():
    cfg = get_config()
    return {"config": cfg.to_public_dict()}


@router.get("/html", response_class=HTMLResponse)
async def config_html(request: Request):
    cfg = get_config()
    return templates.TemplateResponse(request, "_config_table.html", {
        "config": cfg.to_public_dict(),
    })
