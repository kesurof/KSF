import os
from pathlib import Path
from typing import Optional

BASE_DIR = Path(os.environ.get("KSF_BASE_DIR", os.path.expanduser("~/serverbox")))
KSF_ENV_PATH = BASE_DIR / "config" / "ksf.env"
INSTALLED_DIR = BASE_DIR / "config" / "installed-apps"
TRAEFIK_DYNAMIC_DIR = BASE_DIR / "proxy" / "traefik" / "dynamic"
TRAEFIK_DIR = BASE_DIR / "proxy" / "traefik"
OAUTH2_DIR = BASE_DIR / "proxy" / "oauth2-proxy"
CROWDSEC_DIR = BASE_DIR / "proxy" / "crowdsec"
APPS_DIR = BASE_DIR / "apps"
DATA_DIR = BASE_DIR / "data"


class KsfConfig:
    def __init__(self):
        self.env: dict[str, str] = {}
        self.loaded = False
        self._load()

    def _load(self):
        if not KSF_ENV_PATH.exists():
            return
        with open(KSF_ENV_PATH) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, value = line.partition("=")
                    self.env[key.strip()] = self._unquote(value.strip())
        self.loaded = True

    @staticmethod
    def _unquote(value: str) -> str:
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        elif value.startswith("'") and value.endswith("'"):
            value = value[1:-1]
        return value

    def get(self, key: str, default: str = "") -> str:
        return self.env.get(key, default)

    def get_bool(self, key: str, default: bool = False) -> bool:
        val = self.env.get(key, "").lower()
        if val in ("true", "1", "yes"):
            return True
        if val in ("false", "0", "no"):
            return False
        return default

    def has_traefik(self) -> bool:
        return self.get_bool("WITH_TRAEFIK", False)

    def has_oauth2(self) -> bool:
        return self.get_bool("OAUTH2_ENABLED", False)

    def has_crowdsec(self) -> bool:
        return self.get_bool("WITH_CROWDSEC", False)

    def has_appsec(self) -> bool:
        return self.get_bool("CROWDSEC_APPSEC_ENABLED", False)

    @property
    def domain(self) -> str:
        return self.get("DOMAIN", "")

    @property
    def domains(self) -> list[str]:
        raw = self.get("DOMAINS", self.get("DOMAIN", ""))
        return [d.strip() for d in raw.split(",") if d.strip()]

    @property
    def network_name(self) -> str:
        return self.get("NETWORK_NAME", "proxy")

    @property
    def default_domain(self) -> str:
        domains = self.domains
        return domains[0] if domains else ""

    @property
    def traefik_host(self) -> str:
        return self.get("TRAEFIK_HOST", "traefik." + self.domain if self.domain else "")

    @property
    def oauth2_host(self) -> str:
        return self.get("OAUTH2_HOST", "oauth2." + self.domain if self.domain else "")

    def to_public_dict(self) -> dict:
        result = {}
        for k, v in self.env.items():
            if any(token in k for token in ("SECRET", "PASSWORD", "TOKEN", "API_KEY", "COOKIE", "PRIVATE_KEY", "BOUNCER_KEY")):
                result[k] = "******"
            else:
                result[k] = v
        return result


_config: Optional[KsfConfig] = None


def get_config() -> KsfConfig:
    global _config
    if _config is None:
        _config = KsfConfig()
    return _config


def reload_config():
    global _config
    _config = KsfConfig()
