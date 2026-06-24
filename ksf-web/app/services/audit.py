"""Audit log : traçabilité des actions utilisateur et système."""
import json
import logging
from datetime import datetime, timezone
from typing import Any

from app import db

logger = logging.getLogger("ksf-web.audit")


def _utcnow() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


async def log(
    actor: str,
    action: str,
    target: str | None = None,
    before: Any = None,
    after: Any = None,
    job_id: str | None = None,
    ip: str | None = None,
    ua: str | None = None,
) -> int:
    try:
        before_s = json.dumps(before, default=str) if before is not None else None
        after_s = json.dumps(after, default=str) if after is not None else None
    except (TypeError, ValueError):
        before_s, after_s = str(before), str(after)

    async for conn in db.get_conn():
        cur = await conn.execute(
            "INSERT INTO audit_log (actor, action, target, before, after, job_id, ip, ua, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (actor, action, target, before_s, after_s, job_id, ip, ua, _utcnow()),
        )
        await conn.commit()
        return cur.lastrowid


async def list_entries(
    limit: int = 100,
    action: str | None = None,
    target: str | None = None,
    actor: str | None = None,
) -> list[dict]:
    query = "SELECT * FROM audit_log"
    params: list = []
    where = []
    if action:
        where.append("action = ?"); params.append(action)
    if target:
        where.append("target = ?"); params.append(target)
    if actor:
        where.append("actor = ?"); params.append(actor)
    if where:
        query += " WHERE " + " AND ".join(where)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    async for conn in db.get_conn():
        cur = await conn.execute(query, params)
        rows = await cur.fetchall()
        await cur.close()
        return [dict(r) for r in rows]


def export_json(entries: list[dict]) -> str:
    return json.dumps(entries, indent=2, default=str, ensure_ascii=False)


def export_csv(entries: list[dict]) -> str:
    import csv, io
    buf = io.StringIO()
    fields = ["id", "created_at", "actor", "action", "target", "ip", "ua", "job_id", "before", "after"]
    w = csv.DictWriter(buf, fieldnames=fields)
    w.writeheader()
    for e in entries:
        row = {f: e.get(f, "") for f in fields}
        w.writerow(row)
    return buf.getvalue()
