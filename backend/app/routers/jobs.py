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
    get_active_run_id,
    start_job_run,
    stop_job_run,
)

router = APIRouter(prefix="/api/admin/jobs", tags=["jobs"])


class JobStatusOut(BaseModel):
    key: str
    label: str
    description: str
    total: int
    missing: int
    blocked: int
    active: bool
    requires_ai: bool


class AllJobsResponse(BaseModel):
    jobs: list[JobStatusOut]


@router.get("", response_model=AllJobsResponse)
async def get_jobs_status(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get status of all job types with missing counts."""
    jobs = []
    for key, job_type in JOB_TYPES.items():
        total, missing, blocked = await count_missing_books(db, key)
        run_id = await get_active_run_id(key)

        jobs.append(
            JobStatusOut(
                key=key,
                label=job_type.label,
                description=job_type.description,
                total=total,
                missing=missing,
                blocked=blocked,
                active=run_id is not None,
                requires_ai=job_type.requires_ai,
            )
        )

    return AllJobsResponse(jobs=jobs)


@router.post("/{job_type}", status_code=status.HTTP_202_ACCEPTED)
async def trigger_job(
    job_type: str,
    _admin: Annotated[User, Depends(require_admin)],
):
    """Trigger a bulk job that dispatches per-book tasks for all missing books."""
    if job_type not in JOB_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown job type: {job_type}",
        )

    # Start a new run (overwrites any previous run_id, effectively stopping it)
    run_id = await start_job_run(job_type)

    from app.tasks.bulk_jobs import run_bulk_job

    run_bulk_job.delay(job_type, run_id)
    return {"status": "accepted", "job_type": job_type}


@router.delete("/{job_type}", status_code=status.HTTP_200_OK)
async def stop_job(
    job_type: str,
    _admin: Annotated[User, Depends(require_admin)],
):
    """Stop a running bulk job by clearing its run_id."""
    if job_type not in JOB_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown job type: {job_type}",
        )

    was_active = await stop_job_run(job_type)
    if not was_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Job '{job_type}' is not running",
        )

    return {"status": "stopped", "job_type": job_type}
