"""Pubu (電子書城) plugin — zh-TW ebook-store bibliographic data.

Search and book pages both answer scripted requests. The search page
renders recommendation carousels with the same article markup as real
results — items are scoped to the gallery-view list and an
empty-notice (p.empty-info-txtInfo) short-circuits to no hits, or a
no-result query would surface strangers. The search does not index
ISBNs (verified live), so only title and URL clues are accepted; the
book page's JSON-LD (@type Book) plus the #info-content panel carry
the full record."""

import json
import logging
import re

from bs4 import BeautifulSoup

from app.plugins.metadata.base import (
    BookQuery,
    BookRecord,
    Clue,
    MetadataPlugin,
    RateLimitError,
    SearchCandidate,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://www.pubu.com.tw"
SEARCH_URL = BASE_URL + "/search"
BOOK_URL = BASE_URL + "/ebook/{item_id}"

_EBOOK_ID_RE = re.compile(r"/ebook/(\d+)")
_DATE_RE = re.compile(r"20\d{2}/\d{1,2}/\d{1,2}")
# The rating widget reads 「5.0分，5則評分」. Comments are JS-loaded —
# nothing to scrape, so reviews stay out of provides.
_RATING_RE = re.compile(r"(\d+(?:\.\d+)?)分，(\d+)則評分")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9",
}


class PubuPlugin(MetadataPlugin):
    name = "pubu"
    label = "Pubu"
    kind = "scraper"
    locale = "zh-TW"
    accepts = frozenset({Clue.TITLE, Clue.URL})
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
        {"res1.pubu.tw", "res2.pubu.tw", "res3.pubu.tw", "res4.pubu.tw"}
    )
    url_prefix = "https://www.pubu.com.tw/ebook/"
    id_pattern = r"^\d+$"
    id_hint = "e.g. 628595"

    @staticmethod
    def _build_queries(title: str) -> list[str]:
        normalized = re.sub(r"[（(][^）)]*[）)]", "", title)
        normalized = re.sub(r"[【\[][^】\]]*[】\]]", "", normalized)
        normalized = " ".join(normalized.split()).strip()
        queries = [title.strip()]
        if normalized and normalized not in queries:
            queries.append(normalized)
        return queries

    @staticmethod
    def _cover_from_img(img) -> str | None:
        if img is None:
            return None
        src = img.get("data-src") or ""
        if not src.startswith("https://"):
            src = img.get("src") or ""
        return src if src.startswith("https://") else None

    @classmethod
    def _parse_search_items(cls, html: str, limit: int) -> list[SearchCandidate]:
        soup = BeautifulSoup(html, "lxml")
        # The no-result page still carries a recommendation cover-list;
        # the notice is the authoritative "nothing matched".
        if soup.select_one("p.empty-info-txtInfo") is not None:
            return []
        candidates: list[SearchCandidate] = []
        seen: set[str] = set()
        for art in soup.select("div.cover-list.gallery-view article"):
            anchor = art.select_one("h3 a[href^='/ebook/']")
            if anchor is None:
                continue
            id_match = _EBOOK_ID_RE.search(anchor.get("href", ""))
            if id_match is None:
                continue
            url = BOOK_URL.format(item_id=id_match.group(1))
            if url in seen:
                continue
            title = (anchor.get("title") or anchor.get_text(strip=True) or "").strip()
            if not title:
                continue
            store = art.select_one(".info-others a[href^='/store/']")
            seen.add(url)
            candidates.append(
                SearchCandidate(
                    url=url,
                    title=title,
                    authors=[
                        a.get_text(strip=True)
                        for a in art.select("a.author")
                        if a.get_text(strip=True)
                    ],
                    publisher=store.get_text(strip=True) if store else None,
                    cover_url=cls._cover_from_img(art.select_one("img")),
                )
            )
            if len(candidates) >= limit:
                break
        return candidates

    async def _search(self, query: BookQuery) -> list[SearchCandidate]:
        if not query.title:
            return []
        try:
            async with self._client(HEADERS) as client:
                for q in self._build_queries(query.title):
                    resp = await client.get(SEARCH_URL, params={"q": q})
                    if resp.status_code != 200:
                        continue
                    candidates = self._parse_search_items(resp.text, limit=5)
                    if candidates:
                        return candidates
        except RateLimitError:
            raise
        except Exception as e:
            logger.warning(f"Pubu search failed: {e}")
        return []

    @staticmethod
    def _parse_description(soup: BeautifulSoup) -> str | None:
        """The full intro is server-rendered in #info-content (og: and
        LD descriptions are teasers or empty). Same br handling as
        readmoo: insert_before + unwrap, never replace_with."""
        container = soup.select_one("#info-content .font-base")
        if container is None:
            return None
        for heading in container.find_all(["h1", "h2", "h3"]):
            heading.extract()
        for br in container.find_all("br"):
            br.insert_before("\n")
            br.unwrap()
        for block in container.find_all(["p", "div", "li"]):
            block.append("\n\n")
        lines = [line.strip() for line in container.get_text().splitlines()]
        text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
        return text or None

    @classmethod
    def _parse_book_page(cls, html: str, url: str) -> BookRecord:
        soup = BeautifulSoup(html, "lxml")

        book: dict = {}
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or script.get_text())
            except Exception:
                continue
            ld_type = data.get("@type")
            types = ld_type if isinstance(ld_type, list) else [ld_type]
            if "Book" in types:
                book = data
                break

        author = book.get("author")
        if isinstance(author, dict):  # LD allows a Person object
            author = author.get("name")
        authors: list[str] = []
        if isinstance(author, str):
            authors = [p.strip() for p in re.split(r"[、,，]", author) if p.strip()]

        published_date = None
        date_label = soup.find(string=lambda s: s and s.strip() == "發行")
        if date_label:
            col = date_label.find_parent("div")
            sibling = col.find_next_sibling("div") if col else None
            if sibling:
                date_match = _DATE_RE.search(sibling.get_text(" ", strip=True))
                if date_match:
                    published_date = date_match.group(0)

        tags = [
            text
            for a in soup.select(".breadcrumb a")
            if (text := a.get_text(strip=True)) and text != "首頁"
        ]

        rating = None
        rating_count = None
        for widget in soup.select(".pubuUI-js-product-ratingStars"):
            rating_match = _RATING_RE.search(widget.get_text(" ", strip=True))
            if rating_match:
                rating = float(rating_match.group(1)) or None
                rating_count = int(rating_match.group(2)) or None
                break

        description = cls._parse_description(soup)
        if description is None:
            description = (book.get("description") or "").strip() or None

        image = book.get("image")
        return BookRecord(
            source_url=url,
            title=book.get("name"),
            authors=authors,
            publisher=book.get("publisher"),
            description=description,
            published_date=published_date,
            language=book.get("inLanguage"),
            cover_url=image if isinstance(image, str) else None,
            rating=rating,
            rating_count=rating_count,
            tags=tags,
        )

    async def _fetch(self, url: str) -> BookRecord:
        """Book-page fetch; `url` may be a bare ebook id or a full
        /ebook/ URL."""
        id_match = _EBOOK_ID_RE.search(url) or re.fullmatch(r"(\d+)", url)
        if id_match:
            url = BOOK_URL.format(item_id=id_match.group(1))
        try:
            async with self._client(HEADERS) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    return BookRecord(source_url=url)
                return self._parse_book_page(resp.text, url)
        except RateLimitError:
            raise
        except Exception as e:
            logger.warning(f"Pubu fetch failed for {url}: {e}")
            return BookRecord(source_url=url)
