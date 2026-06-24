"""Webhooks : CRUD endpoints + dispatch avec HMAC + retry."""
import asyncio
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
from urllib.parse import urlparse

from app import db
from app.utils import utcnow_str as _utcnow

logger = logging.getLogger("ksf-web.webhooks")

ALLOWED_UPDATE_FIELDS = {"name", "url", "events", "secret", "enabled"}


def _is_safe_webhook_target(url: str, allow_private: bool = False) -> tuple[bool, str]:
    """Bloque les targets dangereuses (SSRF).

    - Scheme doit être http(s)
    - URL doit avoir un host et un path (au moins "/")
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
    if not parsed.netloc:
        return False, "Host manquant dans l'URL"
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
            d["secret"] = _decrypt_secret_field(d)
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
        d["secret"] = _decrypt_secret_field(d)
        return d


def _decrypt_secret_field(row: dict) -> str | None:
    """Déchiffre `secret_encrypted` s'il est présent, sinon fallback sur `secret` legacy."""
    from app import crypto
    if row.get("secret_encrypted") is not None:
        return crypto.maybe_decrypt(row["secret_encrypted"], "secret_encrypted")
    return row.get("secret")


async def create(name: str, url: str, events_list: list[str], secret: str | None = None) -> str:
    import aiosqlite
    from app import crypto
    eid = uuid.uuid4().hex
    secret_encrypted = crypto.maybe_encrypt(secret, "secret_encrypted") if secret else None
    try:
        async for conn in db.get_conn():
            await conn.execute(
                "INSERT INTO webhook_endpoints (id, name, url, secret, secret_encrypted, events, enabled, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
                (eid, name, url, None, secret_encrypted, json.dumps(events_list), _utcnow()),
            )
            await conn.commit()
    except aiosqlite.IntegrityError as e:
        raise ValueError(f"Un webhook avec le même nom/URL existe déjà") from e
    return eid


async def update(endpoint_id: str, **fields) -> bool:
    from app import crypto
    fields = {k: v for k, v in fields.items() if k in ALLOWED_UPDATE_FIELDS}
    if "events" in fields and isinstance(fields["events"], list):
        fields["events"] = json.dumps(fields["events"])
    if "enabled" in fields:
        fields["enabled"] = 1 if fields["enabled"] else 0
    # Gestion explicite du secret :
    # - "secret" non présent dans le payload → on n'y touche pas (idempotent).
    # - "clear_secret" == True → wipe explicite.
    # - "secret" est une string non-vide → chiffrement.
    # - "secret" est None ou "" sans clear_secret → IGNORÉ (sinon wipe accidentel).
    if "secret" in fields:
        secret_val = fields.pop("secret")
        if fields.pop("clear_secret", False):
            # Wipe explicite
            fields["secret_encrypted"] = None
            fields["secret"] = None
        elif isinstance(secret_val, str) and secret_val:
            # Nouvelle valeur
            fields["secret_encrypted"] = crypto.maybe_encrypt(secret_val, "secret_encrypted")
            fields["secret"] = None
        # Sinon (None ou ""), on ne touche pas à la colonne
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


async def backfill_legacy_secrets() -> int:
    """Au démarrage, chiffre les `secret` legacy (TEXT) vers `secret_encrypted` (BLOB).

    Idempotent : ne fait rien si `secret_encrypted` est déjà non-NULL.
    Renvoie le nombre de rows migrées.
    """
    from app import crypto
    n = 0
    async for conn in db.get_conn():
        cur = await conn.execute(
            "SELECT id, secret FROM webhook_endpoints "
            "WHERE secret IS NOT NULL AND secret_encrypted IS NULL"
        )
        rows = await cur.fetchall()
        await cur.close()
        for r in rows:
            encrypted = crypto.maybe_encrypt(r["secret"], "secret_encrypted")
            await conn.execute(
                "UPDATE webhook_endpoints SET secret_encrypted=?, secret=NULL WHERE id=?",
                (encrypted, r["id"]),
            )
            n += 1
        if n:
            await conn.commit()
            logger.info("Backfill: %d secret(s) webhook chiffré(s)", n)
    return n


async def dispatch(category: str, notif_payload: dict) -> int:
    """Dispatch une notification aux webhooks qui matchent la catégorie.

    Renvoie le nombre de webhooks notifiés (succès ou échec).
    Dispatch en parallèle via asyncio.gather (1 slow webhook ne bloque pas les autres).
    """
    endpoints = await list_all()
    matching = [
        ep for ep in endpoints
        if ep.get("enabled") and ("*" in ep["events"] or category in ep["events"])
    ]
    if not matching:
        return 0
    # gather avec return_exceptions pour qu'un crash d'un webhook ne crashe pas les autres
    await asyncio.gather(
        *[_send_with_retry(ep, notif_payload) for ep in matching],
        return_exceptions=True,
    )
    return len(matching)


async def _send_with_retry(ep: dict, payload: dict) -> None:
    body = json.dumps(payload, default=str, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": "ksf-web/1.0"}

    if ep.get("secret"):
        sig = hmac.new(ep["secret"].encode("utf-8"), body, hashlib.sha256).hexdigest()
        headers["X-KSF-Signature"] = f"sha256={sig}"
        headers["X-KSF-Timestamp"] = _utcnow()

    # SSRF mitigation : ré-valide l'IP cible juste avant la connexion, et
    # interdit les redirects HTTP (un attaquant pourrait 302 vers 127.0.0.1).
    # urllib.request.urlopen suit les 30x par défaut — on le court-circuite
    # via un opener custom qui lève HTTPError sur 30x.
    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise urllib.error.HTTPError(
                req.full_url, code, "Redirects disabled for SSRF protection",
                headers, fp,
            )

    safe_url = ep["url"]
    try:
        parsed = urlparse(safe_url)
        if parsed.hostname:
            # Re-résolution DNS et check IP privée (anti-rebinding + DNS-poisoning)
            infos = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
            for info in infos:
                ip_str = info[4][0]
                try:
                    ip = ipaddress.ip_address(ip_str)
                except ValueError:
                    continue
                if (ip.is_private or ip.is_loopback or ip.is_link_local
                        or ip.is_multicast or ip.is_reserved or ip.is_unspecified):
                    logger.error("Webhook %s refuse : IP privée %s pour %s",
                                 ep["name"], ip_str, parsed.hostname)
                    return
    except socket.gaierror:
        logger.warning("Webhook %s : résolution DNS impossible pour %s", ep["name"], ep["url"])

    opener = urllib.request.build_opener(_NoRedirect)

    attempts = 3
    for attempt in range(1, attempts + 1):
        try:
            req = urllib.request.Request(safe_url, data=body, headers=headers, method="POST")
            # asyncio.to_thread pour ne pas bloquer l'event loop (urllib est sync)
            resp = await asyncio.to_thread(opener.open, req, timeout=10)
            try:
                if 200 <= resp.status < 300:
                    logger.info("Webhook %s livré (status=%d)", ep["name"], resp.status)
                    return
                logger.warning("Webhook %s status=%d (attempt %d)", ep["name"], resp.status, attempt)
            finally:
                resp.close()
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
            logger.warning("Webhook %s erreur: %s (attempt %d)", ep["name"], e, attempt)
        if attempt < attempts:
            await asyncio.sleep(2 ** attempt)
    logger.error("Webhook %s échoué après %d tentatives", ep["name"], attempts)
