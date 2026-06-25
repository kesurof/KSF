import os
import asyncio
import subprocess
import re
import logging
from datetime import datetime, timezone

from app import utils
from app.logging_config import TeeSubprocess, get_correlation_id

logger = logging.getLogger("ksf-web")

KSF_BASE_DIR = os.environ.get("KSF_BASE_DIR", "/serverbox")
KSF_REPO_DIR = os.environ.get("KSF_REPO_DIR", "/ksf")
INSTALLED_DIR = os.path.join(KSF_BASE_DIR, "config", "installed-apps")
KSF_BIN = os.path.join(KSF_REPO_DIR, "ksf.sh")
APP_BIN = os.path.join(KSF_REPO_DIR, "app.sh")
ACTIONS_LOG_DIR = os.path.join(KSF_BASE_DIR, "logs", "ksf-web", "actions")

EXEC_ENV = {
    **os.environ,
    "KSF_BASE_DIR": KSF_BASE_DIR,
    "KSF_REPO_DIR": KSF_REPO_DIR,
    "BASE_DIR": KSF_BASE_DIR,
    # HOME pointe sur /tmp (toujours accessible en écriture) plutôt que
    # /home/appuser (qui appartient à l'appuser 1000 de l'image, pas à
    # l'uid réel 1002 de l'hôte). Les scripts n'utilisent plus $HOME
    # depuis qu'on force BASE_DIR.
    "HOME": "/tmp",
    "XDG_CONFIG_HOME": "/tmp",
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
}

TEMPLATES_DIR = os.path.join(KSF_REPO_DIR, "templates", "apps")

ALLOWED_COMMANDS = {
    "doctor": [KSF_BIN, "doctor"],
    "status": [KSF_BIN, "status"],
    "config": [KSF_BIN, "config"],
    "routes": [KSF_BIN, "routes"],
    "backup_create": [KSF_BIN, "backup", "create"],
    "backup_verify_latest": [KSF_BIN, "backup", "verify", "latest"],
    "backup_restore_latest_dryrun": [KSF_BIN, "backup", "restore", "latest", "--dry-run"],
    "update_all": [KSF_BIN, "update", "all", "--yes"],
    "update_service": [KSF_BIN, "update"],  # nécessite extra_args: <service>
    "crowdsec_status": [KSF_BIN, "crowdsec", "status"],
    "crowdsec_alerts": [KSF_BIN, "crowdsec", "alerts"],
    "crowdsec_bouncers": [KSF_BIN, "crowdsec", "bouncers"],
    "crowdsec_decisions": [KSF_BIN, "crowdsec", "decisions"],
    "crowdsec_ban": [KSF_BIN, "crowdsec", "ban"],  # extra_args: <ip> <duration>
    "crowdsec_unban": [KSF_BIN, "crowdsec", "unban"],  # extra_args: <ip>
    "crowdsec_flush_decisions": [KSF_BIN, "crowdsec", "flush-decisions"],
    "crowdsec_restart": [KSF_BIN, "crowdsec", "restart"],
    "appsec_status": [KSF_BIN, "crowdsec", "appsec", "status"],
    "appsec_enable": [KSF_BIN, "crowdsec", "appsec", "enable", "--yes"],
    "appsec_disable": [KSF_BIN, "crowdsec", "appsec", "disable", "--yes"],
    "restart": [KSF_BIN, "restart", "--yes"],
    "trusted_ips_cloudflare": [KSF_BIN, "trusted-ips", "cloudflare"],
    "clean_data": [KSF_BIN, "clean-data"],  # extra_args: <app>
}

# Commandes qui requièrent --yes pour ne pas être bloquées par un prompt.
ALLOWED_COMMANDS_WITH_YES = {
    "update_service", "appsec_enable", "appsec_disable",
    "crowdsec_flush_decisions", "crowdsec_restart",
}

ALLOWED_APP_ACTIONS = {"status", "update", "restart", "start", "stop", "disable", "remove", "install", "rebuild"}
APP_ACTIONS_WITH_YES = {"update", "disable", "remove", "start", "stop", "install", "rebuild"}


def _validate_app_name(name: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9]([a-z0-9\-]*[a-z0-9])?", name))


