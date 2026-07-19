import re
import time
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, HTMLResponse
from ..core.config import (get_config, BASE_DIR, INSTALLED_DIR,
                            TRAEFIK_DIR, OAUTH2_DIR, CROWDSEC_DIR)
from ..core.docker import get_docker
from ..core.state import list_installed_apps
from ..core.state import list_route_files
from ..templates import templates

router = APIRouter()


@router.get("/status")
def api_status():
    cfg = get_config()
    docker = get_docker()
    apps = list_installed_apps()
    running = 0
    for app in apps:
        state = docker.stack_state(app.app_dir, app.docker_service)
        if state["running"] > 0:
            running += 1
    return {
        "installed": cfg.loaded,
        "domain": cfg.domain or "",
        "docker_available": docker.available(),
        "with_traefik": cfg.has_traefik(),
        "with_oauth2": cfg.has_oauth2(),
        "with_crowdsec": cfg.has_crowdsec(),
        "with_appsec": cfg.has_appsec(),
        "apps_total": len(apps),
        "apps_running": running,
    }


@router.get("/status/dashboard", response_class=HTMLResponse)
def dashboard_status(request: Request):
    cfg = get_config()
    docker = get_docker()
    apps = list_installed_apps()
    running = sum(1 for app in apps
                  if get_docker().stack_state(app.app_dir, app.docker_service)["running"] > 0)
    return templates.TemplateResponse(request, "_status_cards.html", {
        "installed": cfg.loaded,
        "domain": cfg.domain or "",
        "docker_available": docker.available(),
        "config": cfg,
        "apps_total": len(apps),
        "apps_running": running,
    })


@router.get("/doctor")
def api_doctor():
    cfg = get_config()
    result = _doctor_check(cfg)
    return result


@router.get("/doctor/html", response_class=HTMLResponse)
def doctor_html(request: Request):
    cfg = get_config()
    result = _doctor_check(cfg)
    return templates.TemplateResponse(request, "_checks_list.html", {
        "checks": result["checks"],
    })


