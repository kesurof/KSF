"""SQLite async connection + migration runner.

L'instance de connexion est globale (aiosqlite). Toutes les requêtes
passent par `get_conn()` qui yield une connexion par requête.
"""
import os
import re
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


# Regex pour identifier les ALTER TABLE ADD COLUMN (non idempotent en SQLite < 3.35).
# On les parse pour checker PRAGMA table_info avant exécution, ce qui rend la
# migration robuste aux crashs entre executescript() et INSERT dans _migrations.
_ALTER_ADD_COL_RE = re.compile(
    r"ALTER\s+TABLE\s+(\w+)\s+ADD\s+COLUMN\s+(\w+)",
    re.IGNORECASE,
)


def _filter_already_applied_alter(stmts: list[str], existing_columns: dict[str, set[str]]) -> list[str]:
    """Filtre les `ALTER TABLE ADD COLUMN` pour les colonnes déjà présentes.

    Rend la migration idempotente même si le process a été tué entre
    executescript() et INSERT dans _migrations : au redémarrage, les
    colonnes déjà ajoutées sont sautées, l'INSERT dans _migrations réussit.
    """
    out = []
    for stmt in stmts:
        m = _ALTER_ADD_COL_RE.search(stmt)
        if m and m.group(2) in existing_columns.get(m.group(1), set()):
            logger.info("Skip ALTER (colonne déjà présente): %s", stmt.strip()[:80])
            continue
        out.append(stmt)
    return out


def _split_statements(sql: str) -> list[str]:
    """Split un script SQL en statements individuels (sur `;`).

    Approche simple : on découpe sur `;` en ligne, on filtre les commentaires
    `--` et les lignes vides. Ne gère pas les strings SQL contenant `;` (cas
    rare dans nos migrations, pas critique).
    """
    statements = []
    for raw in sql.split(";"):
        # Enlève les commentaires de ligne et lignes vides
        lines = []
        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("--"):
                continue
            lines.append(line)
        cleaned = "\n".join(lines).strip()
        if cleaned:
            statements.append(cleaned)
    return statements


async def _get_existing_columns(db: aiosqlite.Connection) -> dict[str, set[str]]:
    """Renvoie {table_name: {col_name, ...}} pour les tables qui existent."""
    result: dict[str, set[str]] = {}
    cur = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )
    tables = [r[0] async for r in cur]
    await cur.close()
    for t in tables:
        if t.startswith("sqlite_"):
            continue
        cur = await db.execute(f"PRAGMA table_info({t})")
        cols = {r[1] async for r in cur}
        await cur.close()
        result[t] = cols
    return result


async def _ensure_schema() -> None:
    """Initialise la table _migrations et applique les migrations manquantes.

    Robustesse :
    - `CREATE TABLE IF NOT EXISTS` est naturellement idempotent.
    - `CREATE INDEX IF NOT EXISTS` est naturellement idempotent.
    - `ALTER TABLE ADD COLUMN` est filtré via PRAGMA table_info() pour être
      idempotent (le runner de migration peut être tué entre executescript et
      l'INSERT dans _migrations sans bloquer le redémarrage suivant).
    """
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
                stmts = _split_statements(sql)
                existing_cols = await _get_existing_columns(db)
                filtered = _filter_already_applied_alter(stmts, existing_cols)
                for stmt in filtered:
                    await db.execute(stmt)
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