def _run_subprocess_sync(cmd: list[str], timeout: int) -> tuple[bool, str]:
    """Helper synchrone (à appeler via asyncio.to_thread). Pour les commandes
    one-shot courtes (doctor, status, config, routes, etc.) qui n'ont pas besoin
    de capture structurée ligne par ligne.
    """
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            cwd=KSF_REPO_DIR, env=EXEC_ENV,
        )
        output = utils.mask_secrets(result.stdout + result.stderr)
        return result.returncode == 0, output.strip()
    except subprocess.TimeoutExpired:
        return False, "La commande a expire (timeout)."
    except FileNotFoundError:
        return False, f"Script introuvable : {cmd[0]}"
    except Exception as e:
        logger.exception("Erreur lors de l'execution de %s", cmd)
        return False, f"Erreur interne : {type(e).__name__}"


def _actions_log_path(prefix: str) -> str:
    os.makedirs(ACTIONS_LOG_DIR, exist_ok=True)
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return os.path.join(ACTIONS_LOG_DIR, f"{prefix}-{ts}.log")


async def run_command(key: str, extra_args: list[str] | None = None, timeout: int = 120) -> tuple[bool, str]:
    """Async wrapper qui ne bloque pas l'event loop.

    `extra_args` est ajouté à la fin de la commande whitelistée après
    validation. Le caller doit valider chaque argument (IP, duration, app name).
    """
    if key not in ALLOWED_COMMANDS:
        return False, f"Commande non autorisee : {key}"
    cmd = list(ALLOWED_COMMANDS[key])
    if extra_args:
        for a in extra_args:
            if not isinstance(a, str) or not a or "\x00" in a:
                return False, "Argument invalide (chaîne non-vide requise)"
        cmd.extend(extra_args)
    if key in ALLOWED_COMMANDS_WITH_YES and "--yes" not in cmd and "-y" not in cmd:
        cmd.append("--yes")
    return await asyncio.to_thread(_run_subprocess_sync, cmd, timeout)


