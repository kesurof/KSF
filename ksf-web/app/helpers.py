"""Helpers extraits de main.py : validation, formatage, audit, normalisation.

Aucun handler n'est défini ici, uniquement des fonctions utilitaires utilisées
par les blueprints `app/routes/`.
"""
import asyncio
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, Request

from app import config
from app.logging_config import get_correlation_id


LOG_DIR = config.ACTIONS_LOG_DIR
OUTPUT_TRUNCATE_BYTES = config.OUTPUT_TRUNCATE_BYTES

logger = logging.getLogger("ksf-web.actions")


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
    """Écrit la sortie brute dans ${ACTIONS_LOG_DIR}/<prefix>-<ts>.log.

    Conservé pour les chemins qui n'utilisent pas TeeSubprocess (ex: action
    synchrone d'un script auxiliaire). Les actions principales passent par
    `run_app_action` qui utilise TeeSubprocess.
    """
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = os.path.join(LOG_DIR, f"{prefix}-{ts}.log")
        with open(path, "w") as f:
            f.write(output)
        return path
    except OSError:
        return ""


async def _tee_subprocess_with_log(cmd: list[str], log_path: str,
                                   extra: dict | None = None) -> tuple[bool, str]:
    """Lance un subprocess via TeeSubprocess, log structuré, retourne (ok, output).

    Lit le fichier brut en fin de run pour l'inclure dans la réponse JSON
    (compatibilité avec l'UI qui attend `output`).
    """
    from app.logging_config import TeeSubprocess
    output = ""
    try:
        async with TeeSubprocess(cmd, log_path,
                                 logger_name="ksf-web.actions",
                                 cwd=config.REPO_DIR,
                                 env=os.environ.copy(),
                                 extra=extra) as tee:
            assert tee.process is not None
            await tee.process.wait()
        ok = (tee.exit_code == 0)
        try:
            with open(log_path, "r", errors="replace") as f:
                output = f.read()
        except OSError:
            output = ""
        return ok, output
    except FileNotFoundError:
        return False, f"Script introuvable : {cmd[0]}"
    except Exception as e:
        logger.exception("Erreur lancement subprocess %s", cmd)
        return False, f"Erreur interne : {type(e).__name__}: {e}"


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
    actor = client_actor(request)
    ip = client_ip(request)
    ua = request.headers.get("user-agent")
    cid = get_correlation_id()
    try:
        await audit.log(actor=actor, action=action, target=target,
                        before=before, after=after, job_id=job_id,
                        ip=ip, ua=ua, correlation_id=cid)
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
    - `ksf_commands.run_app_command` (async via TeeSubprocess)
    - `action_result` (réponse normalisée)
    - `audit_log` (traçabilité)
    - `invalidate_list_cache` (mutations de containers → cache TTL 3s)
    - `notifications.create` (feedback utilisateur)
    - événements structurés `app.action.start` / `app.action.end` dans le log JSONL

    Renvoie le dict prêt à être sérialisé par FastAPI.
    """
    from app import ksf_commands
    from app.services import notifications

    # Pré-calcul du log_path (timestamp UTC compact) — on le donne à
    # run_app_command pour qu'il écrive le fichier brut et le log structuré
    # au même endroit.
    started = time.monotonic()
    cid = get_correlation_id()
    logger.info(
        "app.action.start",
        extra={"action": action, "target": app_name, "action_args": extra_args or []},
    )

    ok, output, log_path = await ksf_commands.run_app_command(
        app_name, action, extra_args=extra_args, correlation_id=cid
    )

    duration_ms = int((time.monotonic() - started) * 1000)
    logger.info(
        "app.action.end",
        extra={
            "action": action,
            "target": app_name,
            "ok": ok,
            "duration_ms": duration_ms,
            "exit_code": 0 if ok else 1,
            "output_size": len(output.encode("utf-8", errors="replace")) if output else 0,
            "log_path": log_path or None,
        },
    )

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
