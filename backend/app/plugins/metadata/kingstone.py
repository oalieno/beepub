"""Kingstone (金石堂) plugin — full zh-TW bibliographic data.

Unlike books.com.tw, both the search page and the product page answer
scripted requests: search result items carry title, authors, publisher
and cover, and the product page's JSON-LD (["Product","Book"]) plus
the 內容簡介 panel add description, publication date, rating and
category tags. The search page header ships trending-keyword /basic/
links — parsing must stay inside result items (li.displayunit) or it
picks up strangers."""

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

BASE_URL = "https://www.kingstone.com.tw"
SEARCH_URL = BASE_URL + "/search/key/{query}"

_ITEM_ID_RE = re.compile(r"/basic/(\d+)")
_SEARCHLINK_RE = re.compile(r"SearchLink\('([^']+)','[^']*','au'\)")
_PUB_DATE_RE = re.compile(r"(\d{4}/\d{1,2}/\d{1,2})")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9",
}


class KingstonePlugin(MetadataPlugin):
    name = "kingstone"
    label = "金石堂"
    kind = "scraper"
    locale = "zh-TW"
    accepts = frozenset({Clue.ISBN, Clue.TITLE, Clue.URL})
    provides = frozenset(
        {
            "title",
            "authors",
            "publisher",
            "description",
            "published_date",
            "cover_url",
            "rating",
            "rating_count",
            "tags",
        }
    )
    cover_hosts = frozenset({"cdn.kingstone.com.tw"})
    url_prefix = "https://www.kingstone.com.tw/basic/"
    id_pattern = r"^\d+/?$"
    id_hint = "e.g. 2018612590237"

    @staticmethod
    def _build_queries(title: str) -> list[str]:
        normalized = re.sub(r"[（(][^）)]*[）)]", "", title)
        normalized = re.sub(r"[【\[][^】\]]*[】\]]", "", normalized)
        normalized = " ".join(normalized.split()).strip()
        queries = [title.strip()]
        if normalized and normalized not in queries:
            queries.append(normalized)
        return queries

    @classmethod
    def _parse_search_items(cls, html: str, limit: int) -> list[SearchCandidate]:
        soup = BeautifulSoup(html, "lxml")
        candidates: list[SearchCandidate] = []
        seen: set[str] = set()
        for li in soup.select("li.displayunit"):
            anchor = li.select_one("h3.pdnamebox a[href*='/basic/']")
            if anchor is None:
                continue
            id_match = _ITEM_ID_RE.search(anchor.get("href", ""))
            if id_match is None:
                continue
            url = f"{BASE_URL}/basic/{id_match.group(1)}/"
            if url in seen:
                continue
            title = anchor.get_text(strip=True)
            if not title:
                continue
            img = li.select_one(".coverbox img")
            cover = img.get("src") if img else None
            if cover and "noimg" in cover:
                cover = None
            publisher_el = li.select_one(".basic2box .publish a")
            seen.add(url)
            candidates.append(
                SearchCandidate(
                    url=url,
                    title=title,
                    authors=[
                        a.get_text(strip=True)
                        for a in li.select(".basic2box .author a")
                        if a.get_text(strip=True)
                    ],
                    publisher=(
                        publisher_el.get_text(strip=True) if publisher_el else None
                    ),
                    cover_url=cover,
                )
            )
            if len(candidates) >= limit:
                break
        return candidates

    async def _search(self, query: BookQuery) -> list[SearchCandidate]:
        # ISBN first — the search indexes ISBNs and answers an unknown
        # one with zero result items (verified live), so hits are exact.
        if query.isbn:
            try:
                async with self._client(HEADERS) as client:
                    resp = await client.get(SEARCH_URL.format(query=query.isbn))
                    if resp.status_code == 200:
                        candidates = self._parse_search_items(resp.text, limit=3)
                        # A print ISBN also matches its linked ebook
                        # listing, which pollutes the title with a
                        # 【電子書】 prefix — prefer the print edition.
                        candidates.sort(key=lambda c: c.title.startswith("【電子書】"))
                        for candidate in candidates:
                            candidate.exact = True
                        if candidates:
                            return candidates
            except RateLimitError:
                raise
            except Exception as e:
                logger.warning(f"Kingstone ISBN search failed: {e}")

        if not query.title:
            return []

        try:
            async with self._client(HEADERS) as client:
                for q in self._build_queries(query.title):
                    resp = await client.get(SEARCH_URL.format(query=q))
                    if resp.status_code != 200:
                        continue
                    candidates = self._parse_search_items(resp.text, limit=5)
                    if candidates:
                        return candidates
        except RateLimitError:
            raise
        except Exception as e:
            logger.warning(f"Kingstone title search failed: {e}")
        return []

    @staticmethod
    def _parse_description(soup: BeautifulSoup) -> str | None:
        """Full intro lives in the 內容簡介 panel (.pdintro). Same br
        handling as readmoo: insert_before + unwrap, never replace_with
        — a mis-nested <br> subtree would take its text with it."""
        container = soup.select_one(".pdintro")
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
    def _parse_product_page(cls, html: str, url: str) -> BookRecord:
        soup = BeautifulSoup(html, "lxml")

        product: dict = {}
        tags: list[str] = []
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or script.get_text())
            except Exception:
                continue
            ld_type = data.get("@type")
            types = ld_type if isinstance(ld_type, list) else [ld_type]
            if "Product" in types or "Book" in types:
                product = data
            elif "BreadcrumbList" in types:
                tags = [
                    name
                    for item in data.get("itemListElement", [])
                    if (name := item.get("name")) and name != "首頁"
                ]

        # Authors: SearchLink('name','','au') anchors inside the main
        # product info area only — carousels elsewhere link differently.
        authors: list[str] = []
        for anchor in soup.select(".basicarea a[href*='SearchLink']"):
            match = _SEARCHLINK_RE.search(anchor.get("href", ""))
            if match and match.group(1) not in authors:
                authors.append(match.group(1))

        published_date = None
        date_label = soup.find(
            "span", class_="title_basic", string=re.compile("出版日")
        )
        if date_label and date_label.parent:
            date_match = _PUB_DATE_RE.search(
                date_label.parent.get_text(" ", strip=True)
            )
            if date_match:
                published_date = date_match.group(1)
        if published_date is None:
            # Fallback: the LD description pipe-joins "YYYY/MM/DD出版".
            date_match = re.search(
                r"(\d{4}/\d{1,2}/\d{1,2})出版", product.get("description") or ""
            )
            if date_match:
                published_date = date_match.group(1)

        images = product.get("image")
        cover_url = None
        if isinstance(images, list) and images:
            cover_url = images[0]
        elif isinstance(images, str):
            cover_url = images

        rating = None
        rating_count = None
        agg = product.get("aggregateRating")
        if isinstance(agg, dict):
            try:
                rating = float(agg.get("ratingValue")) or None
            except (TypeError, ValueError):
                pass
            try:
                rating_count = int(agg.get("reviewCount")) or None
            except (TypeError, ValueError):
                pass

        brand = product.get("brand")
        publisher = brand.get("name") if isinstance(brand, dict) else None

        return BookRecord(
            source_url=url,
            title=product.get("name"),
            authors=authors,
            publisher=publisher,
            description=cls._parse_description(soup),
            published_date=published_date,
            cover_url=cover_url,
            rating=rating,
            rating_count=rating_count,
            tags=tags,
        )

    async def _fetch(self, url: str) -> BookRecord:
        """Product-page fetch; `url` may be a bare product id or a full
        /basic/ URL."""
        id_match = _ITEM_ID_RE.search(url) or re.fullmatch(r"(\d+)/?", url)
        if id_match:
            url = f"{BASE_URL}/basic/{id_match.group(1)}/"
        try:
            async with self._client(HEADERS) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    return BookRecord(source_url=url)
                return self._parse_product_page(resp.text, url)
        except RateLimitError:
            raise
        except Exception as e:
            logger.warning(f"Kingstone fetch failed for {url}: {e}")
            return BookRecord(source_url=url)
