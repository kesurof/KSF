from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from ..core.state import list_route_files
from ..templates import templates

router = APIRouter()


@router.get("")
async def get_routes():
    routes = list_route_files()
    return {"routes": routes}


@router.get("/html", response_class=HTMLResponse)
async def routes_html(request: Request):
    routes = list_route_files()
    return templates.TemplateResponse(request, "_routes_table.html", {
        "routes": routes,
    })
