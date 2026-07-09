"""OPDS catalog — Basic-auth Atom feeds for e-reader clients."""

import xml.etree.ElementTree as ET

import pytest

from tests.integration.conftest import ADMIN_CREDENTIALS, USER_CREDENTIALS
from tests.integration.util import create_library, upload_epub

pytestmark = pytest.mark.integration

ATOM = "{http://www.w3.org/2005/Atom}"
ACQUISITION_REL = "http://opds-spec.org/acquisition"

ADMIN_BASIC = (ADMIN_CREDENTIALS["username"], ADMIN_CREDENTIALS["password"])
USER_BASIC = (USER_CREDENTIALS["username"], USER_CREDENTIALS["password"])


def _entries(response) -> list[ET.Element]:
    assert response.status_code == 200, response.text
    assert "application/atom+xml" in response.headers["content-type"]
    return ET.fromstring(response.text).findall(f"{ATOM}entry")


def _links(element, rel: str) -> list[str]:
    return [
        link.get("href")
        for link in element.iter(f"{ATOM}link")
        if link.get("rel") == rel
    ]


async def test_requires_basic_auth(client):
    response = await client.get("/api/opds")
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"].startswith("Basic")


async def test_rejects_wrong_password(admin_client):
    response = await admin_client.get(
        "/api/opds", auth=(ADMIN_CREDENTIALS["username"], "wrong-password")
    )
    assert response.status_code == 401


async def test_cookie_session_is_not_enough(admin_client):
    # admin_client carries the web session cookie jar; OPDS must ignore it.
    response = await admin_client.get("/api/opds")
    assert response.status_code == 401


async def test_root_lists_libraries(admin_client):
    library_id = await create_library(admin_client, "Shelf")

    entries = _entries(await admin_client.get("/api/opds", auth=ADMIN_BASIC))
    titles = [entry.findtext(f"{ATOM}title") for entry in entries]
    assert titles == ["All books", "Shelf"]
    assert _links(entries[1], "subsection") == [f"/api/opds/libraries/{library_id}"]


async def test_library_feed_entry_and_download(admin_client):
    library_id = await create_library(admin_client)
    book = await upload_epub(
        admin_client, library_id, title="OPDS Book", authors=("Jane Doe",)
    )

    feed = await admin_client.get(f"/api/opds/libraries/{library_id}", auth=ADMIN_BASIC)
    entries = _entries(feed)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.findtext(f"{ATOM}title") == "OPDS Book"
    assert entry.findtext(f"{ATOM}author/{ATOM}name") == "Jane Doe"
    assert entry.findtext(f"{ATOM}id") == f"urn:uuid:{book['id']}"

    (acquisition_href,) = _links(entry, ACQUISITION_REL)
    download = await admin_client.get(acquisition_href, auth=ADMIN_BASIC)
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/epub+zip"
    assert download.content[:2] == b"PK"

    (cover_href,) = _links(entry, "http://opds-spec.org/image")
    cover = await admin_client.get(cover_href, auth=ADMIN_BASIC)
    assert cover.status_code == 200
    assert cover.headers["content-type"] == "image/jpeg"


async def test_search_matches_title(admin_client):
    library_id = await create_library(admin_client)
    await upload_epub(admin_client, library_id, title="Vertical Writing Primer")
    await upload_epub(admin_client, library_id, title="Unrelated Novel")

    entries = _entries(
        await admin_client.get("/api/opds/search?q=Vertical", auth=ADMIN_BASIC)
    )
    assert [e.findtext(f"{ATOM}title") for e in entries] == ["Vertical Writing Primer"]


async def test_download_requires_permission(admin_client, user_client):
    library_id = await create_library(admin_client)
    book = await upload_epub(admin_client, library_id)

    # Catalog browsing works for a regular user without download rights…
    entries = _entries(await user_client.get("/api/opds/all", auth=USER_BASIC))
    assert len(entries) == 1

    # …but acquisition is gated on can_download, exactly like the web UI.
    response = await user_client.get(
        f"/api/opds/books/{book['id']}/file", auth=USER_BASIC
    )
    assert response.status_code == 403


