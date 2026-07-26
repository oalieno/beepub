"""MCP mount (/mcp) — bearer-token auth and the five read-only tools.

Talks raw JSON-RPC over the stateless streamable-HTTP transport, which
is exactly what an MCP client sends per request.
"""

import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, insert

from tests.integration.util import create_library, upload_epub

pytestmark = pytest.mark.integration

RPC_HEADERS = {"Accept": "application/json, text/event-stream"}


@pytest.fixture(autouse=True)
async def _mcp_endpoint_cleanup():
    # The endpoint parks a background task per event loop; cancel it
    # before pytest tears the loop down.
    yield
    from app.main import mcp_endpoint

    await mcp_endpoint.aclose()


async def _pat(client: AsyncClient) -> str:
    response = await client.post("/api/tokens", json={"name": "mcp"})
    assert response.status_code == 201, response.text
    return response.json()["token"]


async def _rpc(client: AsyncClient, token: str, method: str, params: dict) -> dict:
    response = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        headers={**RPC_HEADERS, "Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "error" not in payload, payload
    return payload["result"]


async def _call(client: AsyncClient, token: str, name: str, arguments: dict) -> dict:
    result = await _rpc(
        client, token, "tools/call", {"name": name, "arguments": arguments}
    )
    assert not result.get("isError"), result
    return result.get("structuredContent") or json.loads(result["content"][0]["text"])


async def _seed_book(admin_client: AsyncClient, library_id: str) -> str:
    created = await upload_epub(
        admin_client,
        library_id,
        title="測試之書",
        identifier="urn:uuid:00000000-0000-4000-8000-000000000201",
    )
    return created["id"]


async def _replace_chunks(book_id: str, chapters: list[tuple[str, str | None]]):
    """Overwrite the book's text chunks with controlled content."""
    from app.database import engine
    from app.models.book_text import BookTextChunk

    filler = "字" * 1500
    async with engine.begin() as conn:
        await conn.execute(
            delete(BookTextChunk.__table__).where(
                BookTextChunk.__table__.c.book_id == uuid.UUID(book_id)
            )
        )
        for index, (title, summary) in enumerate(chapters):
            await conn.execute(
                insert(BookTextChunk.__table__).values(
                    id=uuid.uuid4(),
                    book_id=uuid.UUID(book_id),
                    spine_index=index,
                    section_title=title,
                    text=f"{title}。{filler}",
                    char_offset=0,
                    summary=summary,
                )
            )


async def _set_progress(admin_client: AsyncClient, book_id: str, section: int):
    response = await admin_client.put(
        f"/api/books/{book_id}/progress",
        json={
            "cfi": f"epubcfi(/6/{(section + 1) * 2}!/4/2)",
            "percentage": 42,
            "section_index": section,
            "track_activity": False,
        },
    )
    assert response.status_code == 200, response.text


async def test_mcp_requires_a_bearer_token(admin_client: AsyncClient):
    # Cookie auth (which admin_client has) must NOT work on /mcp.
    response = await admin_client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        headers=RPC_HEADERS,
    )
    assert response.status_code == 401
    response = await admin_client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        headers={**RPC_HEADERS, "Authorization": "Bearer bpk_nope"},
    )
    assert response.status_code == 401


async def test_tools_are_listed(admin_client: AsyncClient):
    token = await _pat(admin_client)
    result = await _rpc(admin_client, token, "tools/list", {})
    names = {tool["name"] for tool in result["tools"]}
    assert names == {
        "search_books",
        "get_book",
        "search_passages",
        "get_chapter",
        "get_highlights",
    }


async def test_search_books_fuzzy_and_exclusion(
    admin_client: AsyncClient, user_client: AsyncClient
):
    library_id = await create_library(admin_client, "MCP")
    await _seed_book(admin_client, library_id)
    token = await _pat(admin_client)

    # Fuzzy: wrong middle character still finds the book.
    out = await _call(admin_client, token, "search_books", {"query": "測試の書"})
    assert [b["title"] for b in out["books"]] == ["測試之書"]

    # Broadened keyword search reports which tokens each book matched.
    out = await _call(admin_client, token, "search_books", {"query": "測試 幽靈關鍵詞"})
    assert out["books"][0]["match_reason"] == "matched 1/2 keywords: 測試"

    # A user excluded from the library sees nothing through MCP.
    me = (await user_client.get("/api/auth/me")).json()
    response = await admin_client.put(
        f"/api/admin/users/{me['id']}/library-access",
        json={"excluded_library_ids": [library_id]},
    )
    assert response.status_code == 200, response.text
    user_token = await _pat(user_client)
    out = await _call(user_client, user_token, "search_books", {"query": "測試"})
    assert out["books"] == []


