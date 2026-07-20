"""Google Books plugin — full bibliographic records, covers, and ratings.

The search endpoint routinely omits imageLinks (and sometimes
description/publisher) even when the volume has them, so _fetch always
reads the volume-detail endpoint — the authoritative record."""

import logging
import re
from urllib.parse import parse_qs, urlparse

from app.plugins.metadata.base import (
    BookQuery,
    BookRecord,
    Clue,
    MetadataPlugin,
    RateLimitError,
    SearchCandidate,
)

logger = logging.getLogger(__name__)

API_BASE = "https://www.googleapis.com/books/v1/volumes"

# Best-first: the detail endpoint serves several sizes; search hits cap
# out at a 128px thumbnail when they carry imageLinks at all.
_COVER_PREFERENCE = (
    "extraLarge",
    "large",
    "medium",
    "small",
    "thumbnail",
    "smallThumbnail",
)


# The API flattens a description's line breaks into ASCII spaces. In
# CJK prose a plain space between two CJK characters can only be such a
# scar — real spaces sit next to Latin text ("PChome Online") and real
# CJK spacing uses U+3000. Latin-only descriptions are indistinguishable
# from normal prose and stay untouched.
_CJK = (
    "\\u3000-\\u303f"  # CJK punctuation
    "\\u3041-\\u30ff"  # kana
    "\\u4e00-\\u9fff"  # ideographs
    "\\uf900-\\ufaff"  # compatibility ideographs
    "\\uff00-\\uffef"  # fullwidth forms
)
_FLATTENED_BREAK = re.compile(f"(?<=[{_CJK}]) +(?=[{_CJK}])")


def _reflow_description(text: str | None) -> str | None:
    if not text or "\n" in text:
        return text
    return _FLATTENED_BREAK.sub("\n", text)


def _pick_cover(image_links: dict) -> str | None:
    for key in _COVER_PREFERENCE:
        url = image_links.get(key)
        if not url:
            continue
        if url.startswith("http://"):
            url = "https://" + url[len("http://") :]
        # edge=curl bakes a fake page-fold into the image — not cover art.
        return url.replace("&edge=curl", "").replace("edge=curl&", "")
    return None


