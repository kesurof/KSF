"""Job queue : subprocess long-running commands with persistent state.

Modèle :
- Un job = un subprocess qui exécute ksf.sh / app.sh (ou n'importe quelle commande).
- État persistant en SQLite (survit au restart du conteneur).
- Un seul job à la fois (single-user, c'est suffisant et évite les conflits).
- Lock optionnel par clé (ex: 'app:radarr' pour opérations exclusives sur une app).
- Output capturé dans un fichier logrotaté, lu en streaming via SSE.
- Recovery au démarrage : les jobs 'running' dont le PID n'existe plus sont marqués 'interrupted'.
"""
import asyncio
import json
import logging
import os
import secrets
import signal
import subprocess
import time
import uuid
from typing import Any

import aiosqlite

from app import config, db
from app.services import events
from app.utils import utcnow_str as _utcnow

logger = logging.getLogger("ksf-web.jobs")

# Marqueur posé par cancel() dans le champ "error" du job pour signaler
# au worker qu'il doit terminer en "cancelled" plutôt qu'en success/failed.
# C'est moche mais permet d'éviter une colonne DB supplémentaire.
CANCEL_MARKER = "(cancelled by user)"

JOB_KINDS = frozenset({
    "backup.create",
    "backup.verify",
    "backup.restore",
    "backup.prune",
    "system.update",
    "system.doctor",
    "system.restart",
    "system.update_service",
    "system.clean_data",
    "app.install",
    "app.update",
    "app.rebuild",
    "app.remove",
    "config.update",
    "ksf.trusted_ips_apply",
    "ksf.appsec_toggle",
    "ksf.crowdsec_ban",
    "ksf.crowdsec_unban",
    "ksf.crowdsec_flush",
    "ksf.crowdsec_restart",
})

ALLOWED_COMMANDS: dict[str, list[str]] = {
    "ksf.sh": [config.REPO_DIR + "/ksf.sh"],
    "app.sh": [config.REPO_DIR + "/app.sh"],
}


def _new_id() -> str:
    return uuid.uuid4().hex


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


# ── DB access helpers ───────────────────────────────────────────

async def _row_to_job(row: aiosqlite.Row) -> dict[str, Any]:
    d = dict(row)
    if d.get("args"):
        try:
            d["args"] = json.loads(d["args"])
        except (TypeError, ValueError):
            d["args"] = None
    return d


async def get(job_id: str) -> dict | None:
    async for conn in db.get_conn():
        cur = await conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,))
        row = await cur.fetchone()
        await cur.close()
        if not row:
            return None
        return await _row_to_job(row)


async def list_recent(limit: int = 50, status: str | None = None) -> list[dict]:
    async for conn in db.get_conn():
        if status:
            cur = await conn.execute(
                "SELECT * FROM jobs WHERE status=? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            )
        else:
            cur = await conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            )
        rows = await cur.fetchall()
        await cur.close()
        return [await _row_to_job(r) for r in rows]


async def _update(job_id: str, **fields: Any) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [job_id]
    async for conn in db.get_conn():
        await conn.execute(f"UPDATE jobs SET {cols} WHERE id=?", vals)
        await conn.commit()


# ── Public API : enqueue / cancel ───────────────────────────────

async def enqueue(
    kind: str,
    command: list[str],
    args: list[str] | None = None,
    lock_key: str | None = None,
    triggered_by: str = "admin",
) -> dict:
    if kind not in JOB_KINDS:
        raise ValueError(f"Job kind inconnu : {kind}")
    if not command:
        raise ValueError("command requise")
    job_id = _new_id()
    now = _utcnow()
    async for conn in db.get_conn():
        await conn.execute(
            "INSERT INTO jobs (id, kind, command, args, status, lock_key, created_at, triggered_by) "
            "VALUES (?, ?, ?, ?, 'queued', ?, ?, ?)",
            (job_id, kind, json.dumps(command), json.dumps(args or []), lock_key, now, triggered_by),
        )
        await conn.commit()
    await events.bus.publish("jobs", "enqueued", {"id": job_id, "kind": kind, "lock_key": lock_key})
    logger.info("Job enqueued id=%s kind=%s lock=%s", job_id, kind, lock_key)
    return await get(job_id)


