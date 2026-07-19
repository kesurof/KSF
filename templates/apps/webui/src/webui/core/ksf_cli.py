import os
import re
import subprocess
from pathlib import Path

from .config import BASE_DIR, get_config


CLI_DIR = Path(os.environ.get("KSF_CLI_DIR", "/app/ksf"))
SECRET_KEYS = ("CF_API_KEY", "OAUTH2_CLIENT_SECRET", "OAUTH2_COOKIE_SECRET", "CROWDSEC_BOUNCER_KEY")


def _redact(value: str) -> str:
    for secret in SECRET_KEYS:
        configured = get_config().get(secret)
        if configured:
            value = value.replace(configured, "******")
    return value[-30000:]


def run_ksf(*args: str, timeout: int = 900, dry_run: bool = False) -> tuple[int, str, str]:
    script = CLI_DIR / "ksf.sh"
    if not script.is_file():
        return -1, "", "Les scripts KSF embarques sont introuvables. Reinstallez ou mettez a jour le Web UI."
    command = ["bash", str(script), *args, "--base-dir", str(BASE_DIR)]
    if dry_run:
        command.append("--dry-run")
    command.append("--yes")
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        return result.returncode, _redact(result.stdout), _redact(result.stderr)
    except subprocess.TimeoutExpired:
        return -1, "", "Delai depasse pendant l'execution de la commande KSF."
    except OSError as exc:
        return -1, "", str(exc)


def run_app(*args: str, timeout: int = 900, dry_run: bool = False) -> tuple[int, str, str]:
    script = CLI_DIR / "app.sh"
    if not script.is_file():
        return -1, "", "Le script applicatif KSF embarque est introuvable."
    command = ["bash", str(script), *args, "--base-dir", str(BASE_DIR)]
    if dry_run:
        command.append("--dry-run")
    command.append("--yes")
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        return result.returncode, _redact(result.stdout), _redact(result.stderr)
    except subprocess.TimeoutExpired:
        return -1, "", "Delai depasse pendant la mise a jour de l'application."
    except OSError as exc:
        return -1, "", str(exc)


def run_dns(action: str, host: str, timeout: int = 60) -> tuple[int, str, str]:
    if action not in {"ensure", "delete"}:
        return -1, "", "Action DNS invalide."
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", host, re.IGNORECASE):
        return -1, "", "Host DNS invalide."
    script = CLI_DIR / "lib" / "dns_cloudflare.sh"
    if not script.is_file():
        return -1, "", "Le module DNS KSF embarque est introuvable."
    function = "dns_ensure_record" if action == "ensure" else "dns_delete_record"
    shell = "set -euo pipefail; BASE_DIR=$1; export BASE_DIR; source \"$2\"; \"$3\" \"$4\""
    try:
        result = subprocess.run(
            ["bash", "-c", shell, "ksf-dns", str(BASE_DIR), str(script), function, host],
            capture_output=True, text=True, timeout=timeout,
        )
        return result.returncode, _redact(result.stdout), _redact(result.stderr)
    except subprocess.TimeoutExpired:
        return -1, "", "Delai depasse pendant l'operation DNS."
    except OSError as exc:
        return -1, "", str(exc)
