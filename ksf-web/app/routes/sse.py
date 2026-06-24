"""Blueprints SSE (streaming EventSource)."""
import asyncio
import threading

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.helpers import require_valid_container
from app.services import events, jobs

router = APIRouter()


# ── Job streaming (output subprocess en direct) ────────────

@router.get("/jobs/{job_id}/stream")
async def job_stream(job_id: str, request: Request):
    job = await jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job introuvable")
    last_event_id = int(request.headers.get("last-event-id", "0") or "0")

    async def event_gen():
        yield events.sse_format("snapshot", {
            "id": job["id"], "kind": job["kind"], "status": job["status"],
            "output_size": job.get("output_size") or 0,
        }, event_id=str(last_event_id))
        seen = last_event_id
        async for payload in events.bus.subscribe(f"jobs:{job_id}"):
            if await request.is_disconnected():
                return
            if payload["event"] == "line":
                line_n = payload["data"].get("n", 0)
                if line_n <= seen:
                    continue
                seen = line_n
                yield events.sse_format("line", payload["data"], event_id=str(seen))
            elif payload["event"] == "finished":
                yield events.sse_format("finished", payload["data"], event_id=str(seen))
                return

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ── Container logs streaming ───────────────────────────────

@router.get("/containers/{container_id}/logs/stream")
async def container_logs_stream(container_id: str, request: Request):
    require_valid_container(container_id)
    from app import docker_client

    async def event_gen():
        loop = asyncio.get_event_loop()
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        stop = threading.Event()

        def _reader():
            try:
                for line in docker_client.stream_container_logs(container_id, tail=100, stop_event=stop):
                    loop.call_soon_threadsafe(q.put_nowait, line)
            except Exception:
                pass
            finally:
                loop.call_soon_threadsafe(q.put_nowait, None)

        reader = threading.Thread(target=_reader, daemon=True)
        reader.start()
        yield events.sse_format("start", {"container": container_id})
        try:
            while True:
                if await request.is_disconnected():
                    stop.set()
                    return
                line = await q.get()
                if line is None:
                    yield events.sse_format("end", {})
                    return
                yield events.sse_format("line", {"text": line})
        finally:
            stop.set()

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
