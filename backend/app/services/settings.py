from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import AppSetting
from app.plugins.metadata import registry as metadata_registry

_STATIC_DEFAULTS = {
    "registration_enabled": "false",
    "timezone": "Asia/Taipei",
    "calibre_base_dir": "/calibre",
    "calibre_auto_sync_interval_minutes": "30",
    # Provider credentials (stored once)
    "gemini_api_key": "",
    "openai_api_key": "",
    "openai_base_url": "",
    # Per-feature config
    "companion_provider": "",
    "companion_model": "",
    "tag_provider": "",
    "tag_model": "",
    "image_provider": "",
    "image_model": "",
    # Embedding config (shared by semantic search + companion RAG)
    "embedding_provider": "",
    "embedding_model": "",
    "embedding_api_url": "",
    "embedding_api_key": "",
    # Similar books — semantic similarity blend
    "similar_books_semantic_weight": "10.0",
    "similar_books_semantic_limit": "50",
    # Background metadata job: which sources it fetches
    # (comma-separated plugin names; empty = all enabled)
    metadata_registry.JOB_SOURCES_KEY: "",
}

# Metadata plugins contribute their own keys (one enabled-toggle each,
# plus declared credentials like google_books_api_key) — a drop-in
# plugin needs no edit here.
DEFAULTS = {**_STATIC_DEFAULTS, **metadata_registry.plugin_setting_defaults()}


# Settings whose values are credentials. The admin GET endpoint masks
# these; a masked value submitted back on PUT means "unchanged".
SECRET_SETTINGS = {
    "gemini_api_key",
    "openai_api_key",
    "embedding_api_key",
} | metadata_registry.plugin_secret_keys()

MASK_PREFIX = "****"


def mask_secret(value: str) -> str:
    if not value:
        return ""
    return MASK_PREFIX + value[-4:]


def mask_secrets(settings: dict[str, str]) -> dict[str, str]:
    return {
        key: mask_secret(value) if key in SECRET_SETTINGS else value
        for key, value in settings.items()
    }


def is_masked(value: str) -> bool:
    return value.startswith(MASK_PREFIX)


async def get_setting(db: AsyncSession, key: str) -> str:
    result = await db.execute(select(AppSetting).where(AppSetting.key == key))
    setting = result.scalar_one_or_none()
    if setting:
        return setting.value
    return DEFAULTS.get(key, "")


async def get_all_settings(db: AsyncSession) -> dict[str, str]:
    result = await db.execute(select(AppSetting))
    settings = {row.key: row.value for row in result.scalars().all()}
    # Fill in defaults for any missing keys
    for key, default in DEFAULTS.items():
        if key not in settings:
            settings[key] = default
    return settings


async def update_settings(db: AsyncSession, updates: dict[str, str]) -> dict[str, str]:
    for key, value in updates.items():
        if key not in DEFAULTS:
            continue
        result = await db.execute(select(AppSetting).where(AppSetting.key == key))
        setting = result.scalar_one_or_none()
        if setting:
            setting.value = value
        else:
            db.add(AppSetting(key=key, value=value))
    await db.commit()
    return await get_all_settings(db)
