"""Hardcover plugin — GraphQL API; ratings plus genre/mood/tag data.

The search response already carries the whole document, so candidates
ship a prefetched record and the default resolve() skips _fetch. The
URL path is a real books(where: slug) lookup — slugs for CJK titles
are year+UUID (no title words), so a slug can never be turned back
into a search query."""

import logging

from rapidfuzz import fuzz

from app.plugins.metadata.base import (
    BookQuery,
    BookRecord,
    Clue,
    MetadataPlugin,
    RateLimitError,
    SearchCandidate,
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

BOOK_QUERY = """
query BookBySlug($slug: String!) {
  books(where: {slug: {_eq: $slug}}, limit: 1) {
    slug
    title
    description
    release_date
    rating
    ratings_count
    users_read_count
    cached_tags
    image { url }
    contributions { author { name } }
  }
}
"""


class HardcoverPlugin(MetadataPlugin):
    name = "hardcover"
    label = "Hardcover"
    kind = "api"
    accepts = frozenset({Clue.TITLE, Clue.URL})
    provides = frozenset(
        {
            "title",
            "authors",
            "description",
            "published_date",
            "cover_url",
            "rating",
            "rating_count",
            "readers_count",
            "tags",
        }
    )
    cover_hosts = frozenset({"assets.hardcover.app"})
    settings_keys = ("hardcover_api_token",)
    secret_settings_keys = ("hardcover_api_token",)
    key_url = "https://hardcover.app/account/api"
    ratelimit_cooldown = 60
    url_prefix = "https://hardcover.app/books/"
    id_pattern = r"^[\w-]+$"
    id_hint = "e.g. the-left-hand-of-darkness"

    def _token(self) -> str:
        return self.settings.get("hardcover_api_token", "").strip()

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        token = self._token()
        if token:
            if token.lower().startswith("bearer "):
                headers["Authorization"] = token
            else:
                headers["Authorization"] = f"Bearer {token}"
        return headers

    @staticmethod
    def _cover_from_doc(doc: dict) -> str | None:
        image = doc.get("image")
        if isinstance(image, dict):
            return image.get("url")
        return None

    @classmethod
    def _record_from_doc(cls, doc: dict) -> BookRecord:
        rating = doc.get("rating")
        ratings_count = doc.get("ratings_count")
        readers = doc.get("users_read_count")
        return BookRecord(
            source_url=doc.get("slug"),
            title=doc.get("title"),
            authors=doc.get("author_names") or [],
            description=doc.get("description"),
            published_date=doc.get("release_date"),
            cover_url=cls._cover_from_doc(doc),
            rating=float(rating) if rating else None,
            rating_count=int(ratings_count) if ratings_count else None,
            readers_count=int(readers) if readers else None,
            tags=(
                (doc.get("genres") or [])
                + (doc.get("moods") or [])
                + (doc.get("tags") or [])
            ),
        )

    async def _search(self, query: BookQuery) -> list[SearchCandidate]:
        if not self._token() or not query.title:
            return []

        first_author = query.authors[0] if query.authors else ""
        q = f"{query.title} {first_author}".strip()

        candidates: list[SearchCandidate] = []
        try:
            async with self._client() as client:
                resp = await client.post(
                    API_URL,
                    headers=self._headers(),
                    json={"query": SEARCH_QUERY, "variables": {"query": q}},
                )
                if resp.status_code != 200:
                    logger.warning(
                        f"Hardcover search returned {resp.status_code}: "
                        f"{resp.text[:200]}"
                    )
                    return []

                data = resp.json()
                search_data = data.get("data", {}).get("search", {}).get("results", {})
                for hit in search_data.get("hits", []):
                    doc = hit.get("document", {})
                    slug = doc.get("slug", "")
                    if not slug:
                        continue
                    # alternative_titles often hold the translated title —
                    # surface the best-matching one so base scoring (which
                    # only sees candidate.title) compares against it.
                    titles = [doc.get("title", "")] + (
                        doc.get("alternative_titles") or []
                    )
                    best_title = self._best_title(titles, query.title)
                    candidates.append(
                        SearchCandidate(
                            url=slug,
                            title=best_title,
                            authors=doc.get("author_names") or [],
                            prefetched=self._record_from_doc(doc),
                            published_date=doc.get("release_date"),
                            cover_url=self._cover_from_doc(doc),
                        )
                    )
        except RateLimitError:
            raise
        except Exception as e:
            logger.warning(f"Hardcover search failed: {e}")

        return candidates

    @staticmethod
    def _best_title(titles: list[str], query_title: str) -> str:
        best, best_score = "", -1.0
        for t in titles:
            if not t:
                continue
            score = fuzz.token_sort_ratio(query_title.lower(), t.lower())
            if score > best_score:
                best, best_score = t, score
        return best

    @classmethod
    def _record_from_book_row(cls, row: dict) -> BookRecord:
        """The books table speaks a different shape than the search
        document: authors live in contributions, tags in cached_tags
        (category -> entries; Content Warning stays out, matching the
        search path's genres+moods+tags)."""
        rating = row.get("rating")
        ratings_count = row.get("ratings_count")
        readers = row.get("users_read_count")
        cached = row.get("cached_tags") or {}
        return BookRecord(
            source_url=row.get("slug"),
            title=row.get("title"),
            authors=[
                c["author"]["name"]
                for c in (row.get("contributions") or [])
                if isinstance(c, dict)
                and isinstance(c.get("author"), dict)
                and c["author"].get("name")
            ],
            description=row.get("description") or None,
            published_date=row.get("release_date"),
            cover_url=cls._cover_from_doc(row),
            rating=float(rating) if rating else None,
            rating_count=int(ratings_count) if ratings_count else None,
            readers_count=int(readers) if readers else None,
            tags=[
                entry["tag"]
                for category in ("Genre", "Mood", "Tag")
                for entry in cached.get(category) or []
                if isinstance(entry, dict) and entry.get("tag")
            ],
        )

    async def _fetch(self, url: str) -> BookRecord:
        """By-slug lookup. Used for candidate picks and pinned URLs;
        `url` may be a bare slug or a full hardcover.app/books/ URL.
        An unknown slug returns a bare record — never a guess."""
        slug = url.removeprefix(self.url_prefix)
        if not self._token():
            return BookRecord(source_url=slug)

        try:
            async with self._client() as client:
                resp = await client.post(
                    API_URL,
                    headers=self._headers(),
                    json={"query": BOOK_QUERY, "variables": {"slug": slug}},
                )
                if resp.status_code != 200:
                    logger.warning(
                        f"Hardcover book lookup returned {resp.status_code}: "
                        f"{resp.text[:200]}"
                    )
                    return BookRecord(source_url=slug)

                data = resp.json()
                if data.get("errors"):
                    logger.warning(
                        f"Hardcover book lookup errors for {slug}: "
                        f"{str(data['errors'])[:200]}"
                    )
                rows = (data.get("data") or {}).get("books") or []
                if not rows:
                    return BookRecord(source_url=slug)
                return self._record_from_book_row(rows[0])
        except RateLimitError:
            raise
        except Exception as e:
            logger.warning(f"Hardcover fetch failed for {slug}: {e}")
            return BookRecord(source_url=slug)
