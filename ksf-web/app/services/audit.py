"""Audit log : traçabilité des actions utilisateur et système."""
import json
import logging
from typing import Any

from app import db
from app.utils import utcnow_str as _utcnow

logger = logging.getLogger("ksf-web.audit")

# Cap la taille des before/after pour éviter qu'un payload géant (dump
# complet d'un ksf.env, par ex) n'explose la DB. Tronqué avec un marqueur.
_MAX_BEFORE_AFTER_BYTES = 8192


def _truncate(s: str | None) -> str | None:
    if s is None:
        return None
    if len(s) <= _MAX_BEFORE_AFTER_BYTES:
        return s
    return s[:_MAX_BEFORE_AFTER_BYTES] + f"... [truncated, original {len(s)} bytes]"


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
        before_s = _truncate(json.dumps(before, default=str) if before is not None else None)
        after_s = _truncate(json.dumps(after, default=str) if after is not None else None)
    except (TypeError, ValueError):
        # Fallback: str() peut produire un output enorme, on truncate
        before_s = _truncate(str(before) if before is not None else None)
        after_s = _truncate(str(after) if after is not None else None)
        logger.warning("audit.log: sérialisation JSON échouée pour %s/%s, fallback str()", action, target)

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
