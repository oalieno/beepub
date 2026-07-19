"""Plugin template — copy me, don't import me.

Copy this file to `<your_source>.py` (no leading underscore: the
registry skips `_`-prefixed modules, which is why this template can
live here without being loaded), fill in the declarations and the two
hooks, restart the backend. Everything else — settings whitelist, admin
UI, background job, lookups, SSRF allowlist — follows automatically.

The two-sided contract:

- What the framework CALLS: `resolve()` and `candidates()`, both
  inherited from the base. Nothing outside a plugin ever calls
  `_search`/`_fetch` — the leading underscore means "implement, don't
  call": calling them directly would bypass the confidence floor, the
  prefetched short-circuit, and the resolve cache.
- What a plugin IMPLEMENTS: the `_search`/`_fetch` hooks below, if the
  source fits the common "search, pick the best hit, parse its book
  page" shape. If it doesn't (single-shot ISBN lookup, multi-step
  crawl), skip the hooks and override `resolve()` directly — see
  books_tw.py and open_library.py.

Import rule (enforced by tests): only `app.plugins.metadata.base` plus
stdlib/httpx/bs4/rapidfuzz. Config arrives as `self.settings` (a plain
dict) at construction — never read settings at import time.
"""

import logging

from app.plugins.metadata.base import (
    BookQuery,
    BookRecord,
    Clue,
    MetadataPlugin,
    RateLimitError,
    SearchCandidate,
)

logger = logging.getLogger(__name__)


class ExamplePlugin(MetadataPlugin):
    # ── Declarations: each line below grows something automatically ──
    name = "example"  # settings toggle / Redis key / external_metadata.source
    label = "Example Books"  # display string (proper noun, not translated)
    kind = "api"  # "api" | "scraper" — display only
    locale = None  # e.g. "zh-TW" — display only
    accepts = frozenset({Clue.ISBN, Clue.TITLE, Clue.URL})  # what locates a book
    provides = frozenset({"title", "authors", "cover_url"})  # BookRecord fields
    cover_hosts = frozenset({"covers.example.com"})  # joins the SSRF allowlist
    settings_keys = ("example_api_key",)  # admin UI renders inputs for these
    secret_settings_keys = ("example_api_key",)  # masked on read
    ratelimit_cooldown = 300  # seconds paused after a 429 (framework enforces)
    # All three together ⇔ Clue.URL in accepts: manual linking + pick refs.
    url_prefix = "https://example.com/books/"
    id_pattern = r"^\d+$"
    id_hint = "e.g. 12345"

    # ── Hooks consumed by the default resolve()/candidates() ──
    async def _search(self, query: BookQuery) -> list[SearchCandidate]:
        """Return raw search hits. Mark ISBN-located hits exact=True
        (they win outright); attach prefetched=BookRecord(...) when the
        search response already carried the full document (skips the
        _fetch round-trip). Don't score or filter by similarity — the
        base does the judging, and candidates() shows your hits to the
        user unjudged."""
        hits: list[SearchCandidate] = []
        try:
            async with self._client() as client:
                resp = await client.get(
                    "https://api.example.com/search",
                    params={"q": query.isbn or query.title},
                )
                if resp.status_code != 200:
                    return []
                for item in resp.json()["results"]:
                    hits.append(
                        SearchCandidate(
                            url=item["id"],  # whatever _fetch understands
                            title=item["title"],
                            authors=item.get("authors", []),
                            exact=bool(query.isbn),
                        )
                    )
        except RateLimitError:
            raise  # always re-raise — the framework handles cooldowns
        except Exception as e:
            logger.warning(f"Example search failed: {e}")
        return hits

    async def _fetch(self, url: str) -> BookRecord:
        """Parse one book. `url` is a value this plugin produced earlier
        (a candidate ref, a stored source_url) or admin-entered — accept
        bare IDs and full URLs alike. Fill every field you can parse,
        raw as the source states it; partial records are fine. More than
        one request is fine too (google_books chains two)."""
        book_id = url.removeprefix(self.url_prefix)
        try:
            async with self._client() as client:
                resp = await client.get(f"https://api.example.com/books/{book_id}")
                if resp.status_code != 200:
                    return BookRecord(source_url=url)
                data = resp.json()
                return BookRecord(
                    source_url=url,
                    title=data.get("title"),
                    authors=data.get("authors", []),
                    cover_url=data.get("cover"),
                )
        except RateLimitError:
            raise
        except Exception as e:
            logger.warning(f"Example fetch failed for {url}: {e}")
            return BookRecord(source_url=url)
