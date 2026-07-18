"""Metadata source registry endpoint — one server-side truth for every
frontend surface that needs to know which plugins exist, what they can
do, and whether they're enabled."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models.user import User
from app.plugins.metadata import registry
from app.plugins.metadata.base import RECORD_FIELD_ORDER
from app.schemas.metadata import MetadataSourceOut, MetadataSourcesOut
from app.services.settings import get_all_settings

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
                url_prefix=cls.url_prefix,
                id_pattern=cls.id_pattern,
                id_hint=cls.id_hint,
            )
        )
    return MetadataSourcesOut(sources=sources)
