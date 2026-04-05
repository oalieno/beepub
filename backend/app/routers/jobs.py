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
    get_active_count,
    start_job,
    stop_job,
)

BLOCKED_LABELS: dict[str, str] = {
    "embedding": "Needs Text",
    "summarize": "Needs Text",
    "book_embedding": "Needs Summary",
}

router = APIRouter(prefix="/api/admin/jobs", tags=["jobs"])


class JobStatusOut(BaseModel):
    key: str
    label: str
    description: str
    total: int
    missing: int
    blocked: int
    blocked_label: str
    active: int
    requires_ai: bool


class AllJobsResponse(BaseModel):
    jobs: list[JobStatusOut]
    image_book_count: int = 0


@router.get("", response_model=AllJobsResponse)
async def get_jobs_status(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get status of all job types with missing counts and active task counts."""
    from sqlalchemy import func, select

    from app.models.book import Book

    img_result = await db.execute(
        select(func.count(Book.id)).where(Book.is_image_book.is_(True))
    )
    image_book_count = img_result.scalar() or 0

    jobs = []
    for key, job_type in JOB_TYPES.items():
        total, missing, blocked = await count_missing_books(db, key)
        active = await get_active_count(key)

        jobs.append(
            JobStatusOut(
                key=key,
                label=job_type.label,
                description=job_type.description,
                total=total,
                missing=missing,
                blocked=blocked,
                blocked_label=BLOCKED_LABELS.get(key, "Needs Text"),
                active=active,
                requires_ai=job_type.requires_ai,
            )
        )

    return AllJobsResponse(jobs=jobs, image_book_count=image_book_count)


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

    generation = await start_job(job_type)

    from app.tasks.bulk_jobs import run_bulk_job

    run_bulk_job.delay(job_type, generation)
    return {"status": "accepted", "job_type": job_type}


@router.delete("/{job_type}", status_code=status.HTTP_200_OK)
async def stop_job_endpoint(
    job_type: str,
    _admin: Annotated[User, Depends(require_admin)],
):
    """Stop a running bulk job by incrementing the generation."""
    if job_type not in JOB_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown job type: {job_type}",
        )

    generation = await stop_job(job_type)
    return {"status": "stopped", "job_type": job_type, "generation": generation}
