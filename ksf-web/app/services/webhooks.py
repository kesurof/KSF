"""Webhooks : CRUD endpoints + dispatch avec HMAC + retry."""
import hmac
import hashlib
import ipaddress
import json
import logging
import socket
import secrets
import urllib.request
import urllib.error
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

from app import db

logger = logging.getLogger("ksf-web.webhooks")

ALLOWED_UPDATE_FIELDS = {"name", "url", "events", "secret", "enabled"}


def _is_safe_webhook_target(url: str, allow_private: bool = False) -> tuple[bool, str]:
    """Bloque les targets dangereuses (SSRF).

    - Scheme doit être http(s)
    - Host doit résoudre en IP
    - IP cible ne doit pas être dans un range privé/loopback/link-local
      (sauf si allow_private=True, pour les déploiements internes intentionnels)
    """
    try:
        parsed = urlparse(url)
    except ValueError as e:
        return False, f"URL invalide : {e}"
    if parsed.scheme not in ("http", "https"):
        return False, f"Schéma non autorisé : {parsed.scheme}"
    host = parsed.hostname
    if not host:
        return False, "Host manquant"
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False, f"Host ne résout pas : {host}"
    for info in infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if not allow_private and (
            ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_multicast or ip.is_reserved or ip.is_unspecified
        ):
            return False, f"IP privée/interdite : {ip_str} ({host})"
    return True, ""


def _utcnow() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


async def list_all() -> list[dict]:
    async for conn in db.get_conn():
        cur = await conn.execute("SELECT * FROM webhook_endpoints ORDER BY created_at DESC")
        rows = await cur.fetchall()
        await cur.close()
        out = []
        for r in rows:
            d = dict(r)
            d["enabled"] = bool(d["enabled"])
            try:
                d["events"] = json.loads(d["events"])
            except (TypeError, ValueError):
                d["events"] = []
            out.append(d)
        return out


async def get(endpoint_id: str) -> dict | None:
    async for conn in db.get_conn():
        cur = await conn.execute("SELECT * FROM webhook_endpoints WHERE id=?", (endpoint_id,))
        row = await cur.fetchone()
        await cur.close()
        if not row:
            return None
        d = dict(row)
        d["enabled"] = bool(d["enabled"])
        try:
            d["events"] = json.loads(d["events"])
        except (TypeError, ValueError):
            d["events"] = []
        return d


async def create(name: str, url: str, events_list: list[str], secret: str | None = None) -> str:
    eid = uuid.uuid4().hex
    async for conn in db.get_conn():
        await conn.execute(
            "INSERT INTO webhook_endpoints (id, name, url, secret, events, enabled, created_at) "
            "VALUES (?, ?, ?, ?, ?, 1, ?)",
            (eid, name, url, secret, json.dumps(events_list), _utcnow()),
        )
        await conn.commit()
    return eid


async def update(endpoint_id: str, **fields) -> bool:
    fields = {k: v for k, v in fields.items() if k in ALLOWED_UPDATE_FIELDS}
    if "events" in fields and isinstance(fields["events"], list):
        fields["events"] = json.dumps(fields["events"])
    if "enabled" in fields:
        fields["enabled"] = 1 if fields["enabled"] else 0
    if not fields:
        return False
    cols = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [endpoint_id]
    async for conn in db.get_conn():
        cur = await conn.execute(f"UPDATE webhook_endpoints SET {cols} WHERE id=?", vals)
        await conn.commit()
        return cur.rowcount > 0


async def delete(endpoint_id: str) -> bool:
    async for conn in db.get_conn():
        cur = await conn.execute("DELETE FROM webhook_endpoints WHERE id=?", (endpoint_id,))
        await conn.commit()
        return cur.rowcount > 0


async def dispatch(category: str, notif_payload: dict) -> int:
    """Dispatch une notification aux webhooks qui matchent la catégorie.

    Renvoie le nombre de webhooks notifiés (succès ou échec)."""
    endpoints = await list_all()
    sent = 0
    for ep in endpoints:
        if not ep.get("enabled"):
            continue
        if "*" not in ep["events"] and category not in ep["events"]:
            continue
        await _send_with_retry(ep, notif_payload)
        sent += 1
    return sent


async def _send_with_retry(ep: dict, payload: dict) -> None:
    body = json.dumps(payload, default=str, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": "ksf-web/1.0"}

    if ep.get("secret"):
        sig = hmac.new(ep["secret"].encode("utf-8"), body, hashlib.sha256).hexdigest()
        headers["X-KSF-Signature"] = f"sha256={sig}"
        headers["X-KSF-Timestamp"] = _utcnow()

    attempts = 3
    for attempt in range(1, attempts + 1):
        try:
            req = urllib.request.Request(ep["url"], data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=10) as resp:
                if 200 <= resp.status < 300:
                    logger.info("Webhook %s livré (status=%d)", ep["name"], resp.status)
                    return
                logger.warning("Webhook %s status=%d (attempt %d)", ep["name"], resp.status, attempt)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
            logger.warning("Webhook %s erreur: %s (attempt %d)", ep["name"], e, attempt)
        if attempt < attempts:
            import asyncio
            await asyncio.sleep(2 ** attempt)
    logger.error("Webhook %s échoué après %d tentatives", ep["name"], attempts)
