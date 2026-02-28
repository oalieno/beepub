import json
import logging
import httpx
from bs4 import BeautifulSoup
from rapidfuzz import fuzz

from daemon.sources.base import AbstractMetadataSource, SearchResult, FetchResult

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; BeePub/1.0; +https://github.com/beepub)"
}


class GoodreadsSource(AbstractMetadataSource):
    source_name = "goodreads"

    async def search(self, title: str, authors: list[str], isbn: str | None) -> list[SearchResult]:
        results = []

        # Try ISBN first
        if isbn:
            try:
                async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=15) as client:
                    url = f"https://www.goodreads.com/search?q={isbn}"
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        soup = BeautifulSoup(resp.text, "html.parser")
                        book_links = soup.select("a.bookTitle")
                        for link in book_links[:3]:
                            href = link.get("href", "")
                            text = link.get_text(strip=True)
                            if href:
                                full_url = f"https://www.goodreads.com{href}"
                                results.append(SearchResult(url=full_url, title=text, authors=[]))
            except Exception as e:
                logger.warning(f"Goodreads ISBN search failed: {e}")

        if results:
            return results

        # Fallback: title+author search
        try:
            query = f"{title} {' '.join(authors[:1])}"
            async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=15) as client:
                url = f"https://www.goodreads.com/search?q={httpx.QueryParams({'q': query})}"
                resp = await client.get(f"https://www.goodreads.com/search?q={query}")
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    book_links = soup.select("a.bookTitle")
                    for link in book_links[:5]:
                        href = link.get("href", "")
                        text = link.get_text(strip=True)
                        if href:
                            score = fuzz.token_set_ratio(title.lower(), text.lower())
                            full_url = f"https://www.goodreads.com{href}"
                            results.append(SearchResult(url=full_url, title=text, authors=[], score=score))
                    results.sort(key=lambda r: r.score, reverse=True)
        except Exception as e:
            logger.warning(f"Goodreads title search failed: {e}")

        return results[:3]

    async def fetch(self, url: str) -> FetchResult:
        try:
            async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=15) as client:
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
                        data = json.loads(json_ld.string)
                        raw = data
                        agg = data.get("aggregateRating", {})
                        rating = float(agg.get("ratingValue", 0)) or None
                        rating_count = int(agg.get("ratingCount", 0)) or None
                    except Exception:
                        pass

                # Fallback: scrape rating display
                if rating is None:
                    rating_el = soup.select_one("[data-testid='ratingsCount']") or soup.select_one(".RatingStatistics__rating")
                    if rating_el:
                        try:
                            rating = float(rating_el.get_text(strip=True).split()[0])
                        except Exception:
                            pass

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
