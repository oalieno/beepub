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
    count_all_job_stats,
    get_pending_counts,
    reset_pending,
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
    pending: int
    requires_ai: bool
    # metadata_backfill only: ETA of the announced rate-limit
    # continuation (ISO), if one is armed.
    resume_at: str | None = None


class AllJobsResponse(BaseModel):
    jobs: list[JobStatusOut]
    image_book_count: int = 0


@router.get("", response_model=AllJobsResponse)
async def get_jobs_status(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get status of all job types with missing counts and active task counts."""
    keys = list(JOB_TYPES.keys())

    # One conditional-aggregation query for all counts, one Redis MGET for
    # all pending counters — instead of ~11 sequential count(*) scans plus
    # a fresh Redis connection per job type.
    stats = await count_all_job_stats(db)
    pending_by_key = await get_pending_counts(keys)

    # Reconcile: pending counters are generation-scoped, which removes the
    # stale-run desyncs, but an orchestrator crash mid-dispatch can still
    # leave the current run's counter high. The DB flags are authoritative —
    # if nothing is left to process, a nonzero counter is stale and would
    # show a running job forever.
    for key in keys:
        missing, blocked = stats.counts[key]
        if pending_by_key[key] > 0 and missing == 0 and blocked == 0:
            await reset_pending(key)
            pending_by_key[key] = 0

    resume_at = await _get_resume_at()

    jobs = []
    for key in keys:
        job_type = JOB_TYPES[key]
        missing, blocked = stats.counts[key]
        jobs.append(
            JobStatusOut(
                key=key,
                label=job_type.label,
                description=job_type.description,
                total=stats.total,
                missing=missing,
                blocked=blocked,
                blocked_label=BLOCKED_LABELS.get(key, "Needs Text"),
                pending=pending_by_key[key],
                requires_ai=job_type.requires_ai,
                resume_at=resume_at if key == "metadata_backfill" else None,
            )
        )

    return AllJobsResponse(jobs=jobs, image_book_count=stats.image_book_count)


async def _get_resume_at() -> str | None:
    import redis.asyncio as aioredis

    from app.config import settings as app_config
    from app.tasks.metadata import RESUME_KEY

    client = aioredis.from_url(app_config.redis_url, decode_responses=True)
    try:
        return await client.get(RESUME_KEY)
    except Exception:
        return None
    finally:
        await client.aclose()


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


@router.delete("/metadata_backfill/resume", status_code=status.HTTP_200_OK)
async def cancel_backfill_resume(
    _admin: Annotated[User, Depends(require_admin)],
):
    """Cancel the announced rate-limit continuation. The scheduled task's
    atomic DELETE claim comes back empty and it no-ops."""
    import redis.asyncio as aioredis

    from app.config import settings as app_config
    from app.tasks.metadata import RESUME_KEY

    client = aioredis.from_url(app_config.redis_url)
    try:
        cancelled = await client.delete(RESUME_KEY)
    finally:
        await client.aclose()
    return {"status": "cancelled" if cancelled else "not_scheduled"}
