"""The library table's backend: a page opened around a book, and batch
metadata edits and deletes."""

import uuid

import pytest
from sqlalchemy import update

from app.database import AsyncSessionLocal
from app.models.book import Book
from tests.integration.util import create_library

pytestmark = pytest.mark.integration


async def _physical(client, library_id: str, title: str, **fields) -> str:
    response = await client.post(
        "/api/books/physical",
        json={"library_id": library_id, "title": title, **fields},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _as_own_values(book_ids: list[str], *, calibre: bool = False) -> None:
    """Move what was typed at creation into the book's own fields, as if it
    came from the file (or from Calibre) — the overrides start empty."""
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Book)
            .where(Book.id.in_([uuid.UUID(i) for i in book_ids]))
            .values(
                epub_title=Book.title,
                epub_authors=Book.authors,
                epub_publisher=Book.publisher,
                epub_series=Book.series,
                epub_series_index=Book.series_index,
                title=None,
                authors=None,
                publisher=None,
                series=None,
                series_index=None,
                field_sources=None,
                calibre_id=1 if calibre else None,
            )
        )
        await db.commit()


async def _get(client, book_id: str) -> dict:
    response = await client.get(f"/api/books/{book_id}")
    assert response.status_code == 200, response.text
    return response.json()


async def _shelf(client) -> tuple[str, list[str]]:
    """A library of 30 books: two series (one of them with gaps) and loose
    books, so every ordering has ties and missing values to get through."""
    library_id = await create_library(client, "Batch Shelf")
    ids = []
    for n in range(1, 31):
        fields: dict = {"authors": [f"作者{n % 4}"]}
        if n <= 12:
            fields |= {"series": "星海旅人", "series_index": n}
        elif n <= 18:
            fields |= {"series": "霧港偵探社"}
        ids.append(await _physical(client, library_id, f"卷 {n:02d}", **fields))
    await _as_own_values(ids)
    return library_id, ids


@pytest.mark.parametrize(
    "sort,order",
    [
        ("display_title", "asc"),
        ("display_title", "desc"),
        ("added_at", "desc"),
        ("series_index", "asc"),
        ("series_index", "desc"),
        ("popularity_score", "desc"),
    ],
)
async def test_around_opens_the_page_on_the_book(admin_client, sort, order):
    library_id, ids = await _shelf(admin_client)
    params = {"library": library_id, "sort": sort, "order": order}
    response = await admin_client.get("/api/books", params={**params, "limit": 200})
    whole = [b["id"] for b in response.json()["items"]]
    assert sorted(whole) == sorted(ids)

    for target in (whole[0], whole[7], whole[25]):
        response = await admin_client.get(
            "/api/books", params={**params, "around": target, "limit": 10}
        )
        body = response.json()
        index = whole.index(target)
        assert body["around_index"] == index
        assert body["offset"] == max(0, index - 20)
        # The page is the whole list's own slice there.
        assert [b["id"] for b in body["items"]] == whole[
            body["offset"] : body["offset"] + 10
        ]


async def test_around_a_book_not_listed_pages_as_asked(admin_client):
    library_id, ids = await _shelf(admin_client)
    response = await admin_client.get(
        "/api/books",
        params={
            "library": library_id,
            "series": "霧港偵探社",
            "around": ids[0],  # 星海旅人 1, filtered out
            "offset": 2,
        },
    )
    body = response.json()
    assert body["around_index"] is None
    assert body["offset"] == 2
    assert body["total"] == 6

    # A search starts at its best match: around does not apply.
    response = await admin_client.get(
        "/api/books",
        params={
            "library": library_id,
            "search": "卷",
            "sort": "relevance",
            "around": ids[20],
        },
    )
    body = response.json()
    assert body["around_index"] is None
    assert body["offset"] == 0


async def test_batch_series_keeps_numbers_and_marks_provenance(admin_client):
    library_id = await create_library(admin_client, "Series Shelf")
    first = await _physical(
        admin_client, library_id, "星海旅入 1", series="星海旅入", series_index=1
    )
    second = await _physical(
        admin_client, library_id, "星海旅人 2", series="星海旅人", series_index=2
    )
    third = await _physical(admin_client, library_id, "星海旅人 3")
    await _as_own_values([first, second, third])

    response = await admin_client.patch(
        "/api/books/metadata",
        json={
            "book_ids": [first, second, third],
            "series": " 星海旅人 ",
            "series_indexes": {third: 3},
        },
    )
    assert response.status_code == 200, response.text
    returned = {b["id"]: b for b in response.json()}
    assert set(returned) == {first, second, third}
    for book_id, number in ((first, 1), (second, 2), (third, 3)):
        book = await _get(admin_client, book_id)
        assert book["display_series"] == "星海旅人"
        # A book not given a number keeps the one it showed.
        assert book["display_series_index"] == number
    for book_id in (first, third):
        assert (await _get(admin_client, book_id))["field_sources"] == {
            "series": "manual"
        }
    # The second already was 星海旅人 #2 of its own: no override for it.
    book = await _get(admin_client, second)
    assert book["series"] is None and not book["field_sources"]

    # A blank series drops the override: each shows its own again.
    response = await admin_client.patch(
        "/api/books/metadata",
        json={"book_ids": [first, third], "series": "  "},
    )
    assert response.status_code == 200, response.text
    book = await _get(admin_client, first)
    assert book["series"] is None and book["series_index"] is None
    assert book["display_series"] == "星海旅入"
    assert book["display_series_index"] == 1
    assert not book["field_sources"]
    book = await _get(admin_client, third)
    assert book["display_series"] is None


