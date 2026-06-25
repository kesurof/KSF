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
import signal
import subprocess
import time
import uuid
from typing import Any

import aiosqlite

from app import config, db
from app.services import events
from app.types import JobRecord
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

async def _row_to_job(row: aiosqlite.Row) -> JobRecord:
    d: JobRecord = dict(row)
    if d.get("args"):
        try:
            d["args"] = json.loads(d["args"])
        except (TypeError, ValueError):
            d["args"] = None
    return d


async def get(job_id: str) -> JobRecord | None:
    async for conn in db.get_conn():
        cur = await conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,))
        row = await cur.fetchone()
        await cur.close()
        if not row:
            return None
        return await _row_to_job(row)


async def list_recent(
    limit: int = 50,
    status: str | None = None,
    before: str | None = None,
) -> list[JobRecord]:
    """Liste les jobs récents, ordre DESC par created_at puis id.

    `before` (string ISO 8601) permet la pagination cursor-based : on
    ne récupère que les jobs strictement plus anciens. `before` est le
    `created_at` du dernier job de la page précédente.

    Note : `id` est un UUID TEXT donc inutilisable pour un cursor
    ordonné. `created_at` (ISO 8601 string) compare correctement avec
    `<` en DESC pour des timestamps au même format.
    """
    where = []
    params: list = []
    if status:
        where.append("status = ?")
        params.append(status)
    if before is not None:
        where.append("created_at < ?")
        params.append(before)
    query = "SELECT * FROM jobs"
    if where:
        query += " WHERE " + " AND ".join(where)
    query += " ORDER BY created_at DESC, id DESC LIMIT ?"
    params.append(limit)
    async for conn in db.get_conn():
        cur = await conn.execute(query, params)
        rows = await cur.fetchall()
        await cur.close()
        return [await _row_to_job(r) for r in rows]
    return []


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
) -> JobRecord:
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

            # Lecture ligne par ligne de chaque stream. Chaque stream a son
            # propre compteur (le front distingue stdout/stderr via le champ
            # `stream`, pas via un n° de ligne unique). Préfixe "[stderr] "
            # pour les lignes stderr.
            line_count = {"stdout": 0, "stderr": 0}

            async def read_stream(stream, stream_name: str, prefix: str):
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    logf.write(line)
                    line_count[stream_name] += 1
                    text = line.decode("utf-8", errors="replace").rstrip("\n")
                    if prefix:
                        text = prefix + text
                    await events.bus.publish(
                        f"jobs:{job_id}", "line",
                        {"n": line_count[stream_name], "text": text, "stream": stream_name},
                    )

            # Lecture parallèle de stdout et stderr.
            await asyncio.gather(
                read_stream(proc.stdout, "stdout", ""),
                read_stream(proc.stderr, "stderr", "[stderr] "),
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
