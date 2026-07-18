"""Interactive fan-out orchestration over the plugin registry."""

import asyncio
import logging

from app.plugins.metadata import registry
from app.plugins.metadata.base import (
    REQUEST_TIMEOUT,
    BookQuery,
    BookRecord,
    Clue,
    MetadataPlugin,
    RateLimitError,
)

logger = logging.getLogger(__name__)


async def lookup_isbn_all(
    isbn: str, settings: dict[str, str]
) -> list[tuple[str, BookRecord]]:
    """Resolve an ISBN on every enabled plugin that can locate by ISBN
    and yields bibliographic data or covers (ratings-only sources are
    skipped — nothing to prefill from them).

    Runs concurrently with a per-plugin timeout. Returns (plugin_name,
    record) pairs in registry order; rate-limited, failed, and empty
    sources are simply absent."""
    plugins = [
        p
        for p in registry.enabled_plugins(settings, have={Clue.ISBN})
        if {"title", "cover_url"} & p.provides
    ]

    async def resolve_one(plugin: MetadataPlugin) -> tuple[str, BookRecord | None]:
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT + 5):
                return plugin.name, await plugin.resolve(BookQuery(isbn=isbn))
        except RateLimitError:
            logger.warning(f"{plugin.name} rate limited during ISBN lookup")
        except Exception as e:
            logger.warning(f"{plugin.name} ISBN lookup failed: {e}")
        return plugin.name, None

    resolved = await asyncio.gather(*(resolve_one(p) for p in plugins))
    return [(name, record) for name, record in resolved if record is not None]
