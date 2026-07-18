"""Interactive fan-out orchestration over the plugin registry.

Stays free of app.* infrastructure: callers inject a `resolver` (e.g.
the framework's cached resolve) — the default is a plain live resolve.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

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

Resolver = Callable[[MetadataPlugin, BookQuery], Awaitable[BookRecord | None]]


async def _plain_resolve(plugin: MetadataPlugin, query: BookQuery) -> BookRecord | None:
    return await plugin.resolve(query)


async def lookup_all(
    query: BookQuery,
    settings: dict[str, str],
    *,
    resolver: Resolver | None = None,
) -> list[tuple[str, BookRecord]]:
    """Resolve the clues on every enabled plugin that can locate with
    them and yields bibliographic data or covers (ratings-only sources
    are skipped — nothing to prefill from them).

    A `url` clue is different: pasted URLs belong to exactly one source,
    so they dispatch to the plugin whose url_prefix matches instead of
    fanning out (handing a foreign URL to every plugin would have each
    one scraping a page it can't parse).

    Runs concurrently with a per-plugin timeout. Returns (plugin_name,
    record) pairs in registry order; rate-limited, failed, and empty
    sources are simply absent."""
    resolve = resolver or _plain_resolve

    if query.url:
        plugins = [
            cls(settings)
            for cls in registry.all_plugins()
            if cls.url_prefix
            and query.url.startswith(cls.url_prefix)
            and registry.is_enabled(cls, settings)
        ]
    else:
        have = set()
        if query.isbn:
            have.add(Clue.ISBN)
        if query.title:
            have.add(Clue.TITLE)
        plugins = [
            p
            for p in registry.enabled_plugins(settings, have=have)
            if {"title", "cover_url"} & p.provides
        ]

    async def resolve_one(plugin: MetadataPlugin) -> tuple[str, BookRecord | None]:
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT + 5):
                return plugin.name, await resolve(plugin, query)
        except RateLimitError:
            logger.warning(f"{plugin.name} rate limited during metadata lookup")
        except Exception as e:
            logger.warning(f"{plugin.name} metadata lookup failed: {e}")
        return plugin.name, None

    resolved = await asyncio.gather(*(resolve_one(p) for p in plugins))
    return [(name, record) for name, record in resolved if record is not None]