async def test_get_book_spoiler_protection(admin_client: AsyncClient):
    library_id = await create_library(admin_client, "MCP")
    book_id = await _seed_book(admin_client, library_id)
    await _replace_chunks(
        book_id,
        [
            ("第一章", "一之摘要"),
            ("第二章", "二之摘要"),
            ("第三章", "三之摘要"),
            ("第四章", None),
        ],
    )
    token = await _pat(admin_client)

    # No stored progress → fail closed: TOC yes, summaries no.
    out = await _call(admin_client, token, "get_book", {"book": "測試之書"})
    assert len(out["toc"]) == 4
    assert out["chapter_summaries"] == []

    # Read up to chapter 2 → summaries strictly before it.
    await _set_progress(admin_client, book_id, 2)
    out = await _call(admin_client, token, "get_book", {"book": "測試之書"})
    assert [s["chapter"] for s in out["chapter_summaries"]] == [0, 1]
    assert out["chapter_summaries"][0]["summary"] == "一之摘要"
    assert any(t["is_current"] for t in out["toc"])
    # Chapter 2's summary exists but is past the position — "ready"
    # must not oversell what the spoiler gate will actually serve.
    assert [t["summary_status"] for t in out["toc"]] == [
        "ready",
        "ready",
        "spoiler_locked",
        "missing",
    ]
    assert out["generating"] is False

    # spoilers="all" returns everything that exists — and nothing is
    # spoiler_locked anymore.
    out = await _call(
        admin_client, token, "get_book", {"book": "測試之書", "spoilers": "all"}
    )
    assert [s["chapter"] for s in out["chapter_summaries"]] == [0, 1, 2]
    assert [t["summary_status"] for t in out["toc"]] == [
        "ready",
        "ready",
        "ready",
        "missing",
    ]


async def test_backmatter_is_not_content(admin_client: AsyncClient):
    library_id = await create_library(admin_client, "MCP")
    book_id = await _seed_book(admin_client, library_id)
    await _replace_chunks(
        book_id,
        [("第一章", "一之摘要"), ("上冊註釋", None), ("謝詞", None)],
    )
    await _set_progress(admin_client, book_id, 2)
    token = await _pat(admin_client)

    out = await _call(admin_client, token, "get_book", {"book": book_id})
    assert [t["summary_status"] for t in out["toc"]] == ["ready", "none", "none"]
    # Nothing content-like is missing → no generation gets enqueued for
    # a 170k-char notes section.
    assert out["generating"] is False


async def test_get_book_reports_generating_gaps(admin_client: AsyncClient):
    library_id = await create_library(admin_client, "MCP")
    book_id = await _seed_book(admin_client, library_id)
    await _replace_chunks(
        book_id, [("第一章", "一之摘要"), ("第二章", None), ("第三章", None)]
    )
    await _set_progress(admin_client, book_id, 2)
    token = await _pat(admin_client)

    out = await _call(admin_client, token, "get_book", {"book": book_id})
    # The gap before the reading position is being filled in; the
    # chapter past the position is just missing.
    assert out["generating"] is True
    assert [t["summary_status"] for t in out["toc"]] == [
        "ready",
        "generating",
        "missing",
    ]


async def test_get_chapter_slices(admin_client: AsyncClient):
    library_id = await create_library(admin_client, "MCP")
    book_id = await _seed_book(admin_client, library_id)
    await _replace_chunks(book_id, [("第一章", None)])
    token = await _pat(admin_client)

    out = await _call(
        admin_client,
        token,
        "get_chapter",
        {"book": book_id, "chapter": 0, "max_chars": 500},
    )
    assert out["chapter_title"] == "第一章"
    assert len(out["text"]) == 500
    assert out["has_more"] is True

    rest = await _call(
        admin_client,
        token,
        "get_chapter",
        {"book": book_id, "chapter": 0, "offset": out["next_offset"]},
    )
    assert rest["offset"] == 500

    missing = await _call(
        admin_client, token, "get_chapter", {"book": book_id, "chapter": 99}
    )
    assert "error" in missing


async def test_search_passages_and_highlights(admin_client: AsyncClient):
    library_id = await create_library(admin_client, "MCP")
    book_id = await _seed_book(admin_client, library_id)
    await _replace_chunks(book_id, [("第一章", None), ("神秘的鳳梨事件", None)])
    token = await _pat(admin_client)

    out = await _call(admin_client, token, "search_passages", {"query": "神秘的鳳梨"})
    assert out["match"] == "exact"  # embedding not configured in tests
    assert out["passages"][0]["chapter"] == 1
    assert "神秘的鳳梨" in out["passages"][0]["snippet"]
    assert out["passages"][0]["chapter_title"] == "神秘的鳳梨事件"

    response = await admin_client.post(
        f"/api/books/{book_id}/highlights",
        json={
            "cfi_range": "epubcfi(/6/4!/4/2,/1:0,/1:8)",
            "text": "神秘的鳳梨",
            "note": "重要線索",
        },
    )
    assert response.status_code in (200, 201), response.text

    out = await _call(admin_client, token, "get_highlights", {"book": "測試之書"})
    assert len(out["highlights"]) == 1
    assert out["highlights"][0]["text"] == "神秘的鳳梨"
    assert out["highlights"][0]["note"] == "重要線索"
