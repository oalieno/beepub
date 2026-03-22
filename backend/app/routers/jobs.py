"""Admin job queue API — status monitoring and bulk task triggers."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import require_admin
from app.models.user import User
from app.services.job_queue import (
    JOB_TYPES,
    count_missing_books,
    get_all_job_statuses,
    get_job_status,
    set_job_status,
)

router = APIRouter(prefix="/api/admin/jobs", tags=["jobs"])


class JobStatusOut(BaseModel):
    key: str
    label: str
    description: str
    total: int
    missing: int
    active: bool
    progress: dict | None  # {status, total, processed, failed} or None


class AllJobsResponse(BaseModel):
    jobs: list[JobStatusOut]


class TriggerRequest(BaseModel):
    mode: str = "missing"  # "all" or "missing"


@router.get("", response_model=AllJobsResponse)
async def get_jobs_status(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get status of all job types with missing counts."""
    statuses = await get_all_job_statuses()

    jobs = []
    for key, job_type in JOB_TYPES.items():
        total, missing = await count_missing_books(db, key)
        progress = statuses.get(key)
        active = progress is not None and progress.get("status") == "running"

        jobs.append(
            JobStatusOut(
                key=key,
                label=job_type.label,
                description=job_type.description,
                total=total,
                missing=missing,
                active=active,
                progress=progress,
            )
        )

    return AllJobsResponse(jobs=jobs)


@router.post("/{job_type}", status_code=status.HTTP_202_ACCEPTED)
async def trigger_job(
    job_type: str,
    body: TriggerRequest,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Trigger a bulk job. Mode: 'all' reprocesses everything, 'missing' only unprocessed."""
    if job_type not in JOB_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown job type: {job_type}",
        )

    # Check if already running
    current = await get_job_status(job_type)
    if current and current.get("status") == "running":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Job '{job_type}' is already running",
        )

    from app.tasks.bulk_jobs import run_bulk_job

    run_bulk_job.delay(job_type, body.mode)
    return {"status": "accepted", "job_type": job_type, "mode": body.mode}


@router.delete("/{job_type}", status_code=status.HTTP_200_OK)
async def stop_job(
    job_type: str,
    _admin: Annotated[User, Depends(require_admin)],
):
    """Stop a running bulk job by setting its status to cancelled."""
    if job_type not in JOB_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown job type: {job_type}",
        )

    current = await get_job_status(job_type)
    if not current or current.get("status") != "running":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Job '{job_type}' is not running",
        )

    await set_job_status(
        job_type,
        status="cancelled",
        total=current.get("total", 0),
        processed=current.get("processed", 0),
        failed=current.get("failed", 0),
    )
    return {"status": "cancelled", "job_type": job_type}
