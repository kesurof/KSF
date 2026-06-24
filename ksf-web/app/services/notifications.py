"""Notifications : insert simple + dispatch fire-and-forget aux webhooks.

Architecture simplifiée (post-Item 7 du plan de simplification) :
- La table `notifications` reste, sert d'audit pour les webhooks dispatchés
- Plus de dédup (colonne `dedup_key` + `repeat_count` + index retirés en migration 007)
- Plus d'UI in-app (page /notifications + badge sidebar retirés)
- Gardé : INSERT simple, publish event, dispatch webhooks fire-and-forget
"""
import asyncio
import logging
import uuid

from app import db
from app.utils import utcnow_str as _utcnow

logger = logging.getLogger("ksf-web.notifications")

LEVELS = frozenset({"info", "warn", "error", "critical"})


async def create(
    level: str,
    category: str,
    title: str,
    body: str | None = None,
    link: str | None = None,
) -> str:
    """Insère une notification et dispatche les webhooks en fire-and-forget.

    Renvoie l'ID de la notification créée. Le dispatch webhook est async
    et ne bloque pas l'appelant (3 retries × 10s par endpoint).
    """
    if level not in LEVELS:
        raise ValueError(f"level invalide: {level}")
    now = _utcnow()
    nid = uuid.uuid4().hex

    async for conn in db.get_conn():
        await conn.execute(
            "INSERT INTO notifications (id, level, category, title, body, link, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (nid, level, category, title, body, link, now),
        )
        await conn.commit()
        break  # on a la connexion, on sort du async for

    payload = {"id": nid, "level": level, "category": category,
               "title": title, "body": body, "link": link}

    # Dispatch webhooks en fire-and-forget : on ne bloque pas l'appelant
    # sur la latence des webhooks (3 retries × 10s = 30s par endpoint).
    # Le callback d'erreur capture les exceptions asyncio silencieuses.
    try:
        from app.services import webhooks
        task = asyncio.create_task(webhooks.dispatch(category, payload))
        task.add_done_callback(_log_webhook_dispatch_result)
    except RuntimeError:
        # Si pas de loop active (rare), dispatch sync comme fallback
        try:
            await webhooks.dispatch(category, payload)
        except Exception:
            logger.exception("Erreur dispatch webhooks pour notif %s", nid)
    except Exception:
        logger.exception("Erreur scheduling dispatch webhooks pour notif %s", nid)

    return nid


def _log_webhook_dispatch_result(task: asyncio.Task) -> None:
    """Callback fire-and-forget : log les exceptions silencieuses."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc:
        logger.exception("Erreur fire-and-forget dispatch webhooks: %s", exc)
