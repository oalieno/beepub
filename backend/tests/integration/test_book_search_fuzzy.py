"""Tiered fuzzy book search (services/book_search.py + migration 056).

Tier semantics under test, through the real API:
1. exact ILIKE substring — unchanged behavior, and it masks fuzzy noise
2. normalized ILIKE — whitespace / punctuation / width insensitive
3. trigram word_similarity — tolerates a wrong character
"""

import pytest
from httpx import AsyncClient

from tests.integration.util import create_library, upload_epub

pytestmark = pytest.mark.integration

TITLES = {
    "spaced": "街角 VR 食堂 深夜篇（全）",
    "unspaced": "街角VR食堂 早晨篇",
    "comma": "明日，明日，又明日",
    "short": "三體",
    "decoy": "三十歲的禮物",
    "latin": "Clean Code",
}


async def _seed(admin_client: AsyncClient) -> str:
    library_id = await create_library(admin_client, "Fuzzy")
    for i, title in enumerate(TITLES.values()):
        await upload_epub(
            admin_client,
            library_id,
            title=title,
            identifier=f"urn:uuid:00000000-0000-4000-8000-00000000010{i}",
        )
    return library_id


async def _search(client: AsyncClient, q: str) -> list[str]:
    response = await client.get("/api/books/search", params={"q": q, "limit": 50})
    assert response.status_code == 200, response.text
    return [item["display_title"] for item in response.json()["items"]]


async def test_substring_hit_masks_fuzzy_noise(admin_client: AsyncClient):
    await _seed(admin_client)
    # 三體 matches 三體 exactly; the trigram-adjacent 三十… decoy must
    # not ride along once the substring tiers have a hit.
    titles = await _search(admin_client, "三體")
    assert titles == [TITLES["short"]]


async def test_formatting_variants_do_not_mask_each_other(admin_client: AsyncClient):
    await _seed(admin_client)
    # The unspaced volume is an exact substring hit; the spaced sibling
    # matches only after normalization. Both must come back.
    titles = await _search(admin_client, "街角VR食堂")
    assert set(titles) == {TITLES["spaced"], TITLES["unspaced"]}


async def test_punctuation_insensitive(admin_client: AsyncClient):
    await _seed(admin_client)
    titles = await _search(admin_client, "明日明日又明日")
    assert titles == [TITLES["comma"]]


async def test_one_character_typo_falls_through_to_trigram(
    admin_client: AsyncClient,
):
    await _seed(admin_client)
    titles = await _search(admin_client, "明日明日又明天")
    assert TITLES["comma"] in titles


async def test_gibberish_returns_empty_not_everything(admin_client: AsyncClient):
    await _seed(admin_client)
    assert await _search(admin_client, "zzzz查無此書zzzz") == []
    # Punctuation-only input folds to nothing — '%%' must not match all.
    assert await _search(admin_client, "！！") == []
    # "C++" folds to a single character — the normalized tier must sit
    # out instead of substring-matching every title with a "c".
    assert await _search(admin_client, "C++") == []


async def test_multi_keyword_narrows_then_broadens(admin_client: AsyncClient):
    await _seed(admin_client)
    # Every-token AND: 街角 AND 深夜 keeps only the matching volume.
    titles = await _search(admin_client, "街角 深夜")
    assert titles == [TITLES["spaced"]]
    # No book has all tokens → broaden to any-token instead of empty.
    titles = await _search(admin_client, "三體 明日 不存在的關鍵詞")
    assert {TITLES["short"], TITLES["comma"]} <= set(titles)


async def test_keywords_match_tags(admin_client: AsyncClient):
    await _seed(admin_client)
    response = await admin_client.get(
        "/api/books/search", params={"q": "三體", "limit": 1}
    )
    book_id = response.json()["items"][0]["id"]
    response = await admin_client.put(
        f"/api/books/{book_id}/metadata", json={"tags": ["二戰", "歷史"]}
    )
    assert response.status_code == 200, response.text

    # Topic query: none of these words are in any title — the tag carries it.
    assert TITLES["short"] in await _search(admin_client, "二戰 納粹 軍事")
    # Single tag word matches via the phrase tier too.
    assert await _search(admin_client, "二戰") == [TITLES["short"]]


