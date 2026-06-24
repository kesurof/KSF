"""Helpers extraits de main.py : validation, formatage, audit, normalisation.

Aucun handler n'est défini ici, uniquement des fonctions utilitaires utilisées
par les blueprints `app/routes/`.
"""
import os
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, Request

from app import config


LOG_DIR = config.LOG_DIR
OUTPUT_TRUNCATE_BYTES = config.OUTPUT_TRUNCATE_BYTES


def now_str() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def truncate_output(output: str) -> tuple[str, str | None]:
    if not output:
        return "", None
    data = output.encode("utf-8", errors="replace")
    if len(data) <= OUTPUT_TRUNCATE_BYTES:
        return output, None
    truncated = data[:OUTPUT_TRUNCATE_BYTES].decode("utf-8", errors="replace")
    return truncated, "Sortie tronquee. Voir la sortie complete dans les logs."


def action_result(success: bool, message: str, output: str = "", log_path: str | None = None) -> dict:
    truncated, note = truncate_output(output)
    return {
        "success": success,
        "message": message,
        "output": truncated,
        "truncated": note is not None,
        "log_path": log_path,
        "timestamp": now_str(),
    }


def save_full_output(prefix: str, output: str) -> str:
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = os.path.join(LOG_DIR, f"{prefix}-{ts}.log")
        with open(path, "w") as f:
            f.write(output)
        return path
    except OSError:
        return ""


def require_action() -> None:
    if not config.ACTIONS_ENABLED:
        raise HTTPException(status_code=403, detail="Actions desactivees")


def require_valid_app(name: str) -> None:
    from app import security
    if not security.validate_app_name(name):
        raise HTTPException(status_code=400, detail="Nom d'application invalide")


def require_valid_container(name: str) -> None:
    from app import docker_client
    from app import security
    if not security.validate_container_name(name, docker_client.get_container_names()):
        raise HTTPException(status_code=404, detail="Container inconnu")


def validate_subdomain(value: str) -> str | None:
    if not value or not re.fullmatch(r"[a-z0-9]([a-z0-9\-]*[a-z0-9])?", value):
        return "Sous-domaine invalide (lettres minuscules, chiffres, tirets)."
    return None


def validate_port(value: str) -> str | None:
    if not value or not value.isdigit():
        return "Port invalide (nombre entier requis)."
    port = int(value)
    if port < 1 or port > 65535:
        return "Port hors plage (1-65535)."
    return None


def client_actor(request: Request) -> str:
    user = request.headers.get("x-forwarded-user") or request.headers.get("x-forwarded-email")
    if user:
        user = user.strip()[:64]
        user = "".join(c for c in user if c.isprintable())
    return user or "admin"


def client_ip(request: Request) -> str | None:
    return request.headers.get("x-forwarded-for") or request.headers.get("x-real-ip")


async def audit_log(request: Request, action: str, target: str | None = None,
                    before: Any = None, after: Any = None, job_id: str | None = None) -> None:
    from app.services import audit
    import logging
    logger = logging.getLogger("ksf-web")
    actor = client_actor(request)
    ip = client_ip(request)
    ua = request.headers.get("user-agent")
    try:
        await audit.log(actor=actor, action=action, target=target,
                        before=before, after=after, job_id=job_id, ip=ip, ua=ua)
    except Exception:
        logger.exception("Erreur audit %s/%s", action, target)


def wants_json(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    if "application/json" in accept and "text/html" not in accept:
        return True
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return True
    return False


async def run_app_action(
    app_name: str,
    action: str,
    request: Request | None = None,
    audit_action: str | None = None,
    success_msg: str | None = None,
    fail_msg: str | None = None,
    extra_args: list[str] | None = None,
) -> dict:
    """Helper pour les 6+ routes app.sh (update/restart/start/stop/disable/remove/rebuild).

    Centralise :
    - `require_action` + `require_valid_app` (gérés par l'appelant)
    - `ksf_commands.run_app_command` (async)
    - `save_full_output` (log)
    - `action_result` (réponse normalisée)
    - `audit_log` (traçabilité)
    - `invalidate_list_cache` (mutations de containers → cache TTL 3s)
    - `notifications.create` (feedback utilisateur)

    Renvoie le dict prêt à être sérialisé par FastAPI.
    """
    from app import ksf_commands
    from app.services import notifications

    ok, output = await ksf_commands.run_app_command(app_name, action, extra_args=extra_args)
    log_path = save_full_output(f"{action}-{app_name}", output) if output else ""
    msg_success = success_msg or f"{action} de {app_name} lance."
    msg_fail = fail_msg or f"Échec du {action} de {app_name}."

    # Invalide le cache de containers : les actions ci-dessus créent/détruisent
    # des containers via `docker compose up/down`. Sans invalidation, le
    # dashboard peut montrer des containers obsolètes pendant 3s.
    try:
        from app import docker_client
        docker_client.invalidate_list_cache()
    except Exception:
        pass

    # Audit
    if request is not None and audit_action:
        await audit_log(request, audit_action, app_name)

    # Notification pour l'UI (succès ou échec)
    try:
        await notifications.create(
            level="info" if ok else "error",
            category="app",
            title=f"{action} {app_name} {'réussi' if ok else 'échoué'}",
            body=output[-200:] if output else None,
        )
    except Exception:
        pass

    return action_result(ok, msg_success if ok else msg_fail, output, log_path=log_path or None)
