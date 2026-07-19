from pathlib import Path
from .config import TRAEFIK_DYNAMIC_DIR, get_config


def render_app_route(instance: str, host: str, port: str,
                     protected: bool = True,
                     docker_service: str = "",
                     dry_run: bool = False) -> Path:
    config = get_config()
    route_id = instance
    upstream_service = docker_service or instance
    dest = TRAEFIK_DYNAMIC_DIR / f"route-{instance}.yml"

    middlewares: list[str] = []
    if protected:
        if not config.has_oauth2():
            raise ValueError("OAuth2 Proxy is not configured for this platform")
        middlewares.append("oauth2-chain")
    elif config.has_crowdsec():
        middlewares.append("security-chain")

    middleware_block = ""
    if middlewares:
        middleware_block = "      middlewares:\n" + "\n".join(
            f"        - {middleware}" for middleware in middlewares
        ) + "\n"

    content = f"""http:
  routers:
    {route_id}:
      rule: "Host(`{host}`)"
      entryPoints:
        - websecure
      service: {route_id}
{middleware_block}      tls:
        certResolver: letsencrypt
  services:
    {route_id}:
      loadBalancer:
        servers:
          - url: http://{upstream_service}:{port}
"""

    if not dry_run:
        TRAEFIK_DYNAMIC_DIR.mkdir(parents=True, exist_ok=True)
        dest.write_text(content)
    return dest


def remove_route(instance: str, dry_run: bool = False) -> bool:
    dest = TRAEFIK_DYNAMIC_DIR / f"route-{instance}.yml"
    if dest.exists() and not dry_run:
        dest.unlink()
        return True
    return dest.exists()
