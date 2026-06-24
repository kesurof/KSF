"""Utilitaires partagés ksf-web."""
import re
from datetime import datetime, timezone


def utcnow_dt() -> datetime:
    """Datetime UTC courant (timezone-aware)."""
    return datetime.now(tz=timezone.utc)


def utcnow_str() -> str:
    """Timestamp UTC courant formaté (ex: '2026-06-24 15:09:42 UTC')."""
    return utcnow_dt().strftime("%Y-%m-%d %H:%M:%S UTC")


_SECRET_PATTERN = re.compile(
    r"(SECRET|TOKEN|PASSWORD|COOKIE|CLIENT_SECRET|CF_API_KEY|BOUNCER_KEY)\s*[=:]\s*\S+",
    re.IGNORECASE,
)


def parse_env_file(path: str) -> dict:
    """Parse un fichier .env / app.env en dict. Ignore les lignes vides/commentaires.

    Strip les guillemets autour des valeurs (`KEY="value"` → `value`).
    Best-effort : retourne `{}` si le fichier n'existe pas ou ne peut être lu.
    """
    data = {}
    try:
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                value = value.strip().strip("\"'")
                data[key.strip()] = value
    except Exception:
        pass
    return data


def mask_secrets(text: str) -> str:
    """Masque les valeurs de variables sensibles dans un output texte.

    Ex: `OAUTH_CLIENT_SECRET=abc123` → `OAUTH_CLIENT_SECRET= ******`
    Patterns matchés : SECRET, TOKEN, PASSWORD, COOKIE, CLIENT_SECRET, CF_API_KEY, BOUNCER_KEY.
    """
    return _SECRET_PATTERN.sub(lambda m: m.group(0).split("=")[0].strip() + "= ******", text)


def format_size(size_bytes: int) -> str:
    """Formate une taille en bytes en string lisible (B / KB / MB / GB / TB)."""
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def format_timestamp(ts: float) -> str:
    """Formate un timestamp Unix en string UTC lisible."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