async def test_library_search_uses_the_same_tiers(admin_client: AsyncClient):
    library_id = await _seed(admin_client)
    response = await admin_client.get(
        f"/api/libraries/{library_id}/books",
        params={"search": "街角VR食堂"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total"] == 2
    assert {item["display_title"] for item in payload["items"]} == {
        TITLES["spaced"],
        TITLES["unspaced"],
    }


async def _seed_relevance(admin_client: AsyncClient) -> str:
    """Uploaded least-relevant first, so newest-first is the reverse of
    the relevance order and a silently ignored sort can't pass."""
    library_id = await create_library(admin_client, "Relevance")
    books = {}
    for i, title in enumerate(["我的食堂", "食堂番外", "食堂", "晚餐之書"]):
        books[title] = await upload_epub(
            admin_client,
            library_id,
            title=title,
            identifier=f"urn:uuid:00000000-0000-4000-8000-00000000020{i}",
        )
    # A book whose title doesn't mention the query, in a series named
    # exactly that — a search for the series itself.
    response = await admin_client.put(
        f"/api/books/{books['晚餐之書']['id']}/metadata", json={"series": "食堂"}
    )
    assert response.status_code == 200, response.text
    return library_id


RELEVANCE_ORDER = ["食堂", "晚餐之書", "食堂番外", "我的食堂"]


async def test_library_list_sorts_by_relevance(admin_client: AsyncClient):
    library_id = await _seed_relevance(admin_client)
    for url, params in [
        (f"/api/libraries/{library_id}/books", {}),
        ("/api/books/all", {"library": library_id}),
    ]:
        response = await admin_client.get(
            url, params={**params, "search": "食堂", "sort": "relevance"}
        )
        assert response.status_code == 200, response.text
        titles = [item["display_title"] for item in response.json()["items"]]
        assert titles == RELEVANCE_ORDER, url


async def test_grouped_feed_sorts_by_relevance(admin_client: AsyncClient):
    library_id = await _seed_relevance(admin_client)
    response = await admin_client.get(
        f"/api/libraries/{library_id}/feed",
        params={"search": "食堂", "sort": "relevance"},
    )
    assert response.status_code == 200, response.text
    units = [
        item["book"]["display_title"]
        if item["type"] == "book"
        else f"series:{item['series']['series_name']}"
        for item in response.json()["items"]
    ]
    assert units == ["食堂", "series:食堂", "食堂番外", "我的食堂"]


async def test_grouped_feed_uses_the_same_tiers(admin_client: AsyncClient):
    library_id = await _seed(admin_client)
    # Only the normalized tier matches the spaced volume — the grouped
    # view must find both, like the flat list does.
    response = await admin_client.get(
        f"/api/libraries/{library_id}/feed", params={"search": "街角VR食堂"}
    )
    assert response.status_code == 200, response.text
    assert {item["book"]["display_title"] for item in response.json()["items"]} == {
        TITLES["spaced"],
        TITLES["unspaced"],
    }
    response = await admin_client.get(
        f"/api/libraries/{library_id}/feed", params={"search": "zzzz查無此書zzzz"}
    )
    assert response.json() == {"items": [], "total": 0}


async def test_relevance_without_a_query_falls_back(admin_client: AsyncClient):
    library_id = await _seed_relevance(admin_client)
    for url in [
        f"/api/libraries/{library_id}/books",
        f"/api/libraries/{library_id}/feed",
    ]:
        response = await admin_client.get(url, params={"sort": "relevance"})
        assert response.status_code == 200, response.text
        assert response.json()["total"] == 4, url