async def cancel(job_id: str) -> bool:
    job = await get(job_id)
    if not job:
        return False
    if job["status"] not in ("queued", "running"):
        return False
    if job["status"] == "running" and job.get("pid"):
        try:
            os.killpg(os.getpgid(job["pid"]), signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass
    # On flag l'annulation ; c'est le worker qui marquera "cancelled" quand il détecte
    # la fin du subprocess, pour éviter une race avec _update final du worker.
    await _update(job_id, error=CANCEL_MARKER)
    await events.bus.publish("jobs", "cancel-requested", {"id": job_id})
    return True


# ── Worker loop ──────────────────────────────────────────────────

_worker_task: asyncio.Task | None = None


async def start_worker() -> None:
    global _worker_task
    if _worker_task is not None and not _worker_task.done():
        return
    await recover_interrupted()
    _worker_task = asyncio.create_task(_worker_loop(), name="jobs-worker")


async def stop_worker() -> None:
    global _worker_task
    if _worker_task is None:
        return
    _worker_task.cancel()
    try:
        await _worker_task
    except (asyncio.CancelledError, Exception):
        pass
    _worker_task = None


async def recover_interrupted() -> int:
    """Marque 'interrupted' les jobs 'running' dont le PID n'existe plus."""
    recovered = 0
    async for conn in db.get_conn():
        cur = await conn.execute("SELECT id, pid FROM jobs WHERE status='running'")
        rows = await cur.fetchall()
        await cur.close()
        dead_ids = []
        for row in rows:
            pid = row["pid"]
            if pid and not _pid_alive(pid):
                dead_ids.append(row["id"])
        if not dead_ids:
            return 0
        now = _utcnow()
        await conn.execute(
            "UPDATE jobs SET status='interrupted', finished_at=?, "
            "  error='Process terminé de manière inattendue (recovery au démarrage)' "
            "WHERE id IN ("
            + ",".join("?" * len(dead_ids)) +
            ")",
            [now, *dead_ids],
        )
        await conn.commit()
        recovered = len(dead_ids)
        for jid in dead_ids:
            await events.bus.publish("jobs", "interrupted", {"id": jid})
            logger.warning("Job %s marqué interrupted (PID mort)", jid)
    return recovered


async def _next_queued() -> dict | None:
    """Trouve le prochain job 'queued' qui n'est pas bloqué par un lock.

    Itère sur TOUS les jobs queued (par ordre de création) et retourne le
    premier dont le lock_key n'est pas tenu par un running. Sans cette
    itération, un seul job queued avec un lock tenu bloque tous les jobs
    queued plus récents qui ont un lock libre.
    """
    async for conn in db.get_conn():
        cur = await conn.execute(
            "SELECT * FROM jobs WHERE status='queued' ORDER BY created_at ASC"
        )
        rows = await cur.fetchall()
        await cur.close()
        for row in rows:
            job = await _row_to_job(row)
            # Vérifier si annulé pendant qu'il était en queue (status=queued
            # mais error=CANCEL_MARKER posé par cancel())
            if job.get("error") == CANCEL_MARKER:
                await _update(job["id"], status="cancelled", finished_at=_utcnow(),
                              error=None)
                await events.bus.publish("jobs", "cancelled", {"id": job["id"]})
                continue
            if job.get("lock_key"):
                cur = await conn.execute(
                    "SELECT COUNT(*) as c FROM jobs WHERE status='running' AND lock_key=?",
                    (job["lock_key"],),
                )
                r = await cur.fetchone()
                await cur.close()
                if r["c"] > 0:
                    continue  # Lock tenu, essayer le suivant
            return job
        return None


async def _worker_loop() -> None:
    logger.info("Job worker démarré")
    while True:
        try:
            job = await _next_queued()
            if job is None:
                await asyncio.sleep(1.0)
                continue
            await _run_job(job)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Erreur dans le worker loop")
            await asyncio.sleep(2.0)


async def _run_job(job: dict) -> None:
    job_id = job["id"]
    command = json.loads(job["command"])
    os.makedirs(config.JOB_LOG_DIR, exist_ok=True)
    log_path = os.path.join(config.JOB_LOG_DIR, f"{job_id}.log")

    await _update(job_id, status="running", started_at=_utcnow(), output_path=log_path)
    await events.bus.publish("jobs", "started", {"id": job_id, "kind": job["kind"]})

    env = os.environ.copy()
    env["KSF_BASE_DIR"] = config.BASE_DIR
    env["KSF_REPO_DIR"] = config.REPO_DIR
    env["HOME"] = "/home/appuser"
    env["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

    try:
        with open(log_path, "ab", buffering=0) as logf:
            proc = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=config.REPO_DIR,
                env=env,
                start_new_session=True,
            )
            await _update(job_id, pid=proc.pid)

            # Compteur de lignes partagé entre stdout et stderr pour unicité
            # des numéros de ligne côté front. Verrou car asyncio.gather exécute
            # les 2 streams en parallèle.
            counter_lock = asyncio.Lock()
            counter = {"n": 0}

            async def read_stream(stream, prefix: str):
                buf = b""
                while True:
                    chunk = await stream.read(4096)
                    if not chunk:
                        break
                    logf.write(chunk)
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        async with counter_lock:
                            counter["n"] += 1
                            n = counter["n"]
                        text = line.decode("utf-8", errors="replace")
                        if prefix:
                            text = prefix + text
                        await events.bus.publish(
                            f"jobs:{job_id}", "line",
                            {"n": n, "text": text, "stream": "stderr" if prefix else "stdout"},
                        )
                if buf:
                    async with counter_lock:
                        counter["n"] += 1
                        n = counter["n"]
                    logf.write(b"\n")
                    text = buf.decode("utf-8", errors="replace")
                    if prefix:
                        text = prefix + text
                    await events.bus.publish(
                        f"jobs:{job_id}", "line",
                        {"n": n, "text": text, "stream": "stderr" if prefix else "stdout"},
                    )

            # Lecture parallèle de stdout et stderr avec préfixe pour stderr
            await asyncio.gather(
                read_stream(proc.stdout, ""),
                read_stream(proc.stderr, "[stderr] "),
            )

            await proc.wait()

        size = os.path.getsize(log_path)
        # Si l'utilisateur a demandé l'annulation, on termine en 'cancelled' quel que soit
        # le code retour (le proc a été tué par SIGTERM → exit -15).
        if job.get("error") == CANCEL_MARKER:
            new_status = "cancelled"
            await _update(
                job_id, status=new_status, exit_code=proc.returncode,
                output_size=size, pid=None, finished_at=_utcnow(), error=None,
            )
        else:
            new_status = "success" if proc.returncode == 0 else "failed"
            await _update(
                job_id, status=new_status, exit_code=proc.returncode,
                output_size=size, pid=None, finished_at=_utcnow(),
            )
        await events.bus.publish("jobs", "finished", {
            "id": job_id, "status": new_status, "exit_code": proc.returncode, "size": size,
        })
        logger.info("Job %s terminé status=%s exit=%s", job_id, new_status, proc.returncode)

        try:
            from app.services import notifications
            kind = job["kind"]
            category = kind.split(".")[0] if "." in kind else "system"
            level = "info" if new_status == "success" else "error"
            await notifications.create(
                level=level, category=category,
                title=f"{kind} {'réussi' if new_status == 'success' else 'échoué'}",
                body=f"Job {job_id[:8]} terminé en exit {proc.returncode}.",
                link=f"/jobs/{job_id}",
            )
        except Exception:
            logger.exception("Erreur création notification pour job %s", job_id)
    except Exception as e:
        logger.exception("Erreur d'exécution du job %s", job_id)
        await _update(
            job_id, status="failed", error=f"{type(e).__name__}: {e}",
            finished_at=_utcnow(),
        )
        await events.bus.publish("jobs", "failed", {"id": job_id, "error": str(e)})
        try:
            from app.services import notifications
            await notifications.create(
                level="error", category="system",
                title=f"Erreur d'exécution du job {job['kind']}",
                body=str(e), link=f"/jobs/{job_id}",
            )
        except Exception:
            pass


# ── Log streaming helpers ───────────────────────────────────────

async def stream_log(job_id: str, since_event_id: int = 0) -> tuple[str, int, int]:
    """Renvoie (log_path, current_size, last_event_id). Lit depuis le fichier."""
    job = await get(job_id)
    if not job or not job.get("output_path"):
        return "", 0, since_event_id
    path = job["output_path"]
    try:
        size = os.path.getsize(path)
    except OSError:
        return path, 0, since_event_id
    return path, size, since_event_id
