import logging
import httpx
from bs4 import BeautifulSoup
from rapidfuzz import fuzz

from daemon.sources.base import AbstractMetadataSource, SearchResult, FetchResult

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; BeePub/1.0)",
    "Accept-Language": "zh-TW,zh;q=0.9",
}


class ReadmooSource(AbstractMetadataSource):
    source_name = "readmoo"

    async def search(self, title: str, authors: list[str], isbn: str | None) -> list[SearchResult]:
        results = []
        try:
            query = f"{title} {' '.join(authors[:1])}"
            async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=15) as client:
                resp = await client.get(
                    "https://readmoo.com/search/keyword",
                    params={"q": query, "src": "search"},
                )
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    items = soup.select(".book-info, .item-info")
                    for item in items[:5]:
                        title_el = item.select_one(".book-title, .title")
                        link_el = item.select_one("a")
                        if title_el and link_el:
                            href = link_el.get("href", "")
                            text = title_el.get_text(strip=True)
                            score = fuzz.token_set_ratio(title.lower(), text.lower())
                            if not href.startswith("http"):
                                href = f"https://readmoo.com{href}"
                            results.append(SearchResult(url=href, title=text, authors=[], score=score))
                    results.sort(key=lambda r: r.score, reverse=True)
        except Exception as e:
            logger.warning(f"Readmoo search failed: {e}")
        return results[:3]

    async def fetch(self, url: str) -> FetchResult:
        try:
            async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=15) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    return FetchResult(source_url=url)

                soup = BeautifulSoup(resp.text, "html.parser")

                rating = None
                rating_count = None

                rating_el = soup.select_one(".rating-score, .score")
                if rating_el:
                    try:
                        rating = float(rating_el.get_text(strip=True).replace(",", ""))
                    except Exception:
                        pass

                count_el = soup.select_one(".rating-count, .review-count")
                if count_el:
                    try:
                        text = count_el.get_text(strip=True).replace(",", "").replace("評分", "").strip()
                        rating_count = int("".join(filter(str.isdigit, text))) or None
                    except Exception:
                        pass

                reviews = []
                review_els = soup.select(".review-item, .comment-item")
                for el in review_els[:5]:
                    text_el = el.select_one(".review-content, .comment-content")
                    if text_el:
                        reviews.append({"content": text_el.get_text(strip=True)[:500]})

                return FetchResult(
                    source_url=url,
                    rating=rating,
                    rating_count=rating_count,
                    reviews=reviews if reviews else None,
                )
        except Exception as e:
            logger.warning(f"Readmoo fetch failed for {url}: {e}")
            return FetchResult(source_url=url)