def _doctor_check(cfg):
    errors = 0
    warnings = 0
    checks = []

    def add(status, label, detail=""):
        nonlocal errors, warnings
        checks.append({"status": status, "label": label, "detail": detail})
        if status == "err":
            errors += 1
        elif status == "warn":
            warnings += 1

    env_file = BASE_DIR / "config" / "ksf.env"
    if env_file.exists():
        add("ok", "Configuration présente")
        if env_file.stat().st_mode & 0o077:
            add("warn", "Permissions de configuration", "ksf.env devrait etre en 600")
        else:
            add("ok", "Permissions de configuration", "ksf.env est protege")
    else:
        add("err", "Configuration absente")

    for d in [BASE_DIR / "proxy",
              BASE_DIR / "apps",
              BASE_DIR / "data",
              BASE_DIR / "config",
              INSTALLED_DIR]:
        if d.exists():
            add("ok", "Répertoire présent", str(d))
        else:
            add("err", "Répertoire manquant", str(d))

    docker = get_docker()
    stacks = (("Traefik", cfg.has_traefik(), TRAEFIK_DIR),
              ("OAuth2 Proxy", cfg.has_oauth2(), OAUTH2_DIR),
              ("CrowdSec", cfg.has_crowdsec(), CROWDSEC_DIR))
    for name, enabled, stack_dir in stacks:
        if not enabled:
            continue
        compose = stack_dir / "docker-compose.yml"
        if not compose.exists():
            add("err", f"Stack {name}", "docker-compose.yml absent")
            continue
        add("ok", f"Stack {name}", "docker-compose.yml present")
        code, stdout, stderr = docker.compose_run(str(stack_dir), "config", "--quiet")
        if code == 0:
            add("ok", f"Compose {name}", "configuration valide")
        else:
            add("warn", f"Compose {name}", (stderr or stdout or "validation impossible")[-300:])

    if docker.available():
        add("ok", "Daemon Docker", "accessible")
        try:
            docker.client.networks.get(cfg.network_name)
            add("ok", "Reseau Docker", cfg.network_name)
        except Exception:
            add("warn", "Reseau Docker", f"{cfg.network_name} introuvable")
    else:
        add("err", "Daemon Docker", "indisponible")

    routes = list_route_files()
    installed = {app.instance for app in list_installed_apps()}
    for route in routes:
        instance = route["filename"].removeprefix("route-").removesuffix(".yml")
        if route["has_placeholder"]:
            add("err", "Placeholder dans une route", route["filename"])
        if instance not in installed and instance not in {"traefik", "oauth2-proxy"}:
            add("warn", "Route orpheline", route["filename"])
    if not any(route["has_placeholder"] for route in routes):
        add("ok", "Routes Traefik", "aucun placeholder detecte")

    if cfg.has_traefik():
        trusted = cfg.get("TRAEFIK_TRUSTED_IPS")
        add("ok" if trusted else "warn", "Trusted IPs", "configures" if trusted else "non configures")

    if cfg.get_bool("DNS_AUTO_CREATE"):
        dns_ready = all((cfg.get("DNS_PROVIDER") == "cloudflare", cfg.get("CF_API_EMAIL"),
                         cfg.get("CF_API_KEY"), cfg.get("SERVER_PUBLIC_IP")))
        add("ok" if dns_ready else "warn", "DNS automatique", "configuration Cloudflare complete" if dns_ready else "configuration Cloudflare incomplete")
    else:
        add("ok", "DNS automatique", "desactive")

    if cfg.has_crowdsec() and (CROWDSEC_DIR / "docker-compose.yml").exists():
        code, stdout, stderr = docker.compose_run(str(CROWDSEC_DIR), "exec", "-T", "crowdsec", "cscli", "console", "status")
        add("ok" if code == 0 else "warn", "Console CrowdSec", "accessible" if code == 0 else (stderr or stdout or "indisponible")[-300:])

    _doctor_middlewares(cfg, add)
    _doctor_crowdsec_plugin(cfg, add)
    _doctor_access_log(cfg, add)
    _doctor_containers(cfg, docker, add)
    _doctor_apps(docker, add)

    return {"errors": errors, "warnings": warnings, "checks": checks}


def _doctor_middlewares(cfg, add):
    dynamic_dir = TRAEFIK_DIR / "dynamic"
    references = set()
    definitions = set()
    for path in dynamic_dir.glob("*.yml") if dynamic_dir.exists() else []:
        try:
            content = path.read_text()
        except OSError:
            continue
        references.update(re.findall(r"^\s*-\s+([A-Za-z0-9_.@-]+)\s*$", content, re.MULTILINE))
        if "middlewares:" in content:
            definitions.update(re.findall(r"^\s{4}([A-Za-z0-9_.@-]+):\s*$", content, re.MULTILINE))
    expected = set()
    if cfg.has_oauth2():
        expected.add("oauth2-chain")
    if cfg.has_crowdsec():
        expected.add("security-chain")
    for middleware in sorted(references | expected):
        if middleware in definitions:
            add("ok", "Middleware Traefik", middleware)
        else:
            severity = "err" if middleware in references else "warn"
            add(severity, "Middleware Traefik absent", middleware)


def _doctor_crowdsec_plugin(cfg, add):
    if not cfg.has_crowdsec():
        return
    static_path = TRAEFIK_DIR / "traefik.yml"
    dynamic_path = TRAEFIK_DIR / "dynamic" / "middleware-crowdsec.yml"
    static = _read_text(static_path)
    dynamic = _read_text(dynamic_path)
    if "crowdsec-bouncer-traefik-plugin" in static and re.search(r"^\s*bouncer:\s*$", static, re.MULTILINE):
        add("ok", "Plugin CrowdSec Traefik", "plugin bouncer configure")
    else:
        add("err", "Plugin CrowdSec Traefik", "plugin bouncer absent de traefik.yml")
    if "plugin:" in dynamic and re.search(r"^\s*bouncer:\s*$", dynamic, re.MULTILINE) and "crowdsecMode" in dynamic:
        add("ok", "Middleware CrowdSec", "plugin.bouncer actif")
    else:
        add("err", "Middleware CrowdSec", "plugin.bouncer ou son mode est absent")


