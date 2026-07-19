from fastapi import APIRouter
from fastapi.responses import JSONResponse
from ..core.jobs import get_job, list_recent_jobs

router = APIRouter()


@router.get("")
async def jobs_list():
    jobs = await list_recent_jobs()
    return {"jobs": jobs}


@router.get("/{job_id}")
async def job_status(job_id: int):
    job = await get_job(job_id)
    if job is None:
        return JSONResponse({"error": "Job not found"}, status_code=404)
    return job
