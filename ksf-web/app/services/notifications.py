"""Notifications in-app + dispatch vers webhooks.

Quand une notification est créée, elle est :
1. Sauvegardée en SQLite (lecture via /notifications)
2. Publiée sur le bus d'events (canal "notifications", sub-kanal = category)
3. Dispatchée aux webhooks actifs qui matchent la catégorie
"""
import json
import logging
import uuid
from datetime import datetime, timezone

from app import db
from app.services import events

logger = logging.getLogger("ksf-web.notifications")

LEVELS = frozenset({"info", "warn", "error", "critical"})


def _utcnow() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


async def create(
    level: str,
    category: str,
    title: str,
    body: str | None = None,
    link: str | None = None,
) -> str:
    if level not in LEVELS:
        raise ValueError(f"level invalide: {level}")
    nid = uuid.uuid4().hex
    now = _utcnow()
    async for conn in db.get_conn():
        await conn.execute(
            "INSERT INTO notifications (id, level, category, title, body, link, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (nid, level, category, title, body, link, now),
        )
        await conn.commit()

    payload = {"id": nid, "level": level, "category": category, "title": title, "body": body, "link": link}
    await events.bus.publish("notifications", "new", payload)
    await events.bus.publish(f"notifications:{category}", "new", payload)

    try:
        from app.services import webhooks
        await webhooks.dispatch(category, payload)
    except Exception:
        logger.exception("Erreur dispatch webhooks pour notif %s", nid)

    return nid


async def list_all(limit: int = 100, unread_only: bool = False) -> list[dict]:
    async for conn in db.get_conn():
        if unread_only:
            cur = await conn.execute(
                "SELECT * FROM notifications WHERE read_at IS NULL ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        else:
            cur = await conn.execute(
                "SELECT * FROM notifications ORDER BY created_at DESC LIMIT ?", (limit,),
            )
        rows = await cur.fetchall()
        await cur.close()
        return [dict(r) for r in rows]


async def count_unread() -> int:
    async for conn in db.get_conn():
        cur = await conn.execute("SELECT COUNT(*) as c FROM notifications WHERE read_at IS NULL")
        row = await cur.fetchone()
        await cur.close()
        return row["c"]


async def mark_read(notif_id: str) -> bool:
    async for conn in db.get_conn():
        cur = await conn.execute(
            "UPDATE notifications SET read_at=? WHERE id=? AND read_at IS NULL",
            (_utcnow(), notif_id),
        )
        await conn.commit()
        return cur.rowcount > 0


async def mark_all_read() -> int:
    async for conn in db.get_conn():
        cur = await conn.execute(
            "UPDATE notifications SET read_at=? WHERE read_at IS NULL", (_utcnow(),),
        )
        await conn.commit()
        return cur.rowcount


async def delete(notif_id: str) -> bool:
    async for conn in db.get_conn():
        cur = await conn.execute("DELETE FROM notifications WHERE id=?", (notif_id,))
        await conn.commit()
        return cur.rowcount > 0
