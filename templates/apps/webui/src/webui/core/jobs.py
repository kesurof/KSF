import asyncio
import threading
import time
import aiosqlite
from pathlib import Path
from typing import Optional

from .config import BASE_DIR

DB_PATH = BASE_DIR / "data" / "webui" / "jobs.db"
_active_targets: set[str] = set()
_active_lock = threading.Lock()


async def _get_db() -> aiosqlite.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(str(DB_PATH))
    db.row_factory = aiosqlite.Row
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
    await db.commit()
    try:
        await db.execute("ALTER TABLE jobs ADD COLUMN dry_run INTEGER NOT NULL DEFAULT 0")
        await db.commit()
    except Exception:
        pass
    try:
        DB_PATH.chmod(0o600)
    except OSError:
        pass
    return db


def start_job(action: str, target: str, runner, dry_run: bool = False, secrets: tuple[str, ...] = ()) -> tuple[int | None, str]:
    with _active_lock:
        if target in _active_targets:
            return None, "Une operation est deja en cours pour cette cible."
        _active_targets.add(target)
    job_id = asyncio.run(create_job(action, target, dry_run=dry_run))

    def execute():
        try:
            asyncio.run(update_job(job_id, "running", "Operation en cours"))
            code, stdout, stderr = runner()
            output = (stdout + stderr).strip()
            for secret in secrets:
                if secret:
                    output = output.replace(secret, "******")
            if code == 0:
                message = "Simulation terminee" if dry_run else "Operation terminee"
                asyncio.run(update_job(job_id, "completed", message, output))
            else:
                asyncio.run(update_job(job_id, "failed", stderr or stdout or "Operation echouee", output))
        except Exception as exc:
            asyncio.run(update_job(job_id, "failed", str(exc)))
        finally:
            with _active_lock:
                _active_targets.discard(target)

    threading.Thread(target=execute, daemon=True).start()
    return job_id, ""


async def create_job(action: str, target: str, dry_run: bool = False) -> int:
    db = await _get_db()
    cursor = await db.execute(
        "INSERT INTO jobs (action, target, status, dry_run, created_at) VALUES (?, ?, 'pending', ?, ?)",
        (action, target, int(dry_run), time.time())
    )
    await db.commit()
    job_id = cursor.lastrowid
    await db.close()
    return job_id


async def update_job(job_id: int, status: str, message: str = "", result: str = ""):
    db = await _get_db()
    finished_at = time.time() if status in ("completed", "failed") else None
    await db.execute(
        "UPDATE jobs SET status = ?, message = ?, result = ?, finished_at = ? WHERE id = ?",
        (status, message, result, finished_at, job_id)
    )
    await db.commit()
    await db.close()


async def get_job(job_id: int) -> Optional[dict]:
    db = await _get_db()
    cursor = await db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
    row = await cursor.fetchone()
    await db.close()
    if row is None:
        return None
    return dict(row)


async def list_recent_jobs(limit: int = 20) -> list[dict]:
    db = await _get_db()
    cursor = await db.execute(
        "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
    )
    rows = await cursor.fetchall()
    await db.close()
    return [dict(r) for r in rows]
