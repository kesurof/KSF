import asyncio
import os
import threading
import time
from pathlib import Path
from typing import Awaitable, Callable, Optional

import aiosqlite

from .config import BASE_DIR
from .security import redact_secrets

DEFAULT_DB_PATH = BASE_DIR / "data" / "webui" / "jobs.db"
BUSY_TIMEOUT_MS = 5_000


def get_db_path() -> Path:
    """Return a runtime-overridable path so tests never touch server data."""
    configured = os.environ.get("KSF_WEBUI_DB_PATH")
    return Path(configured).expanduser() if configured else DEFAULT_DB_PATH


def _host_ids() -> tuple[int, int]:
    try:
        return (
            int(os.environ.get("KSF_WEBUI_DB_UID", os.getuid())),
            int(os.environ.get("KSF_WEBUI_DB_GID", os.getgid())),
        )
    except ValueError as exc:
        raise RuntimeError("KSF_WEBUI_DB_UID et KSF_WEBUI_DB_GID doivent etre numeriques") from exc


def _secure_path(path: Path, mode: int) -> None:
    uid, gid = _host_ids()
    path.chmod(mode)
    if path.stat().st_uid != uid or path.stat().st_gid != gid:
        try:
            os.chown(path, uid, gid)
        except OSError as exc:
            raise RuntimeError(f"Impossible de definir l'ownership de {path}") from exc


def _prepare_db_path(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _secure_path(path.parent, 0o700)


async def _migration_1(db: aiosqlite.Connection) -> None:
    await db.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            target TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            message TEXT DEFAULT '',
            result TEXT DEFAULT '',
            dry_run INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL,
            finished_at REAL
        )
    """)


async def _migration_2(db: aiosqlite.Connection) -> None:
    columns = await (await db.execute("PRAGMA table_info(jobs)")).fetchall()
    if "dry_run" not in {column[1] for column in columns}:
        await db.execute("ALTER TABLE jobs ADD COLUMN dry_run INTEGER NOT NULL DEFAULT 0")


async def _migration_3(db: aiosqlite.Connection) -> None:
    # Keep the most recent active job per target before adding the SQLite lock.
    await db.execute("""
        UPDATE jobs
        SET status = 'failed', message = 'Operation remplacee par une operation plus recente',
            finished_at = COALESCE(finished_at, created_at)
        WHERE id IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY target ORDER BY created_at DESC, id DESC
                ) AS position
                FROM jobs WHERE status IN ('pending', 'running')
            ) WHERE position > 1
        )
    """)
    await db.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS jobs_one_active_target
        ON jobs(target) WHERE status IN ('pending', 'running')
    """)


# (version, destructive, migration). Destructive migrations get a SQLite backup first.
MIGRATIONS: list[tuple[int, bool, Callable[[aiosqlite.Connection], Awaitable[None]]]] = [
    (1, False, _migration_1),
    (2, False, _migration_2),
    (3, True, _migration_3),
]


async def _backup_database(db: aiosqlite.Connection, path: Path, version: int) -> Path:
    backup_path = path.with_name(f"{path.name}.v{version}.pre-migration-{time.time_ns()}.bak")
    destination = await aiosqlite.connect(str(backup_path))
    try:
        await db.backup(destination)
    finally:
        await destination.close()
    _secure_path(backup_path, 0o600)
    return backup_path


