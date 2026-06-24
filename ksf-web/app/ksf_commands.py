import os
import subprocess
import re
import logging

logger = logging.getLogger("ksf-web")

KSF_BASE_DIR = os.environ.get("KSF_BASE_DIR", "/serverbox")
KSF_REPO_DIR = os.environ.get("KSF_REPO_DIR", "/ksf")
INSTALLED_DIR = os.path.join(KSF_BASE_DIR, "config", "installed-apps")
KSF_BIN = os.path.join(KSF_REPO_DIR, "ksf.sh")
APP_BIN = os.path.join(KSF_REPO_DIR, "app.sh")

EXEC_ENV = {
    **os.environ,
    "KSF_BASE_DIR": KSF_BASE_DIR,
    "KSF_REPO_DIR": KSF_REPO_DIR,
    "HOME": "/home/appuser",
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
}

TEMPLATES_DIR = os.path.join(KSF_REPO_DIR, "templates", "apps")

ALLOWED_COMMANDS = {
    "doctor": [KSF_BIN, "doctor"],
    "backup_create": [KSF_BIN, "backup", "create"],
    "backup_verify_latest": [KSF_BIN, "backup", "verify", "latest"],
    "backup_restore_latest_dryrun": [KSF_BIN, "backup", "restore", "latest", "--dry-run"],
    "update_all": [KSF_BIN, "update", "all", "--yes"],
    "crowdsec_status": [KSF_BIN, "crowdsec", "status"],
    "crowdsec_alerts": [KSF_BIN, "crowdsec", "alerts"],
    "crowdsec_bouncers": [KSF_BIN, "crowdsec", "bouncers"],
    "appsec_status": [KSF_BIN, "crowdsec", "appsec", "status"],
}

ALLOWED_APP_ACTIONS = {"status", "update", "restart", "start", "stop", "disable", "remove", "install"}
APP_ACTIONS_WITH_YES = {"update", "disable", "remove", "start", "stop", "install"}


def _validate_app_name(name: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9]([a-z0-9\-]*[a-z0-9])?", name))


def run_command(key: str, timeout: int = 120) -> tuple[bool, str]:
    if key not in ALLOWED_COMMANDS:
        return False, f"Commande non autorisee : {key}"
    cmd = ALLOWED_COMMANDS[key]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            cwd=KSF_REPO_DIR, env=EXEC_ENV,
        )
        output = _mask_secrets(result.stdout + result.stderr)
        return result.returncode == 0, output.strip()
    except subprocess.TimeoutExpired:
        return False, "La commande a expire (timeout)."
    except FileNotFoundError:
        return False, f"Script introuvable : {cmd[0]}"
    except Exception as e:
        logger.exception("Erreur lors de l'execution de %s", key)
        return False, f"Erreur interne : {type(e).__name__}"


def run_app_command(app_name: str, action: str, extra_args: list[str] | None = None, timeout: int = 120) -> tuple[bool, str]:
    if not _validate_app_name(app_name):
        return False, "Nom d'application invalide."
    if action not in ALLOWED_APP_ACTIONS:
        return False, f"Action non autorisee : {action}"
    cmd = [APP_BIN, action, app_name]
    if extra_args:
        cmd.extend(extra_args)
    if action in APP_ACTIONS_WITH_YES:
        cmd.append("--yes")
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            cwd=KSF_REPO_DIR, env=EXEC_ENV,
        )
        output = _mask_secrets(result.stdout + result.stderr)
        return result.returncode == 0, output.strip()
    except subprocess.TimeoutExpired:
        return False, "La commande a expire (timeout)."
    except FileNotFoundError:
        return False, f"Script introuvable : {cmd[0]}"
    except Exception as e:
        logger.exception("Erreur lors de l'execution de %s %s", action, app_name)
        return False, f"Erreur interne : {type(e).__name__}"


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
        env_data = _parse_env_file(os.path.join(INSTALLED_DIR, fname))

        app_host = env_data.get("APP_HOST", "") or env_data.get("APP_DOMAIN", "")
        if app_host and domain and "." not in app_host:
            app_host = f"{app_host}.{domain}"

        if not app_host:
            runtime_dir = env_data.get("APP_DIR", os.path.join(KSF_BASE_DIR, "apps", app_name))
            runtime_data = _parse_env_file(os.path.join(runtime_dir, "app.env"))
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
        env_data = _parse_env_file(env_path)
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
    env_data = _parse_env_file(env_path)
    template_env_path = os.path.join(TEMPLATES_DIR, app_name, "app.env")
    if os.path.isfile(template_env_path):
        template_data = _parse_env_file(template_env_path)
        env_data.setdefault("APP_DESCRIPTION", template_data.get("APP_DESCRIPTION", ""))
        env_data.setdefault("APP_CATEGORY", template_data.get("APP_CATEGORY", "other"))
    return env_data


def get_ksf_env() -> dict:
    env_path = os.path.join(KSF_BASE_DIR, "config", "ksf.env")
    if not os.path.isfile(env_path):
        return {}
    return _parse_env_file(env_path)


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
            "size": _format_size(stat.st_size),
            "created": _format_timestamp(stat.st_mtime),
            "has_checksum": os.path.isfile(f"{fpath}.sha256"),
        })
    if backups:
        backups[0]["is_latest"] = True
    return backups, None


def _parse_env_file(path: str) -> dict:
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


def _mask_secrets(text: str) -> str:
    pattern = re.compile(
        r"(SECRET|TOKEN|PASSWORD|COOKIE|CLIENT_SECRET|CF_API_KEY|BOUNCER_KEY)\s*[=:]\s*\S+",
        re.IGNORECASE,
    )
    return pattern.sub(lambda m: m.group(0).split("=")[0].strip() + "= ******", text)


def _format_size(size_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def _format_timestamp(ts: float) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