class GoogleBooksPlugin(MetadataPlugin):
    name = "google_books"
    label = "Google Books"
    kind = "api"
    accepts = frozenset({Clue.ISBN, Clue.TITLE, Clue.URL})
    provides = frozenset(
        {
            "title",
            "authors",
            "publisher",
            "description",
            "published_date",
            "language",
            "cover_url",
            "rating",
            "rating_count",
            "tags",
        }
    )
    cover_hosts = frozenset(
        {
            "books.google.com",
            "books.googleusercontent.com",
            # Volume-detail image links are sometimes served from Google's
            # generic image CDN rather than the books hosts.
            "lh3.googleusercontent.com",
        }
    )
    settings_keys = ("google_books_api_key",)
    secret_settings_keys = ("google_books_api_key",)
    ratelimit_cooldown = 86400  # keyless access 429s for a long time
    url_prefix = "https://books.google.com/books?id="
    id_pattern = r"^[\w-]+$"
    id_hint = "e.g. qixiEAAAQBAJ"

    def _key_params(self) -> dict[str, str]:
        api_key = self.settings.get("google_books_api_key", "")
        return {"key": api_key} if api_key else {}

    @staticmethod
    def _extract_volume_id(url: str) -> str:
        """Stored source_urls are bare volume IDs; manually-linked ones
        may arrive as full books.google.com URLs."""
        if "books.google.com" in url:
            parsed = urlparse(url)
            volume_id = parse_qs(parsed.query).get("id", [""])[0]
            if volume_id:
                return volume_id
        return url

    async def resolve(self, query: BookQuery) -> BookRecord | None:
        # A url clue arriving on a fresh instance (candidate pick,
        # pinned URL in the job) has no search-side stash, but the merge
        # in _fetch needs one — TW no-preview volumes carry their
        # description only in the search response. Re-run the search
        # when the other clues allow so the stash covers the volume.
        if query.url and (query.isbn or query.title):
            await self._search(query)
        return await super().resolve(query)

    async def _search(self, query: BookQuery) -> list[SearchCandidate]:
        candidates: list[SearchCandidate] = []
        params: dict[str, str | int] = {"maxResults": 5, **self._key_params()}
        # Search-response volumeInfo per volume id, merged in _fetch: the
        # two endpoints omit fields in BOTH directions (see _fetch).
        self._search_vi: dict[str, dict] = {}

        def collect(item: dict, *, exact: bool) -> None:
            vi = item.get("volumeInfo", {})
            self._search_vi[item["id"]] = vi
            candidates.append(
                SearchCandidate(
                    url=item["id"],
                    title=vi.get("title", ""),
                    authors=vi.get("authors", []),
                    exact=exact,
                    publisher=vi.get("publisher"),
                    published_date=vi.get("publishedDate"),
                    cover_url=_pick_cover(vi.get("imageLinks") or {}),
                )
            )

        try:
            async with self._client() as client:
                # Try ISBN first
                if query.isbn:
                    params["q"] = f"isbn:{query.isbn}"
                    resp = await client.get(API_BASE, params=params)
                    if resp.status_code == 200:
                        for item in resp.json().get("items", []):
                            collect(item, exact=True)
                    if candidates:
                        return candidates

                # Fallback: title + author
                if not query.title:
                    return []
                first_author = query.authors[0] if query.authors else ""
                q_parts = [f"intitle:{query.title}"]
                if first_author:
                    q_parts.append(f"inauthor:{first_author}")

                params["q"] = " ".join(q_parts)
                resp = await client.get(API_BASE, params=params)
                if resp.status_code != 200:
                    return []

                for item in resp.json().get("items", []):
                    collect(item, exact=False)
        except RateLimitError:
            raise
        except Exception as e:
            logger.warning(f"Google Books search failed: {e}")

        return candidates

    async def _fetch(self, url: str) -> BookRecord:
        volume_id = self._extract_volume_id(url)
        try:
            async with self._client() as client:
                resp = await client.get(
                    f"{API_BASE}/{volume_id}", params=self._key_params()
                )
                if resp.status_code != 200:
                    return BookRecord(source_url=volume_id)

                dvi = resp.json().get("volumeInfo", {})
                svi = getattr(self, "_search_vi", {}).get(volume_id, {})
                # The two endpoints omit fields in BOTH directions: search
                # hits often lack imageLinks, while the detail record drops
                # description for TW no-preview volumes. Merge search-first
                # (the pre-plugin behavior), except covers — detail serves
                # the real sizes, search caps at a 128px thumbnail.
                vi = {**dvi, **{k: v for k, v in svi.items() if v}}
                vi["imageLinks"] = dvi.get("imageLinks") or svi.get("imageLinks") or {}

                title = vi.get("title")
                if vi.get("subtitle"):
                    title = f"{title}: {vi['subtitle']}" if title else vi["subtitle"]

                # Hierarchical category strings like "Fiction / Science
                # Fiction" — keep the full string plus each level.
                tags: list[str] = []
                for cat in vi.get("categories", []):
                    tags.append(cat)
                    for part in cat.split(" / "):
                        part = part.strip()
                        if part:
                            tags.append(part)
                if vi.get("mainCategory"):
                    tags.append(vi["mainCategory"])

                rating = vi.get("averageRating")
                rating_count = vi.get("ratingsCount")

                return BookRecord(
                    source_url=volume_id,
                    title=title,
                    authors=vi.get("authors", []),
                    publisher=vi.get("publisher"),
                    description=_reflow_description(vi.get("description")),
                    published_date=vi.get("publishedDate"),
                    language=vi.get("language"),
                    cover_url=_pick_cover(vi.get("imageLinks") or {}),
                    tags=tags,
                    rating=float(rating) if rating else None,
                    rating_count=int(rating_count) if rating_count else None,
                )
        except RateLimitError:
            raise
        except Exception as e:
            logger.warning(f"Google Books fetch failed for {volume_id}: {e}")
            return BookRecord(source_url=volume_id)
