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
    # The keyword search matches print ISBNs too (verified live), which
    # makes readmoo the zh-TW description source for TW editions —
    # books.com.tw blocks its product pages and Google's TW records are
    # usually metadata-only.
    accepts = frozenset({Clue.ISBN, Clue.TITLE, Clue.URL})
    provides = frozenset(
        {
            "title",
            "authors",
            "publisher",
            "description",
            "cover_url",
            "rating",
            "rating_count",
            "reviews",
            "tags",
        }
    )
    cover_hosts = frozenset({"cdn.readmoo.com"})
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

    @classmethod
    def _extract_cards(cls, soup: BeautifulSoup, limit: int) -> list[SearchCandidate]:
        """Parse full result cards (li.listItem-box): canonical book
        URL, full title (the h4 anchor's title attribute — the visible
        text is line-wrapped), authors, publisher, and the lazy-loaded
        cover thumbnail. Falls back to _extract_book_links when the
        page layout doesn't match."""
        cards: list[SearchCandidate] = []
        seen: set[str] = set()
        for li in soup.select("li.listItem-box"):
            link = li.select_one(".caption h4 a.product-link") or li.select_one(
                "a.product-link[href*='/book/']"
            )
            if link is None:
                continue
            href = link.get("href", "")
            full_url = href if href.startswith("http") else f"https://readmoo.com{href}"
            path = urlparse(full_url).path or ""
            if not re.match(r"^/book/\d+$", path):
                continue
            url = f"https://readmoo.com{path}"
            if url in seen:
                continue
            title = (link.get("title") or link.get_text(strip=True) or "").strip()
            if not title:
                continue
            authors = [
                a.get_text(strip=True)
                for a in li.select(".contributor-info a")
                if a.get_text(strip=True)
            ]
            publisher_el = li.select_one(".publisher-info a")
            img = li.select_one("img[data-lazy-original]") or li.select_one(
                "img[itemprop='image']"
            )
            cover = None
            if img is not None:
                cover = img.get("data-lazy-original") or img.get("src")
                if cover and cover.endswith("openbook.png"):  # lazy placeholder
                    cover = None
            seen.add(url)
            cards.append(
                SearchCandidate(
                    url=url,
                    title=title,
                    authors=authors,
                    publisher=(
                        publisher_el.get_text(strip=True) if publisher_el else None
                    ),
                    cover_url=cover,
                )
            )
            if len(cards) >= limit:
                break
        return cards

    @classmethod
    def _extract_candidates(
        cls, soup: BeautifulSoup, limit: int
    ) -> list[SearchCandidate]:
        cards = cls._extract_cards(soup, limit)
        if cards:
            return cards
        return [
            SearchCandidate(url=url, title=text)
            for url, text in cls._extract_book_links(soup, limit)
        ]

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
        candidates: list[SearchCandidate] = []

        # ISBN first: a 13-digit hit in the keyword search is effectively
        # an exact match.
        if query.isbn:
            try:
                async with self._client(HEADERS) as client:
                    resp = await client.get(
                        SEARCH_URL, params={"q": query.isbn, "src": "search"}
                    )
                    if resp.status_code == 200:
                        soup = BeautifulSoup(resp.text, "html.parser")
                        candidates = self._extract_candidates(soup, limit=3)
                        for candidate in candidates:
                            candidate.exact = True
            except RateLimitError:
                raise
            except Exception as e:
                logger.warning(f"Readmoo ISBN search failed: {e}")

        if candidates or not query.title:
            return candidates

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
                    found = self._extract_candidates(soup, limit=5)
                    if found:
                        candidates = found
                        break
        except RateLimitError:
            raise
        except Exception as e:
            logger.warning(f"Readmoo search failed: {e}")
        return candidates

    @staticmethod
    def _parse_description(soup: BeautifulSoup) -> str | None:
        """Full intro lives in #book-detail-description (an h2 「詳細資訊」
        heading followed by the text); the meta descriptions are 50-char
        truncations.

        The page formats with <br><br> runs and <p> blocks; descriptions
        are displayed through markdown, where single newlines collapse —
        so paragraph boundaries must come out as blank lines to survive
        rendering."""
        container = soup.select_one("#book-detail-description")
        if container is None:
            meta = soup.select_one("meta[property='og:description']")
            return meta.get("content") if meta else None
        for heading in container.find_all(["h1", "h2", "h3"]):
            heading.extract()
        for br in container.find_all("br"):
            br.replace_with("\n")
        for block in container.find_all(["p", "div", "li"]):
            block.append("\n\n")
        lines = [line.strip() for line in container.get_text().splitlines()]
        text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
        return text or None

    @staticmethod
    def _parse_cover(soup: BeautifulSoup) -> str | None:
        """og:image carries the full-size cover (~630x945); the
        itemprop=image element only has a 460x580 variant."""
        og = soup.select_one("meta[property='og:image']")
        if og and og.get("content"):
            return og["content"]
        img = soup.select_one("img[itemprop='image']")
        if img and img.get("src"):
            return img["src"]
        return None

    async def _fetch(self, url: str) -> BookRecord:
        try:
            async with self._client(HEADERS) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    return BookRecord(source_url=url)

                soup = BeautifulSoup(resp.text, "html.parser")

                title_el = soup.select_one("h1.book-detail-title") or soup.select_one(
                    "h1"
                )
                title = title_el.get_text(strip=True) if title_el else None

                authors: list[str] = []
                for author_el in soup.select("[itemprop='author']"):
                    author = author_el.get_text(strip=True)
                    if author and author not in authors:
                        authors.append(author)

                publisher_el = soup.select_one("[itemprop='publisher']")
                publisher = publisher_el.get_text(strip=True) if publisher_el else None

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
                    title=title,
                    authors=authors,
                    publisher=publisher,
                    description=self._parse_description(soup),
                    cover_url=self._parse_cover(soup),
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
