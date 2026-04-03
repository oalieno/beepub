"""Hardcover API (GraphQL) metadata source."""

import logging

import httpx
from rapidfuzz import fuzz

from app.services.metadata_sources.base import (
    AbstractMetadataSource,
    FetchResult,
    RateLimitError,
    SearchResult,
)

logger = logging.getLogger(__name__)

API_URL = "https://api.hardcover.app/v1/graphql"

# Simple search query — results come back as JSON in `results` field
# containing hits[].document with all book data (genres, moods, tags, etc.)
SEARCH_QUERY = """
query Search($query: String!) {
  search(query: $query, query_type: "Book", per_page: 5) {
    results
  }
}
"""


class HardcoverSource(AbstractMetadataSource):
    source_name = "hardcover"

    def __init__(self, api_token: str = ""):
        self.api_token = api_token.strip()

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_token:
            token = self.api_token
            if token.lower().startswith("bearer "):
                headers["Authorization"] = token
            else:
                headers["Authorization"] = f"Bearer {token}"
        return headers

    async def search(
        self, title: str, authors: list[str], isbn: str | None
    ) -> list[SearchResult]:
        if not self.api_token:
            return []

        results: list[SearchResult] = []
        first_author = authors[0] if authors else ""
        query = f"{title} {first_author}".strip()
        if not query:
            return []

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    API_URL,
                    headers=self._headers(),
                    json={"query": SEARCH_QUERY, "variables": {"query": query}},
                )
                if resp.status_code == 429:
                    raise RateLimitError("hardcover")
                if resp.status_code != 200:
                    logger.warning(
                        "Hardcover search returned %d: %s",
                        resp.status_code,
                        resp.text[:200],
                    )
                    return []

                data = resp.json()
                search_data = data.get("data", {}).get("search", {}).get("results", {})
                hits = search_data.get("hits", [])

                for hit in hits:
                    doc = hit.get("document", {})
                    item_title = doc.get("title", "")
                    slug = doc.get("slug", "")
                    if not slug:
                        continue

                    item_authors = doc.get("author_names", [])
                    # Check title + alternative_titles for best match
                    # Use token_sort_ratio (penalizes length mismatch) instead of
                    # token_set_ratio (which matches "56" to "56 天還你濃密頭髮")
                    all_titles = [item_title] + (doc.get("alternative_titles") or [])
                    score = max(
                        fuzz.token_sort_ratio(title.lower(), t.lower())
                        for t in all_titles
                        if t
                    )

                    # Build FetchResult directly from search data
                    rating = doc.get("rating")
                    ratings_count = doc.get("ratings_count")
                    prefetched = FetchResult(
                        source_url=slug,
                        rating=float(rating) if rating else None,
                        rating_count=int(ratings_count) if ratings_count else None,
                        raw_data={
                            "genres": doc.get("genres") or [],
                            "moods": doc.get("moods") or [],
                            "tags": doc.get("tags") or [],
                            "content_warnings": doc.get("content_warnings") or [],
                            "description": doc.get("description"),
                            "pages": doc.get("pages"),
                            "release_date": doc.get("release_date"),
                            "users_read_count": doc.get("users_read_count"),
                            "slug": slug,
                        },
                    )

                    results.append(
                        SearchResult(
                            url=slug,
                            title=item_title,
                            authors=item_authors,
                            score=score,
                            prefetched=prefetched,
                        )
                    )

                results.sort(key=lambda r: r.score, reverse=True)
        except RateLimitError:
            raise
        except Exception as e:
            logger.warning("Hardcover search failed: %s", e)

        return results[:3]

    async def fetch(self, url: str) -> FetchResult:
        """Fetch book details by re-searching. Used for pinned URLs only.

        `url` is a slug (e.g., 'children-of-memory') or numeric ID.
        """
        if not self.api_token:
            return FetchResult(source_url=url)

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    API_URL,
                    headers=self._headers(),
                    json={
                        "query": SEARCH_QUERY,
                        "variables": {"query": url.replace("-", " ")},
                    },
                )
                if resp.status_code == 429:
                    raise RateLimitError("hardcover")
                if resp.status_code != 200:
                    return FetchResult(source_url=url)

                data = resp.json()
                hits = (
                    data.get("data", {})
                    .get("search", {})
                    .get("results", {})
                    .get("hits", [])
                )

                # Find matching book by slug or use first result
                doc = None
                for hit in hits:
                    d = hit.get("document", {})
                    if d.get("slug") == url:
                        doc = d
                        break
                if not doc and hits:
                    doc = hits[0].get("document", {})
                if not doc:
                    return FetchResult(source_url=url)

                rating = doc.get("rating")
                ratings_count = doc.get("ratings_count")
                slug = doc.get("slug", url)

                return FetchResult(
                    source_url=slug,
                    rating=float(rating) if rating else None,
                    rating_count=int(ratings_count) if ratings_count else None,
                    raw_data={
                        "genres": doc.get("genres") or [],
                        "moods": doc.get("moods") or [],
                        "tags": doc.get("tags") or [],
                        "content_warnings": doc.get("content_warnings") or [],
                        "description": doc.get("description"),
                        "pages": doc.get("pages"),
                        "release_date": doc.get("release_date"),
                        "users_read_count": doc.get("users_read_count"),
                        "slug": slug,
                    },
                )
        except RateLimitError:
            raise
        except Exception as e:
            logger.warning("Hardcover fetch failed for %s: %s", url, e)
            return FetchResult(source_url=url)
