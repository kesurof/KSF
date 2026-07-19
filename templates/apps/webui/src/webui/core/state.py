import os
from pathlib import Path
from typing import Optional

from .config import INSTALLED_DIR, APPS_DIR, DATA_DIR, BASE_DIR, get_config, TRAEFIK_DYNAMIC_DIR


class AppRecord:
    def __init__(self, instance: str, template: str = "",
                 host: str = "", domain: str = "", subdomain: str = "",
                 port: str = "", host_port: str = "",
                 docker_service: str = "",
                 protected: bool = True, public: bool = True,
                 local_only: bool = False, disabled: bool = False,
                 app_dir: str = "", app_data: str = "",
                 puid: str = "", pgid: str = "",
                 installed_at: str = ""):
        self.instance = instance
        self.template = template or instance
        self.host = host
        self.domain = domain
        self.subdomain = subdomain
        self.port = port
        self.host_port = host_port
        self.docker_service = docker_service
        self.protected = protected
        self.public = public
        self.local_only = local_only
        self.disabled = disabled
        self.app_dir = app_dir or str(APPS_DIR / instance)
        self.app_data = app_data or str(DATA_DIR / instance)
        self.puid = puid
        self.pgid = pgid
        self.installed_at = installed_at

    @property
    def access_label(self) -> str:
        if self.local_only:
            return f"127.0.0.1:{self.host_port}" if self.host_port else "local-only"
        if self.disabled:
            return "disabled"
        if self.host:
            suffix = f" +127.0.0.1:{self.host_port}" if self.host_port else ""
            return f"https://{self.host}{suffix}"
        return "not-exposed"

    @property
    def display_name(self) -> str:
        if self.instance != self.template and self.template:
            return f"{self.instance} [{self.template}]"
        return self.instance

    def to_dict(self) -> dict:
        return {
            "instance": self.instance,
            "template": self.template,
            "host": self.host,
            "domain": self.domain,
            "subdomain": self.subdomain,
            "port": self.port,
            "host_port": self.host_port,
            "docker_service": self.docker_service,
            "protected": self.protected,
            "public": self.public,
            "local_only": self.local_only,
            "disabled": self.disabled,
            "app_dir": self.app_dir,
            "app_data": self.app_data,
            "installed_at": self.installed_at,
            "access_label": self.access_label,
            "display_name": self.display_name,
        }


def parse_env_file(path: Path) -> dict:
    result = {}
    if not path.exists():
        return result
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                result[key.strip()] = _unquote(value.strip())
    return result


def _unquote(value: str) -> str:
    if value.startswith('"') and value.endswith('"'):
        value = value[1:-1]
    elif value.startswith("'") and value.endswith("'"):
        value = value[1:-1]
    return value


def _get_bool(env: dict, key: str, default: bool = True) -> bool:
    val = env.get(key, "").lower()
    if val in ("true", "1", "yes"):
        return True
    if val in ("false", "0", "no"):
        return False
    return default


def list_installed_apps() -> list[AppRecord]:
    apps = []
    if not INSTALLED_DIR.exists():
        return apps
    for f in sorted(INSTALLED_DIR.glob("*.env")):
        instance = f.stem
        env = parse_env_file(f)
        template = env.get("APP_NAME", instance)
        protected = _get_bool(env, "APP_PROTECTED", True)
        if not protected:
            protected = _get_bool(env, "APP_AUTH", True)
        apps.append(AppRecord(
            instance=instance,
            template=template,
            host=env.get("APP_HOST", ""),
            domain=env.get("APP_DOMAIN", ""),
            subdomain=env.get("APP_SUBDOMAIN", ""),
            port=env.get("APP_PORT", ""),
            host_port=env.get("APP_HOST_PORT", ""),
            docker_service=env.get("APP_DOCKER_SERVICE", ""),
            protected=protected,
            public=_get_bool(env, "APP_PUBLIC", True),
            local_only=_get_bool(env, "APP_LOCAL_ONLY", False),
            disabled=_get_bool(env, "APP_DISABLED", False),
            app_dir=env.get("APP_DIR", str(APPS_DIR / instance)),
            app_data=env.get("APP_DATA", str(DATA_DIR / instance)),
            puid=env.get("APP_PUID", ""),
            pgid=env.get("APP_PGID", ""),
            installed_at=env.get("APP_INSTALLED_AT", ""),
        ))
    return apps


def get_installed_app(instance: str) -> Optional[AppRecord]:
    for app in list_installed_apps():
        if app.instance == instance:
            return app
    return None


def list_available_templates() -> list[dict]:
    config = get_config()
    templates_dir = Path(os.environ.get("KSF_SCRIPT_DIR", "")) / "templates" / "apps"
    if not templates_dir.exists():
        return []
    results = []
    for d in sorted(templates_dir.iterdir()):
        if not d.is_dir():
            continue
        env_file = d / "app.env"
        if not env_file.exists():
            continue
        env = parse_env_file(env_file)
        results.append({
            "name": d.name,
            "description": env.get("APP_DESCRIPTION", d.name),
            "category": env.get("APP_CATEGORY", "general"),
            "port": env.get("APP_PORT", ""),
            "host": env.get("APP_HOST", d.name),
            "default_host": env.get("APP_DEFAULT_HOST", env.get("APP_HOST", d.name)),
            "protected": _get_bool(env, "APP_PROTECTED", True),
            "public": _get_bool(env, "APP_PUBLIC", True),
            "docker_service": env.get("APP_DOCKER_SERVICE", ""),
        })
    return results


def get_template(name: str) -> Optional[dict]:
    for t in list_available_templates():
        if t["name"] == name:
            return t
    return None


def list_route_files() -> list[dict]:
    if not TRAEFIK_DYNAMIC_DIR.exists():
        return []
    routes = []
    for f in sorted(TRAEFIK_DYNAMIC_DIR.glob("route-*.yml")):
        content = f.read_text()
        host = ""
        if "Host(`" in content:
            start = content.index("Host(`") + 6
            end = content.index("`)", start)
            host = content[start:end]
        has_oauth2 = "oauth2-chain" in content
        has_crowdsec = "security-chain" in content or "crowdsec" in content
        has_placeholder = "${" in content or "__" in content
        routes.append({
            "filename": f.name,
            "host": host,
            "has_oauth2": has_oauth2,
            "has_crowdsec": has_crowdsec,
            "has_placeholder": has_placeholder,
        })
    return routes