async def test_excluded_library_is_invisible(admin_client, user_client):
    lib_a = await create_library(admin_client, "Visible")
    lib_b = await create_library(admin_client, "Hidden")
    await upload_epub(admin_client, lib_a, title="Public Book")
    hidden = await upload_epub(admin_client, lib_b, title="Secret Book")

    me = await user_client.get("/api/auth/me")
    response = await admin_client.put(
        f"/api/admin/users/{me.json()['id']}/library-access",
        json={"excluded_library_ids": [lib_b]},
    )
    assert response.status_code == 200, response.text

    root_titles = [
        e.findtext(f"{ATOM}title")
        for e in _entries(await user_client.get("/api/opds", auth=USER_BASIC))
    ]
    assert "Hidden" not in root_titles

    all_titles = [
        e.findtext(f"{ATOM}title")
        for e in _entries(await user_client.get("/api/opds/all", auth=USER_BASIC))
    ]
    assert all_titles == ["Public Book"]

    assert (
        await user_client.get(f"/api/opds/libraries/{lib_b}", auth=USER_BASIC)
    ).status_code == 404
    assert (
        await user_client.get(f"/api/opds/books/{hidden['id']}/cover", auth=USER_BASIC)
    ).status_code == 404


async def test_pagination_links(admin_client, monkeypatch):
    from app.routers import opds

    monkeypatch.setattr(opds, "PAGE_SIZE", 2)
    library_id = await create_library(admin_client)
    for i in range(3):
        await upload_epub(
            admin_client,
            library_id,
            title=f"Book {i}",
            identifier=f"urn:uuid:00000000-0000-4000-8000-00000000000{i}",
        )

    first = await admin_client.get("/api/opds/all", auth=ADMIN_BASIC)
    feed = ET.fromstring(first.text)
    assert len(feed.findall(f"{ATOM}entry")) == 2
    assert _links(feed, "next") == ["/api/opds/all?page=2"]

    second = await admin_client.get("/api/opds/all?page=2", auth=ADMIN_BASIC)
    feed = ET.fromstring(second.text)
    assert len(feed.findall(f"{ATOM}entry")) == 1
    assert _links(feed, "next") == []
    assert _links(feed, "previous") == ["/api/opds/all?page=1"]


async def test_opds_served_on_both_prefixes(admin_client):
    """/opds is the e-reader convention; hrefs follow the entry prefix."""
    library_id = await create_library(admin_client, "Shelf")
    book = await upload_epub(admin_client, library_id, title="Alias Book")

    entries = _entries(await admin_client.get("/opds", auth=ADMIN_BASIC))
    assert _links(entries[0], "subsection") == ["/opds/all"]
    assert _links(entries[1], "subsection") == [f"/opds/libraries/{library_id}"]

    feed_entries = _entries(await admin_client.get("/opds/all", auth=ADMIN_BASIC))
    (acquisition_href,) = _links(feed_entries[0], ACQUISITION_REL)
    assert acquisition_href == f"/opds/books/{book['id']}/file"
    download = await admin_client.get(acquisition_href, auth=ADMIN_BASIC)
    assert download.status_code == 200

    # The legacy prefix keeps working and keeps its own hrefs.
    entries = _entries(await admin_client.get("/api/opds", auth=ADMIN_BASIC))
    assert _links(entries[0], "subsection") == ["/api/opds/all"]


async def test_opensearch_description(admin_client):
    response = await admin_client.get("/api/opds/opensearch.xml", auth=ADMIN_BASIC)
    assert response.status_code == 200
    template = ET.fromstring(response.text).find(
        "{http://a9.com/-/spec/opensearch/1.1/}Url"
    )
    assert template is not None
    assert template.get("template") == "/api/opds/search?q={searchTerms}"
