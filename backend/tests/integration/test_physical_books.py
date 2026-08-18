"""Physical (file-less) books: creation, file-endpoint gating, OPDS
exclusion, format filtering, and the ISBN prefill lookup."""

import pytest

from tests.integration.conftest import ADMIN_CREDENTIALS
from tests.integration.util import create_library, upload_epub

pytestmark = pytest.mark.integration

ADMIN_BASIC = (ADMIN_CREDENTIALS["username"], ADMIN_CREDENTIALS["password"])


async def create_physical(client, library_id: str, **overrides) -> dict:
    payload = {
        "library_id": library_id,
        "title": "紙本測試書",
        "authors": ["Paper Author"],
        "isbn": "9789571234567",
        **overrides,
    }
    response = await client.post("/api/books/physical", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def test_create_physical_book(admin_client):
    library_id = await create_library(admin_client, "Physical Shelf")
    book = await create_physical(admin_client, library_id)

    assert book["format"] == "physical"
    assert book["file_size"] is None
    assert book["display_title"] == "紙本測試書"
    assert book["display_authors"] == ["Paper Author"]
    assert book["epub_isbn"] == "9789571234567"

    detail = await admin_client.get(f"/api/books/{book['id']}")
    assert detail.status_code == 200
    assert detail.json()["format"] == "physical"

    listing = await admin_client.get("/api/books/all")
    assert book["id"] in [b["id"] for b in listing.json()["items"]]


async def test_create_physical_requires_upload_permission(user_client):
    response = await user_client.post(
        "/api/books/physical",
        json={"library_id": "00000000-0000-0000-0000-000000000000", "title": "x"},
    )
    assert response.status_code == 403


async def test_file_endpoints_are_gated(admin_client):
    library_id = await create_library(admin_client)
    book = await create_physical(admin_client, library_id)

    for path in ("file", "content/OEBPS/ch1.xhtml", "images"):
        response = await admin_client.get(f"/api/books/{book['id']}/{path}")
        assert response.status_code == 409, path


async def test_interactions_work_without_a_file(admin_client):
    library_id = await create_library(admin_client)
    book = await create_physical(admin_client, library_id)
    book_id = book["id"]

    status_resp = await admin_client.put(
        f"/api/books/{book_id}/reading-status",
        json={"reading_status": "currently_reading"},
    )
    assert status_resp.status_code == 200

    notes_resp = await admin_client.put(
        f"/api/books/{book_id}/notes", json={"notes": "第三章看完了"}
    )
    assert notes_resp.status_code == 200

    interaction = (await admin_client.get(f"/api/books/{book_id}/interaction")).json()
    assert interaction["reading_status"] == "currently_reading"
    assert interaction["notes"] == "第三章看完了"


async def test_opds_excludes_physical_books(admin_client):
    library_id = await create_library(admin_client, "Mixed")
    epub = await upload_epub(admin_client, library_id, title="Real EPUB")
    physical = await create_physical(admin_client, library_id)

    response = await admin_client.get(
        f"/api/opds/libraries/{library_id}", auth=ADMIN_BASIC
    )
    assert response.status_code == 200
    assert epub["id"] in response.text
    assert physical["id"] not in response.text


async def test_format_filter_on_book_lists(admin_client):
    library_id = await create_library(admin_client, "Filter Lib")
    epub = await upload_epub(admin_client, library_id, title="Filter EPUB")
    physical = await create_physical(admin_client, library_id)

    scoped = await admin_client.get(
        f"/api/libraries/{library_id}/books?format=physical"
    )
    assert [b["id"] for b in scoped.json()["items"]] == [physical["id"]]
    assert scoped.json()["total"] == 1

    global_list = await admin_client.get("/api/books/all?format=physical")
    ids = [b["id"] for b in global_list.json()["items"]]
    assert physical["id"] in ids
    assert epub["id"] not in ids


async def test_delete_physical_book(admin_client):
    library_id = await create_library(admin_client)
    book = await create_physical(admin_client, library_id)

    response = await admin_client.delete(f"/api/books/{book['id']}")
    assert response.status_code == 204
    assert (await admin_client.get(f"/api/books/{book['id']}")).status_code == 404


async def test_cover_url_host_allowlist(admin_client):
    library_id = await create_library(admin_client)
    response = await admin_client.post(
        "/api/books/physical",
        json={
            "library_id": library_id,
            "title": "SSRF probe",
            "cover_url": "https://internal.example.com/secret.png",
        },
    )
    assert response.status_code == 422


async def test_isbn_lookup_returns_per_source_results(admin_client, monkeypatch):
    from app.plugins.metadata import BookRecord

    async def fake_lookup_all(query, settings: dict, *, resolver=None):
        assert query.isbn == "9789571234567"
        return [
            (
                "google_books",
                BookRecord(
                    title="查到的書",
                    authors=["某作者"],
                    publisher="某出版社",
                    description="簡介",
                    published_date="2020-01-01",
                    language="zh-TW",
                    cover_url="https://books.google.com/books/content?id=x",
                ),
            ),
            (
                "books_tw",
                BookRecord(
                    title="查到的書（台版）",
                    authors=["某作者"],
                    publisher="某出版社",
                    cover_url="https://im1.book.com.tw/image/getImage?i=x",
                ),
            ),
            # Cover-only degradation: feeds covers, never a source pill.
            (
                "open_library",
                BookRecord(cover_url="https://covers.openlibrary.org/b/isbn/x-L.jpg"),
            ),
        ]

    monkeypatch.setattr("app.routers.books.lookup_all", fake_lookup_all)
    response = await admin_client.get("/api/books/metadata-lookup?isbn=9789571234567")
    assert response.status_code == 200, response.text
    data = response.json()

    assert [r["source"] for r in data["results"]] == ["google_books", "books_tw"]
    assert data["results"][0]["title"] == "查到的書"
    assert data["results"][1]["label"] == "博客來"
    assert [c["source"] for c in data["covers"]] == [
        "google_books",
        "books_tw",
        "open_library",
    ]


async def test_lookup_empty_is_still_200_and_no_clues_is_422(admin_client, monkeypatch):
    async def fake_lookup_all(query, settings: dict, *, resolver=None):
        return []

    monkeypatch.setattr("app.routers.books.lookup_all", fake_lookup_all)
    response = await admin_client.get("/api/books/metadata-lookup?isbn=0000000000")
    assert response.status_code == 200
    assert response.json() == {"results": [], "covers": []}

    response = await admin_client.get("/api/books/metadata-lookup")
    assert response.status_code == 422


async def test_lookup_accepts_title_and_url_clues(admin_client, monkeypatch):
    from app.plugins.metadata import BookRecord

    seen_queries = []

    async def fake_lookup_all(query, settings: dict, *, resolver=None):
        seen_queries.append(query)
        return [("readmoo", BookRecord(title="神", description="全文"))]

    monkeypatch.setattr("app.routers.books.lookup_all", fake_lookup_all)

    response = await admin_client.get(
        "/api/books/metadata-lookup?title=%E7%A5%9E&author=%E8%91%A3%E5%95%9F%E7%AB%A0"
    )
    assert response.status_code == 200
    assert response.json()["results"][0]["source"] == "readmoo"
    assert seen_queries[-1].title == "神"
    assert seen_queries[-1].authors == ["董啟章"]

    response = await admin_client.get(
        "/api/books/metadata-lookup?url=https://readmoo.com/book/210071675000101"
    )
    assert response.status_code == 200
    assert seen_queries[-1].url == "https://readmoo.com/book/210071675000101"


async def test_metadata_search_lists_per_source_candidates(admin_client, monkeypatch):
    from app.plugins.metadata import SearchCandidate

    async def fake_search_all(query, settings: dict):
        assert query.title == "神"
        assert query.authors == ["董啟章"]
        return [
            (
                "readmoo",
                [
                    SearchCandidate(
                        url="https://readmoo.com/book/210071675000101", title="神"
                    ),
                    SearchCandidate(url="https://readmoo.com/book/2", title=""),
                ],
            ),
            # google refs are bare volume ids — the page url derives
            # from the plugin's url_prefix.
            ("google_books", [SearchCandidate(url="o5zjzwEACAAJ", title="神")]),
        ]

    monkeypatch.setattr("app.routers.books.search_all", fake_search_all)
    response = await admin_client.get(
        "/api/books/metadata-search?title=%E7%A5%9E&author=%E8%91%A3%E5%95%9F%E7%AB%A0"
    )
    assert response.status_code == 200, response.text
    candidates = response.json()["candidates"]

    # The untitled hit is dropped — nothing for the user to judge.
    assert [(c["source"], c["ref"]) for c in candidates] == [
        ("readmoo", "https://readmoo.com/book/210071675000101"),
        ("google_books", "o5zjzwEACAAJ"),
    ]
    assert candidates[0]["url"] == "https://readmoo.com/book/210071675000101"
    assert candidates[1]["url"] == "https://books.google.com/books?id=o5zjzwEACAAJ"
    assert candidates[1]["label"] == "Google Books"

    response = await admin_client.get("/api/books/metadata-search")
    assert response.status_code == 422


async def test_lookup_pick_resolves_on_the_owning_plugin_only(
    admin_client, monkeypatch
):
    from app.plugins.metadata import BookRecord

    picks = []

    async def fake_resolve_one(plugin, query, *, resolver=None):
        picks.append((plugin.name, query))
        return BookRecord(title="神", description="全文")

    async def fail_lookup_all(query, settings: dict, *, resolver=None):
        raise AssertionError("a pick must not fan out")

    monkeypatch.setattr("app.routers.books.resolve_one", fake_resolve_one)
    monkeypatch.setattr("app.routers.books.lookup_all", fail_lookup_all)

    # A full-URL ref (readmoo) and a bare-id ref (google) both pass the
    # plugin's own shape validation; the original clues ride along.
    response = await admin_client.get(
        "/api/books/metadata-lookup?source=readmoo"
        "&ref=https://readmoo.com/book/210071675000101&title=%E7%A5%9E"
    )
    assert response.status_code == 200, response.text
    assert [r["source"] for r in response.json()["results"]] == ["readmoo"]
    assert picks[-1][0] == "readmoo"
    assert picks[-1][1].url == "https://readmoo.com/book/210071675000101"
    assert picks[-1][1].title == "神"

    response = await admin_client.get(
        "/api/books/metadata-lookup?source=google_books&ref=o5zjzwEACAAJ"
    )
    assert response.status_code == 200
    assert picks[-1][1].url == "o5zjzwEACAAJ"


async def test_lookup_pick_rejects_bad_source_and_foreign_ref(
    admin_client, monkeypatch
):
    async def fake_resolve_one(plugin, query, *, resolver=None):
        raise AssertionError("invalid picks must not resolve")

    monkeypatch.setattr("app.routers.books.resolve_one", fake_resolve_one)

    # source and ref go together.
    response = await admin_client.get("/api/books/metadata-lookup?source=readmoo")
    assert response.status_code == 422

    response = await admin_client.get("/api/books/metadata-lookup?source=nope&ref=1")
    assert response.status_code == 400

    # A ref outside the plugin's own ID shape (SSRF guard).
    response = await admin_client.get(
        "/api/books/metadata-lookup?source=readmoo&ref=https://evil.example/x"
    )
    assert response.status_code == 400

    # Disabled source → 409, same as manual linking.
    resp = await admin_client.put(
        "/api/admin/settings",
        json={"metadata_source_readmoo_enabled": "false"},
    )
    assert resp.status_code == 200
    try:
        response = await admin_client.get(
            "/api/books/metadata-lookup?source=readmoo"
            "&ref=https://readmoo.com/book/210071675000101"
        )
        assert response.status_code == 409
    finally:
        await admin_client.put(
            "/api/admin/settings",
            json={"metadata_source_readmoo_enabled": "true"},
        )
