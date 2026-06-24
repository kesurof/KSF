"""Audit log : traçabilité des actions utilisateur et système."""
import json
import logging
from typing import Any

from app import crypto, db
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


def _serialize_payload(value: Any) -> str | None:
    """JSON serialize + truncate. Fallback sur str() si non-sérialisable."""
    if value is None:
        return None
    try:
        return _truncate(json.dumps(value, default=str))
    except (TypeError, ValueError):
        logger.warning("audit.log: sérialisation JSON échouée, fallback str()")
        return _truncate(str(value))


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
    before_s = _serialize_payload(before)
    after_s = _serialize_payload(after)
    before_enc = crypto.maybe_encrypt(before_s, "before_encrypted") if before_s else None
    after_enc = crypto.maybe_encrypt(after_s, "after_encrypted") if after_s else None

    async for conn in db.get_conn():
        cur = await conn.execute(
            "INSERT INTO audit_log (actor, action, target, before, after, "
            "before_encrypted, after_encrypted, job_id, ip, ua, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (actor, action, target, None, None,
             before_enc, after_enc, job_id, ip, ua, _utcnow()),
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
        out = []
        for r in rows:
            d = dict(r)
            d["before"] = _decrypt_field(d, "before")
            d["after"] = _decrypt_field(d, "after")
            out.append(d)
        return out


def _decrypt_field(row: dict, plain_column: str) -> str | None:
    """Déchiffre `*_encrypted` ; fallback sur la colonne legacy en clair."""
    enc_col = plain_column + "_encrypted"
    if row.get(enc_col) is not None:
        return crypto.maybe_decrypt(row[enc_col], enc_col)
    return row.get(plain_column)


async def get_entry(entry_id: int) -> dict | None:
    """Charge une entrée unique avec before/after déchiffrés (utilisé pour lazy-load)."""
    async for conn in db.get_conn():
        cur = await conn.execute("SELECT * FROM audit_log WHERE id=?", (entry_id,))
        row = await cur.fetchone()
        await cur.close()
        if not row:
            return None
        d = dict(row)
        d["before"] = _decrypt_field(d, "before")
        d["after"] = _decrypt_field(d, "after")
        return d


async def backfill_legacy_payloads() -> int:
    """Au démarrage, chiffre les `before`/`after` legacy vers `*_encrypted`.

    Idempotent : ne fait rien si la colonne chiffrée est déjà non-NULL.
    Renvoie le nombre de rows migrées.
    """
    n = 0
    async for conn in db.get_conn():
        cur = await conn.execute(
            "SELECT id, before, after FROM audit_log "
            "WHERE (before IS NOT NULL AND before_encrypted IS NULL) "
            "   OR (after IS NOT NULL AND after_encrypted IS NULL)"
        )
        rows = await cur.fetchall()
        await cur.close()
        for r in rows:
            before_enc = crypto.maybe_encrypt(r["before"], "before_encrypted") if r["before"] else None
            after_enc = crypto.maybe_encrypt(r["after"], "after_encrypted") if r["after"] else None
            await conn.execute(
                "UPDATE audit_log SET before_encrypted=?, after_encrypted=?, before=NULL, after=NULL WHERE id=?",
                (before_enc, after_enc, r["id"]),
            )
            n += 1
        if n:
            await conn.commit()
            logger.info("Backfill: %d entrée(s) audit migrée(s) vers *_encrypted", n)
    return n


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
