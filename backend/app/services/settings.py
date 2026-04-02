from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import AppSetting

DEFAULTS = {
    "registration_enabled": "false",
    "timezone": "Asia/Taipei",
    "metadata_refresh_enabled": "true",
    "metadata_refresh_hour": "3",
    "metadata_refresh_interval_days": "7",
    "metadata_refresh_cooldown_days": "30",
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
    # External metadata API keys
    "google_books_api_key": "",
    "hardcover_api_token": "",
}


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