def _doctor_access_log(cfg, add, now=None):
    if not cfg.has_traefik():
        return
    log_path = TRAEFIK_DIR / "logs" / "access.log"
    if not log_path.exists():
        add("err", "Access log Traefik", f"absent ({log_path})")
        return
    if not log_path.is_file() or not log_path.stat().st_mode:
        add("err", "Access log Traefik", "inaccessible")
        return
    try:
        stat = log_path.stat()
    except OSError:
        add("err", "Access log Traefik", "illisible")
        return
    if stat.st_size == 0:
        add("warn", "Access log Traefik", "vide: aucune requete recente ou journalisation inactive")
        return
    age = (now if now is not None else time.time()) - stat.st_mtime
    if age > 86400:
        add("warn", "Access log Traefik", f"dernier ecrit il y a {int(age // 3600)} h")
    else:
        add("ok", "Access log Traefik", "present et recent")


def _doctor_containers(cfg, docker, add):
    if not docker.available():
        return
    expected = (("Traefik", cfg.has_traefik(), "traefik"),
                ("OAuth2 Proxy", cfg.has_oauth2(), "oauth2-proxy"),
                ("CrowdSec", cfg.has_crowdsec(), "crowdsec"))
    for label, enabled, name in expected:
        if not enabled:
            continue
        try:
            container = docker.client.containers.get(name)
            state = container.attrs.get("State", {})
            status = state.get("Status", "unknown")
            health = state.get("Health", {}).get("Status", "")
            restarts = state.get("RestartCount", 0)
            if status != "running" or health == "unhealthy":
                add("err", f"Conteneur {label}", f"{status}{' (' + health + ')' if health else ''}")
            elif restarts and restarts > 3:
                add("warn", f"Conteneur {label}", f"actif mais {restarts} redemarrages")
            else:
                add("ok", f"Conteneur {label}", health or "actif")
            _doctor_image(container, label, add)
        except Exception as exc:
            add("warn", f"Conteneur {label}", f"absent ou non verifiable: {str(exc)[:120]}")


def _doctor_image(container, label, add):
    declared = container.attrs.get("Config", {}).get("Image", "")
    image_id = container.attrs.get("Image", "")
    image = getattr(container, "image", None)
    digests = image.attrs.get("RepoDigests", []) if image else []
    tags = image.tags if image else []
    if not declared:
        add("warn", f"Image {label}", "image declaree indisponible")
    elif not image_id:
        add("warn", f"Image {label}", "image executee indisponible")
    elif tags and declared not in tags:
        add("err", f"Image {label}", "image declaree differente de l'image executee")
    elif ":latest" in declared and not digests:
        add("warn", f"Image {label}", "tag latest sans digest: comparaison indeterminee")
    elif digests:
        add("ok", f"Image {label}", "image executee identifiee par digest")
    else:
        add("warn", f"Image {label}", "tag identique mais digest non comparable")


def _doctor_apps(docker, add):
    for app in list_installed_apps():
        compose = Path(app.app_dir) / "docker-compose.yml"
        if not compose.is_file():
            add("err", "Stack application", f"{app.instance}: docker-compose.yml absent")
            continue
        code, stdout, stderr = docker.compose_run(app.app_dir, "config", "--quiet")
        if code == 0:
            add("ok", "Compose application", f"{app.instance}: valide")
        else:
            add("err", "Compose application", f"{app.instance}: {(stderr or stdout or 'invalide')[-220:]}")


def _read_text(path):
    try:
        return path.read_text() if path.is_file() else ""
    except OSError:
        return ""
