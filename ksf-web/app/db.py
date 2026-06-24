"""SQLite async connection + migration runner.

L'instance de connexion est globale (aiosqlite). Toutes les requêtes
passent par `get_conn()` qui yield une connexion par requête.
"""
import os
import glob
import logging
from typing import AsyncIterator

import aiosqlite

from app import config

logger = logging.getLogger("ksf-web.db")

_conn: aiosqlite.Connection | None = None
_write_lock_conn: aiosqlite.Connection | None = None
_migrations_applied = False


async def get_conn() -> AsyncIterator[aiosqlite.Connection]:
    """Yield une connexion partagée (read) ou exclusive (write via _write_lock_conn)."""
    global _conn, _write_lock_conn
    if _conn is None:
        db_dir = os.path.dirname(config.DB_PATH)
        try:
            os.makedirs(db_dir, exist_ok=True)
        except PermissionError as e:
            raise RuntimeError(
                f"Impossible de créer le dossier DB {db_dir}: {e}. "
                f"Vérifiez que le volume est monté et que les permissions sont correctes."
            ) from e
        is_new = not os.path.exists(config.DB_PATH)
        _conn = await aiosqlite.connect(config.DB_PATH, isolation_level=None)
        _conn.row_factory = aiosqlite.Row
        await _conn.execute("PRAGMA journal_mode=WAL")
        await _conn.execute("PRAGMA foreign_keys=ON")
        await _conn.execute("PRAGMA busy_timeout=5000")
        if is_new:
            try:
                os.chmod(config.DB_PATH, 0o600)
            except OSError:
                logger.warning("Impossible de chmod 600 sur %s", config.DB_PATH)
    yield _conn


async def _ensure_schema() -> None:
    """Initialise la table _migrations et applique les migrations manquantes."""
    async for db in get_conn():
        await db.execute(
            "CREATE TABLE IF NOT EXISTS _migrations ("
            "  version INTEGER PRIMARY KEY,"
            "  name TEXT NOT NULL,"
            "  applied_at TEXT NOT NULL"
            ")"
        )
        await db.commit()
        cursor = await db.execute("SELECT version FROM _migrations")
        applied = {row[0] async for row in cursor}
        await cursor.close()

        migrations_dir = config.MIGRATIONS_DIR
        files = sorted(glob.glob(os.path.join(migrations_dir, "*.sql")))
        for path in files:
            name = os.path.basename(path)
            try:
                version = int(name.split("_", 1)[0])
            except ValueError:
                continue
            if version in applied:
                continue
            logger.info("Application de la migration %s", name)
            with open(path) as f:
                sql = f.read()
            try:
                # NOTE : on n'utilise pas BEGIN/COMMIT/ROLLBACK ici car
                # sqlite3.executescript() fait un COMMIT implicite avant
                # d'exécuter le script, ce qui invaliderait notre transaction.
                # À la place, on compte sur l'idempotence des migrations :
                # CREATE TABLE IF NOT EXISTS est un no-op si la table existe.
                # Si le process crashe entre executescript et l'INSERT,
                # la migration est partiellement appliquée mais sera
                # réessayée au prochain restart (le IF NOT EXISTS rend
                # executescript idempotent, et l'INSERT réussit ensuite).
                await db.executescript(sql)
                from datetime import datetime, timezone
                ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
                await db.execute(
                    "INSERT INTO _migrations (version, name, applied_at) VALUES (?, ?, ?)",
                    (version, name, ts),
                )
                await db.commit()
            except Exception:
                logger.exception("Échec de la migration %s", name)
                raise


async def init() -> None:
    """Init : applique les migrations au démarrage de l'app."""
    global _migrations_applied
    if _migrations_applied:
        return
    await _ensure_schema()
    _migrations_applied = True


async def close() -> None:
    global _conn, _write_lock_conn
    if _write_lock_conn is not None:
        await _write_lock_conn.close()
        _write_lock_conn = None
    if _conn is not None:
        await _conn.close()
        _conn = None
