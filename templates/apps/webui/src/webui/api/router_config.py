from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from ..core.config import get_config
from ..templates import templates

router = APIRouter()

CATEGORIES = [
    ("Plateforme", "general", ["DOMAIN", "DOMAINS", "SERVER_", "TIMEZONE", "TZ", "NETWORK_NAME", "BASE_DIR", "KSF_", "WITH_"]),
    ("Traefik & ACME", "infra", ["TRAEFIK_", "ACME_"]),
    ("OAuth2 Proxy", "infra", ["OAUTH2_"]),
    ("CrowdSec", "security", ["CROWDSEC_"]),
    ("DNS Cloudflare", "maintenance", ["DNS_", "CF_"]),
    ("Applications", "apps", ["APP_", "DEFAULT_"]),
]


def _categorize(raw: dict) -> list[dict]:
    assigned = set()
    sections = []
    for label, accent, prefixes in CATEGORIES:
        items = []
        for key in sorted(raw):
            if key in assigned:
                continue
            if any(key.startswith(p) or key == p for p in prefixes):
                items.append((key, raw[key]))
                assigned.add(key)
        if items:
            sections.append({"label": label, "accent": accent, "items": items})
    remaining = [(k, raw[k]) for k in sorted(raw) if k not in assigned]
    if remaining:
        sections.append({"label": "Autres", "accent": "general", "items": remaining})
    return sections


@router.get("")
async def get_config_endpoint():
    cfg = get_config()
    return {"config": cfg.to_public_dict()}


@router.get("/html", response_class=HTMLResponse)
async def config_html(request: Request):
    cfg = get_config()
    raw = cfg.to_public_dict()
    sections = _categorize(raw)
    return templates.TemplateResponse(request, "_config_table.html", {
        "sections": sections,
    })
