"""Google Books API metadata source."""

import logging

import httpx
from rapidfuzz import fuzz

from app.services.metadata_sources.base import (
    REQUEST_TIMEOUT,
    AbstractMetadataSource,
    FetchResult,
    RateLimitError,
    SearchResult,
)

logger = logging.getLogger(__name__)

API_BASE = "https://www.googleapis.com/books/v1/volumes"


class GoogleBooksSource(AbstractMetadataSource):
    source_name = "google_books"

    def __init__(self, api_key: str = ""):
        self.api_key = api_key

    async def search(
        self, title: str, authors: list[str], isbn: str | None
    ) -> list[SearchResult]:
        results: list[SearchResult] = []
        params: dict[str, str | int] = {"maxResults": 5}
        if self.api_key:
            params["key"] = self.api_key

        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                # Try ISBN first
                if isbn:
                    params["q"] = f"isbn:{isbn}"
                    resp = await client.get(API_BASE, params=params)
                    if resp.status_code == 429:
                        raise RateLimitError("google_books")
                    if resp.status_code == 200:
                        data = resp.json()
                        for item in data.get("items", []):
                            vi = item.get("volumeInfo", {})
                            results.append(
                                SearchResult(
                                    url=item["id"],
                                    title=vi.get("title", ""),
                                    authors=vi.get("authors", []),
                                    score=100.0,
                                )
                            )
                    if results:
                        return results[:3]

                # Fallback: title + author
                first_author = authors[0] if authors else ""
                q_parts = []
                if title:
                    q_parts.append(f"intitle:{title}")
                if first_author:
                    q_parts.append(f"inauthor:{first_author}")
                if not q_parts:
                    return []

                params["q"] = " ".join(q_parts)
                resp = await client.get(API_BASE, params=params)
                if resp.status_code == 429:
                    raise RateLimitError("google_books")
                if resp.status_code != 200:
                    return []

                data = resp.json()
                for item in data.get("items", []):
                    vi = item.get("volumeInfo", {})
                    item_title = vi.get("title", "")
                    score = fuzz.token_sort_ratio(title.lower(), item_title.lower())
                    results.append(
                        SearchResult(
                            url=item["id"],
                            title=item_title,
                            authors=vi.get("authors", []),
                            score=score,
                        )
                    )
                results.sort(key=lambda r: r.score, reverse=True)
        except RateLimitError:
            raise
        except Exception as e:
            logger.warning(f"Google Books search failed: {e}")

        return results[:3]

    async def fetch(self, url: str) -> FetchResult:
        """Fetch volume details. `url` is the volume ID."""
        volume_id = url
        params: dict[str, str] = {}
        if self.api_key:
            params["key"] = self.api_key

        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                resp = await client.get(f"{API_BASE}/{volume_id}", params=params)
                if resp.status_code == 429:
                    raise RateLimitError("google_books")
                if resp.status_code != 200:
                    return FetchResult(source_url=volume_id)

                data = resp.json()
                vi = data.get("volumeInfo", {})

                rating = vi.get("averageRating")
                rating_count = vi.get("ratingsCount")

                # Extract categories (hierarchical strings like "Fiction / Science Fiction")
                categories = vi.get("categories", [])
                main_category = vi.get("mainCategory")

                raw_data = {
                    "categories": categories,
                    "mainCategory": main_category,
                    "description": vi.get("description"),
                    "pageCount": vi.get("pageCount"),
                    "language": vi.get("language"),
                    "publishedDate": vi.get("publishedDate"),
                    "industryIdentifiers": vi.get("industryIdentifiers", []),
                }

                return FetchResult(
                    source_url=volume_id,
                    rating=float(rating) if rating else None,
                    rating_count=int(rating_count) if rating_count else None,
                    raw_data=raw_data,
                )
        except RateLimitError:
            raise
        except Exception as e:
            logger.warning(f"Google Books fetch failed for {volume_id}: {e}")
            return FetchResult(source_url=volume_id)
