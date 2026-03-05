import json
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


class KoboTWSource(AbstractMetadataSource):
    source_name = "kobo_tw"

    @staticmethod
    def _is_challenged_response(status_code: int, body: str) -> bool:
        if status_code == 403:
            return True
        lowered = body.lower()
        return "challenged | kobo.com" in lowered or "captcha" in lowered

    async def search(self, title: str, authors: list[str], isbn: str | None) -> list[SearchResult]:
        results = []

        # Try ISBN search first
        if isbn:
            try:
                async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=15) as client:
                    resp = await client.get(
                        "https://www.kobo.com/tw/zh/search",
                        params={"query": isbn},
                    )
                    if self._is_challenged_response(resp.status_code, resp.text):
                        logger.warning("Kobo TW search blocked by anti-bot challenge (ISBN)")
                        return []
                    if resp.status_code == 200:
                        soup = BeautifulSoup(resp.text, "html.parser")
                        items = soup.select(".result-items .item-detail")
                        for item in items[:3]:
                            title_el = item.select_one(".title")
                            link_el = item.select_one("a")
                            if title_el and link_el:
                                href = link_el.get("href", "")
                                text = title_el.get_text(strip=True)
                                if not href.startswith("http"):
                                    href = f"https://www.kobo.com{href}"
                                results.append(SearchResult(url=href, title=text, authors=[]))
            except Exception as e:
                logger.warning(f"Kobo TW ISBN search failed: {e}")

        if results:
            return results

        # Fallback: title+author search
        try:
            query = f"{title} {' '.join(authors[:1])}"
            async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=15) as client:
                resp = await client.get(
                    "https://www.kobo.com/tw/zh/search",
                    params={"query": query},
                )
                if self._is_challenged_response(resp.status_code, resp.text):
                    logger.warning("Kobo TW search blocked by anti-bot challenge (title)")
                    return []
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    items = soup.select(".result-items .item-detail")
                    for item in items[:5]:
                        title_el = item.select_one(".title")
                        link_el = item.select_one("a")
                        if title_el and link_el:
                            href = link_el.get("href", "")
                            text = title_el.get_text(strip=True)
                            score = fuzz.token_set_ratio(title.lower(), text.lower())
                            if not href.startswith("http"):
                                href = f"https://www.kobo.com{href}"
                            results.append(SearchResult(url=href, title=text, authors=[], score=score))
                    results.sort(key=lambda r: r.score, reverse=True)
        except Exception as e:
            logger.warning(f"Kobo TW title search failed: {e}")

        return results[:3]

    async def fetch(self, url: str) -> FetchResult:
        try:
            async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=15) as client:
                resp = await client.get(url)
                if self._is_challenged_response(resp.status_code, resp.text):
                    logger.warning("Kobo TW fetch blocked by anti-bot challenge")
                    return FetchResult(source_url=url)
                if resp.status_code != 200:
                    return FetchResult(source_url=url)

                soup = BeautifulSoup(resp.text, "html.parser")

                # Try JSON-LD
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

                # Fallback scraping
                if rating is None:
                    rating_el = soup.select_one("[data-testid='average-rating']")
                    if rating_el:
                        try:
                            rating = float(rating_el.get_text(strip=True))
                        except Exception:
                            pass

                reviews = []
                review_els = soup.select(".review-text, .ReviewText")
                for el in review_els[:5]:
                    reviews.append({"content": el.get_text(strip=True)[:500]})

                return FetchResult(
                    source_url=url,
                    rating=rating,
                    rating_count=rating_count,
                    reviews=reviews if reviews else None,
                    raw_data=raw,
                )
        except Exception as e:
            logger.warning(f"Kobo TW fetch failed for {url}: {e}")
            return FetchResult(source_url=url)
