from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from ..core.jobs import get_job, list_recent_jobs
from ..templates import templates

router = APIRouter()


@router.get("")
async def jobs_list():
    jobs = await list_recent_jobs()
    return {"jobs": jobs}


@router.get("/html", response_class=HTMLResponse)
async def jobs_html(request: Request):
    jobs = await list_recent_jobs()
    return templates.TemplateResponse(request, "_jobs_table.html", {"jobs": jobs})


@router.get("/{job_id}")
async def job_status(job_id: int):
    job = await get_job(job_id)
    if job is None:
        return JSONResponse({"error": "Job not found"}, status_code=404)
    return job