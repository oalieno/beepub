import json
import logging
import re

import httpx
from bs4 import BeautifulSoup
from rapidfuzz import fuzz

from app.services.metadata_sources.base import (
    AbstractMetadataSource,
    FetchResult,
    SearchResult,
)

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


class GoodreadsSource(AbstractMetadataSource):
    source_name = "goodreads"

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
            "a.bookTitle",
            "a[data-testid='bookTitle']",
            "a[href^='/book/show/']",
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
                    full_url = f"https://www.goodreads.com{href}"

                # Strip query params and subpaths to get clean book URL
                full_url = full_url.split("?")[0]
                match = re.match(
                    r"(https?://www\.goodreads\.com/book/show/\d+)", full_url
                )
                if match:
                    full_url = match.group(1)

                if full_url in seen:
                    continue

                seen.add(full_url)
                links.append((full_url, text))

                if len(links) >= limit:
                    return links

        return links

    async def search(
        self, title: str, authors: list[str], isbn: str | None
    ) -> list[SearchResult]:
        results = []

        # Try ISBN first
        if isbn:
            try:
                async with httpx.AsyncClient(
                    headers=HEADERS, follow_redirects=True, timeout=15
                ) as client:
                    resp = await client.get(
                        "https://www.goodreads.com/search", params={"q": isbn}
                    )
                    if resp.status_code == 200:
                        # If redirected to a book page, use that URL directly
                        final_url = str(resp.url)
                        if "/book/show/" in final_url:
                            clean_url = final_url.split("?")[0]
                            results.append(
                                SearchResult(url=clean_url, title="", authors=[])
                            )
                        else:
                            soup = BeautifulSoup(resp.text, "html.parser")
                            for full_url, text in self._extract_book_links(
                                soup, limit=3
                            ):
                                results.append(
                                    SearchResult(url=full_url, title=text, authors=[])
                                )
            except Exception as e:
                logger.warning(f"Goodreads ISBN search failed: {e}")

        if results:
            return results

        # Fallback: title+author search
        try:
            queries = self._build_queries(title, authors)
            async with httpx.AsyncClient(
                headers=HEADERS, follow_redirects=True, timeout=15
            ) as client:
                for query in queries:
                    if not query:
                        continue

                    resp = await client.get(
                        "https://www.goodreads.com/search", params={"q": query}
                    )
                    if resp.status_code != 200:
                        continue

                    soup = BeautifulSoup(resp.text, "html.parser")
                    links = self._extract_book_links(soup, limit=5)

                    if links:
                        for full_url, text in links:
                            score = fuzz.token_set_ratio(title.lower(), text.lower())
                            results.append(
                                SearchResult(
                                    url=full_url, title=text, authors=[], score=score
                                )
                            )
                        results.sort(key=lambda r: r.score, reverse=True)
                        break
        except Exception as e:
            logger.warning(f"Goodreads title search failed: {e}")

        return results[:3]

    @staticmethod
    def _normalize_book_url(url: str) -> str:
        """Strip trailing subpaths like /reviews, /editions from book URLs."""
        match = re.match(r"(https?://www\.goodreads\.com/book/show/\d+)", url)
        return match.group(1) if match else url

    async def fetch(self, url: str) -> FetchResult:
        url = self._normalize_book_url(url)
        try:
            async with httpx.AsyncClient(
                headers=HEADERS, follow_redirects=True, timeout=15
            ) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    return FetchResult(source_url=url)

                soup = BeautifulSoup(resp.text, "html.parser")

                # Try JSON-LD structured data
                json_ld = soup.find("script", type="application/ld+json")
                rating = None
                rating_count = None
                raw = {}

                if json_ld:
                    try:
                        ld_text = json_ld.string or json_ld.get_text()
                        data = json.loads(ld_text)
                        raw = data
                        agg = data.get("aggregateRating", {})
                        rating = float(agg.get("ratingValue", 0)) or None
                        rating_count = int(agg.get("ratingCount", 0)) or None
                    except Exception:
                        logger.warning("Failed to parse JSON-LD from %s", url)

                # Fallback: scrape rating display
                if rating is None:
                    rating_el = soup.select_one(
                        "[data-testid='ratingsCount']"
                    ) or soup.select_one(".RatingStatistics__rating")
                    if rating_el:
                        try:
                            rating = float(rating_el.get_text(strip=True).split()[0])
                        except Exception:
                            pass

                # Extract genres/shelves
                genres = []
                for genre_el in soup.select(
                    "[data-testid='genresList'] a, "
                    ".BookPageMetadataSection__genreButton a, "
                    ".actionLinkLite.bookPageGenreLink"
                ):
                    genre_text = genre_el.get_text(strip=True)
                    if genre_text and genre_text not in genres:
                        genres.append(genre_text)

                # Extract top shelves (user-voted categories)
                shelves = []
                for shelf_el in soup.select(
                    "[data-testid='shelfList'] a, "
                    ".BookPageShelfList a, "
                    "a.actionLinkLite.bookPageGenreLink"
                ):
                    shelf_text = shelf_el.get_text(strip=True)
                    if shelf_text and shelf_text not in shelves and shelf_text not in genres:
                        shelves.append(shelf_text)

                raw["genres"] = genres
                raw["shelves"] = shelves

                # Extract top reviews
                reviews = []
                review_els = soup.select(".ReviewCard, .friendReviews")
                for el in review_els[:5]:
                    text_el = el.select_one(".ReviewText, .reviewText")
                    if text_el:
                        reviews.append({"content": text_el.get_text(strip=True)[:500]})

                return FetchResult(
                    source_url=url,
                    rating=rating,
                    rating_count=rating_count,
                    reviews=reviews if reviews else None,
                    raw_data=raw,
                )
        except Exception as e:
            logger.warning(f"Goodreads fetch failed for {url}: {e}")
            return FetchResult(source_url=url)