async def test_batch_authors_and_publisher(admin_client):
    library_id = await create_library(admin_client, "People Shelf")
    ids = [
        await _physical(
            admin_client, library_id, f"書 {n}", authors=["原作者"], publisher="原社"
        )
        for n in (1, 2)
    ]
    await _as_own_values(ids)
    # Fields left out are not touched; field_sources keeps other keys.
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Book)
            .where(Book.id == uuid.UUID(ids[0]))
            .values(description="自訂簡介", field_sources={"description": "readmoo"})
        )
        await db.commit()

    response = await admin_client.patch(
        "/api/books/metadata",
        json={"book_ids": ids, "authors": [" 甲 ", "", "乙"], "publisher": "新社"},
    )
    assert response.status_code == 200, response.text
    book = await _get(admin_client, ids[0])
    assert book["display_authors"] == ["甲", "乙"]
    assert book["publisher"] == "新社"
    assert book["description"] == "自訂簡介"
    assert book["field_sources"] == {
        "description": "readmoo",
        "authors": "manual",
        "publisher": "manual",
    }

    response = await admin_client.patch(
        "/api/books/metadata",
        json={"book_ids": ids, "authors": ["  "], "publisher": ""},
    )
    assert response.status_code == 200, response.text
    book = await _get(admin_client, ids[0])
    assert book["authors"] is None and book["publisher"] is None
    assert book["display_authors"] == ["原作者"]
    assert book["field_sources"] == {"description": "readmoo"}


async def test_batch_edit_gives_calibre_books_overrides_only(admin_client):
    library_id = await create_library(admin_client, "Calibre-ish")
    book_id = await _physical(admin_client, library_id, "卡書", publisher="原社")
    await _as_own_values([book_id], calibre=True)

    response = await admin_client.patch(
        "/api/books/metadata", json={"book_ids": [book_id], "publisher": "覆寫社"}
    )
    assert response.status_code == 200, response.text
    book = await _get(admin_client, book_id)
    assert book["publisher"] == "覆寫社"
    assert book["epub_publisher"] == "原社"


async def test_batch_edit_is_all_or_nothing(admin_client, user_client):
    library_id = await create_library(admin_client, "Strict Shelf")
    book_id = await _physical(admin_client, library_id, "原書名", publisher="原社")
    missing = str(uuid.uuid4())

    response = await admin_client.patch(
        "/api/books/metadata",
        json={"book_ids": [book_id, missing], "publisher": "新社"},
    )
    assert response.status_code == 404
    assert missing in response.json()["detail"]
    assert (await _get(admin_client, book_id))["publisher"] == "原社"

    response = await admin_client.patch(
        "/api/books/metadata",
        json={"book_ids": [book_id], "series_indexes": {book_id: 2}},
    )
    assert response.status_code == 422

    response = await user_client.patch(
        "/api/books/metadata", json={"book_ids": [book_id], "publisher": "新社"}
    )
    assert response.status_code == 403


async def test_batch_delete(admin_client, user_client):
    library_id = await create_library(admin_client, "Delete Shelf")
    ids = [await _physical(admin_client, library_id, f"刪 {n}") for n in (1, 2, 3)]
    await _as_own_values([ids[2]], calibre=True)

    response = await user_client.post("/api/books/delete", json={"book_ids": ids[:2]})
    assert response.status_code == 403

    # A Calibre book in the batch stops all of it: the sync would bring it back.
    response = await admin_client.post("/api/books/delete", json={"book_ids": ids})
    assert response.status_code == 409
    for book_id in ids:
        await _get(admin_client, book_id)

    response = await admin_client.post(
        "/api/books/delete", json={"book_ids": [ids[0], str(uuid.uuid4())]}
    )
    assert response.status_code == 404
    await _get(admin_client, ids[0])

    response = await admin_client.post("/api/books/delete", json={"book_ids": ids[:2]})
    assert response.status_code == 204
    for book_id in ids[:2]:
        response = await admin_client.get(f"/api/books/{book_id}")
        assert response.status_code == 404
    await _get(admin_client, ids[2])