async def run_app_command(app_name: str, action: str, extra_args: list[str] | None = None,
                          timeout: int = 120, correlation_id: str | None = None) -> tuple[bool, str, str]:
    """Async wrapper qui ne bloque pas l'event loop.

    Utilise TeeSubprocess pour teer la sortie vers un fichier brut
    (`actions/<action>-<app>-<ts>.log`) ET vers le logger structuré
    `ksf-web.actions` (events `subprocess.line` JSONL).

    Renvoie (ok, output_text, log_path).
    """
    if not _validate_app_name(app_name):
        return False, "Nom d'application invalide.", ""
    if action not in ALLOWED_APP_ACTIONS:
        return False, f"Action non autorisee : {action}", ""
    cmd = [APP_BIN, action, app_name]
    if extra_args:
        cmd.extend(extra_args)
    if action in APP_ACTIONS_WITH_YES:
        cmd.append("--yes")
    log_path = _actions_log_path(f"{action}-{app_name}")
    cid = correlation_id or get_correlation_id()
    try:
        async with TeeSubprocess(
            cmd, log_path,
            logger_name="ksf-web.actions",
            cwd=KSF_REPO_DIR,
            env=EXEC_ENV,
            correlation_id=cid,
            extra={"action": action, "target": app_name},
        ) as tee:
            assert tee.process is not None
            try:
                await asyncio.wait_for(tee.process.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                tee.process.kill()
                await tee.process.wait()
                return False, "La commande a expire (timeout).", log_path
        ok = (tee.exit_code == 0)
        try:
            with open(log_path, "r", errors="replace") as f:
                output = f.read()
        except OSError:
            output = ""
        return ok, output, log_path
    except FileNotFoundError:
        return False, f"Script introuvable : {cmd[0]}", ""
    except Exception as e:
        logger.exception("Erreur lancement app command %s/%s", action, app_name)
        return False, f"Erreur interne : {type(e).__name__}: {e}", ""


def list_installed_apps() -> list[dict]:
    apps = []
    if not os.path.isdir(INSTALLED_DIR):
        return apps

    ksf_env = get_ksf_env()
    domain = ksf_env.get("DOMAIN", ksf_env.get("DOMAINS", ""))
    if domain:
        domain = domain.split(",")[0].strip()

    for fname in sorted(os.listdir(INSTALLED_DIR)):
        if not fname.endswith(".env"):
            continue
        app_name = fname[:-4]
        env_data = utils.parse_env_file(os.path.join(INSTALLED_DIR, fname))

        app_host = env_data.get("APP_HOST", "") or env_data.get("APP_DOMAIN", "")
        if app_host and domain and "." not in app_host:
            app_host = f"{app_host}.{domain}"

        if not app_host:
            runtime_dir = env_data.get("APP_DIR", os.path.join(KSF_BASE_DIR, "apps", app_name))
            runtime_data = utils.parse_env_file(os.path.join(runtime_dir, "app.env"))
            rh = runtime_data.get("APP_HOST", "") or runtime_data.get("APP_DOMAIN", "")
            if rh and domain and "." not in rh:
                rh = f"{rh}.{domain}"
            app_host = rh

        apps.append({
            "name": app_name,
            "host": app_host or "",
            "port": env_data.get("APP_PORT", ""),
            "protected": env_data.get("APP_PROTECTED", "true") == "true",
            "disabled": env_data.get("APP_DISABLED", "false") == "true",
            "dir": env_data.get("APP_DIR", ""),
            "installed_at": env_data.get("APP_INSTALLED_AT", ""),
        })
    return apps


def list_available_apps() -> list[dict]:
    apps = []
    if not os.path.isdir(TEMPLATES_DIR):
        return apps
    for app_name in sorted(os.listdir(TEMPLATES_DIR)):
        app_dir = os.path.join(TEMPLATES_DIR, app_name)
        if not os.path.isdir(app_dir):
            continue
        env_path = os.path.join(app_dir, "app.env")
        if not os.path.isfile(env_path):
            continue
        env_data = utils.parse_env_file(env_path)
        apps.append({
            "name": app_name,
            "description": env_data.get("APP_DESCRIPTION", ""),
            "category": env_data.get("APP_CATEGORY", "other"),
            "port": env_data.get("APP_PORT", ""),
            "protected": env_data.get("APP_PROTECTED", "true") == "true",
            "installed": os.path.isfile(os.path.join(INSTALLED_DIR, f"{app_name}.env")),
        })
    return apps


def get_installed_app_env(app_name: str) -> dict:
    if not _validate_app_name(app_name):
        return {}
    env_path = os.path.join(INSTALLED_DIR, f"{app_name}.env")
    if not os.path.isfile(env_path):
        return {}
    env_data = utils.parse_env_file(env_path)
    template_env_path = os.path.join(TEMPLATES_DIR, app_name, "app.env")
    if os.path.isfile(template_env_path):
        template_data = utils.parse_env_file(template_env_path)
        env_data.setdefault("APP_DESCRIPTION", template_data.get("APP_DESCRIPTION", ""))
        env_data.setdefault("APP_CATEGORY", template_data.get("APP_CATEGORY", "other"))
    return env_data


def get_ksf_env() -> dict:
    env_path = os.path.join(KSF_BASE_DIR, "config", "ksf.env")
    if not os.path.isfile(env_path):
        return {}
    return utils.parse_env_file(env_path)


def get_appsec_state() -> str:
    ksf_env = get_ksf_env()
    if not ksf_env.get("CROWDSEC_APPSEC_ENABLED", "false").lower() == "true":
        return "inactive"
    if os.path.isfile(os.path.join(KSF_BASE_DIR, "proxy", "crowdsec", "appsec.yaml")):
        return "active"
    return "indeterminate"


def list_backups() -> tuple[list[dict], str | None]:
    backups_dir = os.path.join(KSF_BASE_DIR, "backups")
    if not os.path.isdir(backups_dir):
        return [], None
    if not os.access(backups_dir, os.R_OK):
        return [], "Accès en lecture refusé sur le dossier de sauvegardes. Vérifiez les permissions (UID/GID du conteneur ksf-web)."
    try:
        all_files = os.listdir(backups_dir)
    except PermissionError:
        return [], "Accès en lecture refusé sur le dossier de sauvegardes. Vérifiez les permissions (UID/GID du conteneur ksf-web)."
    except OSError as e:
        return [], f"Erreur de lecture du dossier de sauvegardes ({e.errno})."

    backups = []
    for fname in sorted(all_files, reverse=True):
        if not fname.endswith(".tar.gz"):
            continue
        fpath = os.path.join(backups_dir, fname)
        if not os.path.isfile(fpath):
            continue
        try:
            stat = os.stat(fpath)
        except OSError:
            continue
        backups.append({
            "name": fname,
            "size": utils.format_size(stat.st_size),
            "created": utils.format_timestamp(stat.st_mtime),
            "has_checksum": os.path.isfile(f"{fpath}.sha256"),
        })
    if backups:
        backups[0]["is_latest"] = True
    return backups, None
