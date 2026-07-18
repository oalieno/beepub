"""Readmoo (讀墨) plugin — zh-TW store ratings, reviews, and category tags."""

import logging
import re
from urllib.parse import urlparse

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

SEARCH_URL = "https://readmoo.com/search/keyword"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; BeePub/1.0)",
    "Accept-Language": "zh-TW,zh;q=0.9",
}


class ReadmooPlugin(MetadataPlugin):
    name = "readmoo"
    label = "Readmoo 讀墨"
    kind = "scraper"
    locale = "zh-TW"
    accepts = frozenset({Clue.TITLE, Clue.URL})
    provides = frozenset({"rating", "rating_count", "reviews", "tags"})
    url_prefix = "https://readmoo.com/book/"
    id_pattern = r"^\d+$"
    id_hint = "e.g. 210227953000101"

    @staticmethod
    def _build_queries(title: str, authors: list[str]) -> list[str]:
        first_author = " ".join(authors[:1]).strip()
        normalized_title = re.sub(r"[（(][^）)]*[）)]", "", title)
        normalized_title = re.sub(r"[【\[][^】\]]*[】\]]", "", normalized_title)
        normalized_title = " ".join(normalized_title.split()).strip()

        candidates = [
            f"{title} {first_author}".strip(),
            title.strip(),
            f"{normalized_title} {first_author}".strip(),
            normalized_title,
        ]

        queries: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            cleaned = " ".join(candidate.split())
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            queries.append(cleaned)

        return queries

    @staticmethod
    def _extract_book_links(soup: BeautifulSoup, limit: int) -> list[tuple[str, str]]:
        links: list[tuple[str, str]] = []
        seen: set[str] = set()

        selectors = [
            "h4 a.product-link[href*='/book/']",
            "a.product-link[href*='/book/']",
            "a[href*='/book/']",
        ]
        for selector in selectors:
            for link in soup.select(selector):
                href = link.get("href", "")
                text = link.get_text(strip=True)
                if not href or not text:
                    continue

                if href.startswith("http"):
                    full_url = href
                else:
                    full_url = f"https://readmoo.com{href}"

                parsed = urlparse(full_url)
                path = parsed.path or ""
                if not re.match(r"^/book/\d+$", path):
                    continue

                canonical_url = f"https://readmoo.com{path}"
                if canonical_url in seen:
                    continue

                seen.add(canonical_url)
                links.append((canonical_url, text))

                if len(links) >= limit:
                    return links

        return links

    async def _search(self, query: BookQuery) -> list[SearchCandidate]:
        if not query.title:
            return []

        candidates: list[SearchCandidate] = []
        try:
            queries = self._build_queries(query.title, query.authors)
            async with self._client(HEADERS) as client:
                for q in queries:
                    resp = await client.get(
                        SEARCH_URL, params={"q": q, "src": "search"}
                    )
                    if resp.status_code != 200:
                        continue

                    soup = BeautifulSoup(resp.text, "html.parser")
                    links = self._extract_book_links(soup, limit=5)
                    if links:
                        candidates = [
                            SearchCandidate(url=full_url, title=text)
                            for full_url, text in links
                        ]
                        break
        except RateLimitError:
            raise
        except Exception as e:
            logger.warning(f"Readmoo search failed: {e}")
        return candidates

    async def _fetch(self, url: str) -> BookRecord:
        try:
            async with self._client(HEADERS) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    return BookRecord(source_url=url)

                soup = BeautifulSoup(resp.text, "html.parser")

                rating = None
                rating_count = None

                rating_value_el = soup.select_one("[itemprop='ratingValue']")
                if rating_value_el:
                    try:
                        raw = rating_value_el.get(
                            "content"
                        ) or rating_value_el.get_text(strip=True)
                        rating = float(str(raw).replace(",", ""))
                    except Exception:
                        pass

                rating_count_el = soup.select_one("[itemprop='ratingCount']")
                if rating_count_el:
                    try:
                        raw = rating_count_el.get(
                            "content"
                        ) or rating_count_el.get_text(strip=True)
                        rating_count = (
                            int("".join(filter(str.isdigit, str(raw)))) or None
                        )
                    except Exception:
                        pass

                rating_el = soup.select_one(".rating-score, .score")
                if rating is None and rating_el:
                    try:
                        rating = float(rating_el.get_text(strip=True).replace(",", ""))
                    except Exception:
                        pass

                if rating is None:
                    avg_rating_el = soup.select_one(".avg-rating")
                    if avg_rating_el:
                        try:
                            rating = float(
                                avg_rating_el.get_text(strip=True).replace(",", "")
                            )
                        except Exception:
                            pass

                count_el = soup.select_one(".rating-count, .review-count")
                if rating_count is None and count_el:
                    try:
                        text = (
                            count_el.get_text(strip=True)
                            .replace(",", "")
                            .replace("評分", "")
                            .strip()
                        )
                        rating_count = int("".join(filter(str.isdigit, text))) or None
                    except Exception:
                        pass

                if rating_count is None and rating_value_el and rating_value_el.parent:
                    try:
                        text = rating_value_el.parent.get_text(" ", strip=True).replace(
                            ",", ""
                        )
                        rating_count = int("".join(filter(str.isdigit, text))) or None
                    except Exception:
                        pass

                # Breadcrumb / category links = raw tags
                categories: list[str] = []
                for cat_el in soup.select(
                    ".breadcrumb a, "
                    ".category-link, "
                    "[itemprop='genre'], "
                    ".book-category a, "
                    ".book-meta a[href*='/category/']"
                ):
                    cat_text = cat_el.get_text(strip=True)
                    if cat_text and cat_text not in categories and cat_text != "首頁":
                        categories.append(cat_text)

                reviews = []
                review_els = soup.select(".review-item, .comment-item")
                for el in review_els[:5]:
                    text_el = el.select_one(".review-content, .comment-content")
                    if text_el:
                        reviews.append({"content": text_el.get_text(strip=True)[:500]})

                return BookRecord(
                    source_url=url,
                    rating=rating,
                    rating_count=rating_count,
                    reviews=reviews if reviews else None,
                    tags=categories,
                )
        except RateLimitError:
            raise
        except Exception as e:
            logger.warning(f"Readmoo fetch failed for {url}: {e}")
            return BookRecord(source_url=url)