async def test_batch_title_is_for_one_book_and_own_values_store_nothing(
    admin_client,
):
    library_id = await create_library(admin_client, "Title Shelf")
    ids = [
        await _physical(admin_client, library_id, f"小魔法書！ {n}", authors=["虎走"])
        for n in (1, 2)
    ]
    await _as_own_values(ids)

    response = await admin_client.patch(
        "/api/books/metadata", json={"book_ids": ids, "title": "同一個書名"}
    )
    assert response.status_code == 422

    response = await admin_client.patch(
        "/api/books/metadata", json={"book_ids": [ids[0]], "title": " 小魔法書！1 "}
    )
    assert response.status_code == 200, response.text
    book = await _get(admin_client, ids[0])
    assert book["title"] == "小魔法書！1"
    assert book["field_sources"] == {"title": "manual"}

    # Typed back to the book's own: the override goes.
    response = await admin_client.patch(
        "/api/books/metadata",
        json={"book_ids": [ids[0]], "title": "小魔法書！ 1", "authors": ["虎走"]},
    )
    assert response.status_code == 200, response.text
    book = await _get(admin_client, ids[0])
    assert book["title"] is None and book["authors"] is None
    assert not book["field_sources"]


async def test_batch_titles_one_per_book(admin_client):
    library_id = await create_library(admin_client, "Replace Shelf")
    ids = [
        await _physical(admin_client, library_id, f"銀河觀測手記 {n}")
        for n in (1, 2, 3)
    ]
    await _as_own_values(ids)

    # A book not named in titles is left alone; a blank one goes back to
    # its own title; a title the book has of its own stores nothing.
    response = await admin_client.patch(
        "/api/books/metadata",
        json={
            "book_ids": ids,
            "titles": {ids[0]: "銀河觀測手記 01", ids[1]: "銀河觀測手記 2"},
        },
    )
    assert response.status_code == 200, response.text
    first, second, third = [await _get(admin_client, i) for i in ids]
    assert first["title"] == "銀河觀測手記 01"
    assert first["field_sources"] == {"title": "manual"}
    assert second["title"] is None and not second["field_sources"]
    assert third["title"] is None

    response = await admin_client.patch(
        "/api/books/metadata", json={"book_ids": ids, "titles": {ids[0]: "  "}}
    )
    assert response.status_code == 200, response.text
    first = await _get(admin_client, ids[0])
    assert first["title"] is None and first["display_title"] == "銀河觀測手記 1"

    for body in (
        {"book_ids": ids[:1], "titles": {ids[1]: "別本的書名"}},
        {"book_ids": ids[:1], "title": "甲", "titles": {ids[0]: "乙"}},
        {"book_ids": ids[:1], "titles": {ids[0]: "長" * 501}},
    ):
        response = await admin_client.patch("/api/books/metadata", json=body)
        assert response.status_code == 422, body


async def test_batch_tags_added_and_removed(admin_client):
    library_id = await create_library(admin_client, "Tag Shelf")
    ids = [
        await _physical(admin_client, library_id, f"潮汐圖鑑 {n}") for n in (1, 2, 3)
    ]
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Book)
            .where(Book.id == uuid.UUID(ids[0]))
            .values(epub_tags=["海洋", "圖鑑"])
        )
        await db.execute(
            update(Book).where(Book.id == uuid.UUID(ids[1])).values(tags=["待整理"])
        )
        await db.commit()

    response = await admin_client.patch(
        "/api/books/metadata",
        json={
            "book_ids": ids,
            "tags_add": ["科普", " 海洋 "],
            "tags_remove": ["待整理"],
        },
    )
    assert response.status_code == 200, response.text
    first, second, third = [await _get(admin_client, i) for i in ids]
    # Each book keeps what it had; a tag it already has is not doubled.
    assert first["display_tags"] == ["海洋", "圖鑑", "科普"]
    assert first["epub_tags"] == ["海洋", "圖鑑"]
    assert first["field_sources"] == {"tags": "manual"}
    assert second["display_tags"] == ["科普", "海洋"]
    assert third["display_tags"] == ["科普", "海洋"]

    # Taking off what was added leaves the first book on its own tags
    # again, with no override; a tag no book has changes nothing.
    response = await admin_client.patch(
        "/api/books/metadata",
        json={"book_ids": ids[:1], "tags_remove": ["科普", "沒有這個"]},
    )
    assert response.status_code == 200, response.text
    first = await _get(admin_client, ids[0])
    assert first["tags"] is None and not first["field_sources"]
    assert first["display_tags"] == ["海洋", "圖鑑"]

    response = await admin_client.patch(
        "/api/books/metadata",
        json={"book_ids": ids, "tags_add": ["科普"], "tags_remove": ["科普"]},
    )
    assert response.status_code == 422
