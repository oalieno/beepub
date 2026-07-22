"""Metadata source registry endpoint — one server-side truth for every
frontend surface that needs to know which plugins exist, what they can
do, and whether they're enabled."""

from typing import Annotated

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings as app_config
from app.database import get_db
from app.deps import get_current_user, require_admin
from app.models.user import User
from app.plugins.metadata import registry
from app.plugins.metadata.base import RECORD_FIELD_ORDER
from app.schemas.metadata import (
    MetadataSourceOut,
    MetadataSourcesOut,
    MetadataSourceStats,
    MetadataSourceStatsOut,
)
from app.services.metadata_fetch import HEALTH_KEY_PREFIX
from app.services.settings import get_all_settings
from app.tasks.metadata import RATELIMIT_KEY_PREFIX

router = APIRouter(prefix="/api/metadata", tags=["metadata"])

_CLUE_ORDER = ("isbn", "title", "url")


@router.get("/sources", response_model=MetadataSourcesOut)
async def list_metadata_sources(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    app_settings = await get_all_settings(db)
    job_names = {p.name for p in registry.job_plugins(app_settings)}

    sources = []
    for cls in registry.all_plugins():
        configured = all(app_settings.get(key) for key in cls.settings_keys)
        sources.append(
            MetadataSourceOut(
                name=cls.name,
                label=cls.label,
                kind=cls.kind,
                locale=cls.locale,
                accepts=[c for c in _CLUE_ORDER if c in cls.accepts],
                provides=[f for f in RECORD_FIELD_ORDER if f in cls.provides],
                enabled=registry.is_enabled(cls, app_settings),
                in_job=cls.name in job_names,
                configured=configured,
                setting_keys=list(cls.settings_keys),
                secret_setting_keys=list(cls.secret_settings_keys),
                key_url=cls.key_url,
                url_prefix=cls.url_prefix,
                id_pattern=cls.id_pattern,
                id_hint=cls.id_hint,
            )
        )
    return MetadataSourcesOut(sources=sources)


@router.get("/sources/stats", response_model=MetadataSourceStatsOut)
async def metadata_source_stats(
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Operational health per source, for /admin/metadata: archive
    tallies (found vs empty markers — a marker row is exactly one with
    a NULL record), Redis health hash, and rate-limit cooldown."""
    result = await db.execute(
        text("""
            SELECT source,
                   COUNT(*) FILTER (WHERE record IS NOT NULL) AS books_found,
                   COUNT(*) FILTER (WHERE record IS NULL) AS books_not_found,
                   MAX(fetched_at) AS last_fetched_at
            FROM external_metadata
            GROUP BY source
        """)
    )
    stats: dict[str, MetadataSourceStats] = {}
    for row in result.mappings():
        stats[row["source"]] = MetadataSourceStats(
            books_found=row["books_found"],
            books_not_found=row["books_not_found"],
            last_fetched_at=(
                row["last_fetched_at"].isoformat() if row["last_fetched_at"] else None
            ),
        )

    client = aioredis.from_url(app_config.redis_url, decode_responses=True)
    try:
        for cls in registry.all_plugins():
            entry = stats.setdefault(cls.name, MetadataSourceStats())
            health = await client.hgetall(f"{HEALTH_KEY_PREFIX}:{cls.name}")
            if health:
                entry.last_success_at = health.get("last_success_at")
                entry.last_error_at = health.get("last_error_at")
                entry.last_error = health.get("last_error")
                entry.last_ratelimited_at = health.get("last_ratelimited_at")
                entry.consecutive_failures = int(
                    health.get("consecutive_failures") or 0
                )
            ttl = await client.ttl(f"{RATELIMIT_KEY_PREFIX}:{cls.name}")
            if ttl > 0:
                entry.cooldown_seconds = ttl
    except Exception:
        # Redis being down degrades stats to the DB tallies, never a 500.
        pass
    finally:
        await client.aclose()

    return MetadataSourceStatsOut(stats=stats)