async def _apply_migrations(db: aiosqlite.Connection, path: Path) -> None:
    await db.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at REAL NOT NULL
        )
    """)
    await db.commit()
    rows = await (await db.execute("SELECT version FROM schema_migrations")).fetchall()
    applied = {row[0] for row in rows}
    for version, destructive, migration in MIGRATIONS:
        if version in applied:
            continue
        # SQLite's online backup requires no active write transaction. A second
        # process may create a redundant backup, but cannot apply this version twice.
        if destructive and path.exists() and path.stat().st_size:
            await _backup_database(db, path, version)
        try:
            await db.execute("BEGIN IMMEDIATE")
            current = await (await db.execute(
                "SELECT 1 FROM schema_migrations WHERE version = ?", (version,)
            )).fetchone()
            if current is not None:
                await db.commit()
                continue
            await migration(db)
            await db.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (version, time.time()),
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise


def _retention_days() -> int:
    try:
        days = int(os.environ.get("KSF_WEBUI_JOB_RETENTION_DAYS", "30"))
    except ValueError as exc:
        raise RuntimeError("KSF_WEBUI_JOB_RETENTION_DAYS doit etre un entier positif") from exc
    if days < 0:
        raise RuntimeError("KSF_WEBUI_JOB_RETENTION_DAYS doit etre un entier positif")
    return days


async def _get_db() -> aiosqlite.Connection:
    path = get_db_path()
    _prepare_db_path(path)
    db = await aiosqlite.connect(str(path), timeout=BUSY_TIMEOUT_MS / 1000)
    try:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        await db.execute("PRAGMA foreign_keys=ON")
        await _apply_migrations(db, path)
        integrity = await (await db.execute("PRAGMA integrity_check")).fetchone()
        if integrity is None or integrity[0] != "ok":
            raise RuntimeError(f"Verification d'integrite SQLite echouee: {integrity[0] if integrity else 'sans resultat'}")
        _secure_path(path, 0o600)
        for sidecar in (path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")):
            if sidecar.exists():
                _secure_path(sidecar, 0o600)
        return db
    except Exception:
        await db.close()
        raise


async def _prune_jobs(db: aiosqlite.Connection) -> None:
    cutoff = time.time() - (_retention_days() * 86_400)
    await db.execute(
        "DELETE FROM jobs WHERE status IN ('completed', 'failed') AND finished_at IS NOT NULL AND finished_at < ?",
        (cutoff,),
    )


def _redact_job_output(value: str, secrets: tuple[str, ...]) -> str:
    value = redact_secrets(value)
    for secret in secrets:
        if secret:
            value = value.replace(secret, "******")
    return value


def start_job(action: str, target: str, runner, dry_run: bool = False, secrets: tuple[str, ...] = ()) -> tuple[int | None, str]:
    try:
        job_id = asyncio.run(create_job(action, target, dry_run=dry_run))
    except aiosqlite.IntegrityError:
        return None, "Une operation est deja en cours pour cette cible."

    def execute():
        try:
            asyncio.run(update_job(job_id, "running", "Operation en cours"))
            code, stdout, stderr = runner()
            output = _redact_job_output((stdout + stderr).strip(), secrets)
            if code == 0:
                message = "Simulation terminee" if dry_run else "Operation terminee"
                asyncio.run(update_job(job_id, "completed", message, output))
            else:
                asyncio.run(update_job(
                    job_id, "failed", _redact_job_output(stderr or stdout or "Operation echouee", secrets), output
                ))
        except Exception as exc:
            asyncio.run(update_job(job_id, "failed", _redact_job_output(str(exc), secrets)))

    threading.Thread(target=execute, daemon=True).start()
    return job_id, ""


async def create_job(action: str, target: str, dry_run: bool = False) -> int:
    db = await _get_db()
    try:
        await _prune_jobs(db)
        cursor = await db.execute(
            "INSERT INTO jobs (action, target, status, dry_run, created_at) VALUES (?, ?, 'pending', ?, ?)",
            (action, target, int(dry_run), time.time()),
        )
        await db.commit()
        return cursor.lastrowid
    finally:
        await db.close()


async def update_job(job_id: int, status: str, message: str = "", result: str = "") -> None:
    db = await _get_db()
    try:
        finished_at = time.time() if status in ("completed", "failed") else None
        await db.execute(
            "UPDATE jobs SET status = ?, message = ?, result = ?, finished_at = ? WHERE id = ?",
            (status, redact_secrets(message), redact_secrets(result), finished_at, job_id),
        )
        await db.commit()
    finally:
        await db.close()


async def get_job(job_id: int) -> Optional[dict]:
    db = await _get_db()
    try:
        row = await (await db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))).fetchone()
        return dict(row) if row is not None else None
    finally:
        await db.close()


async def list_recent_jobs(limit: int = 20) -> list[dict]:
    db = await _get_db()
    try:
        rows = await (await db.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        )).fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()
