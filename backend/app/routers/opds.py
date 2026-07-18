"""OPDS 1.2 catalog — read-only Atom feeds for e-reader clients (KOReader etc.).

OPDS clients send HTTP Basic credentials on every request instead of doing a
cookie/bearer login flow, so this router has its own auth dependency. All
hrefs are absolute paths; clients resolve them against the catalog's host.
"""

import asyncio
import base64
import binascii
import os
import uuid
from datetime import UTC, datetime
from typing import Annotated
from xml.etree import ElementTree as ET

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.requests import Request
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.book import Book
from app.models.library import Library, LibraryBook
from app.models.user import User, UserRole
from app.routers.books import book_search_conditions
from app.routers.libraries import (
    accessible_book_ids_select,
    accessible_libraries_condition,
)
from app.services.auth import verify_password
from app.services.credential_cache import CredentialCache

# Mounted twice in main.py: /opds (the e-reader convention) and /api/opds
# (compatibility alias). Feed hrefs follow the prefix the request came in on.
router = APIRouter(tags=["opds"])

PAGE_SIZE = 50

ATOM_NS = "http://www.w3.org/2005/Atom"
DC_NS = "http://purl.org/dc/terms/"
OPENSEARCH_NS = "http://a9.com/-/spec/opensearch/1.1/"

NAV_TYPE = "application/atom+xml;profile=opds-catalog;kind=navigation"
ACQ_TYPE = "application/atom+xml;profile=opds-catalog;kind=acquisition"
OPENSEARCH_TYPE = "application/opensearchdescription+xml"

ACQUISITION_REL = "http://opds-spec.org/acquisition"
IMAGE_REL = "http://opds-spec.org/image"
THUMBNAIL_REL = "http://opds-spec.org/image/thumbnail"


# --- HTTP Basic auth -------------------------------------------------------

_credential_cache = CredentialCache()


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": 'Basic realm="BeePub OPDS"'},
    )


async def get_opds_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Basic "):
        raise _unauthorized()
    try:
        decoded = base64.b64decode(header[6:], validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        raise _unauthorized() from None
    username, sep, password = decoded.partition(":")
    if not sep or not username or not password:
        raise _unauthorized()

    cache_key = CredentialCache.key(username, password)
    cached_id = _credential_cache.get(cache_key)
    user: User | None = None
    if cached_id is not None:
        result = await db.execute(select(User).where(User.id == cached_id))
        user = result.scalar_one_or_none()
        if user is None:
            # The cached account is gone; fall through to a fresh
            # verification (the same username may exist under a new id).
            _credential_cache.invalidate(cache_key)

    if user is None:
        result = await db.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()
        # bcrypt off the event loop — covers arrive in concurrent bursts.
        if user is None or not await asyncio.to_thread(
            verify_password, password, user.password_hash
        ):
            raise _unauthorized()
        _credential_cache.put(cache_key, user.id)

    if not user.is_active:
        _credential_cache.invalidate(cache_key)
        raise _unauthorized()
    return user


# --- Atom/XML helpers ------------------------------------------------------


def _base_path(request: Request) -> str:
    """The catalog prefix of the incoming request: '/opds' or '/api/opds'."""
    path = request.url.path
    return path[: path.find("/opds") + len("/opds")]


def _rfc3339(dt: datetime | None) -> str:
    if dt is None:
        dt = datetime.now(UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()


def _add_link(parent: ET.Element, rel: str, href: str, type_: str) -> None:
    ET.SubElement(parent, "link", {"rel": rel, "href": href, "type": type_})


def _feed(
    title: str, feed_id: str, self_href: str, kind_type: str, base: str
) -> ET.Element:
    feed = ET.Element("feed", {"xmlns": ATOM_NS, "xmlns:dc": DC_NS})
    ET.SubElement(feed, "id").text = feed_id
    ET.SubElement(feed, "title").text = title
    ET.SubElement(feed, "updated").text = _rfc3339(None)
    _add_link(feed, "self", self_href, kind_type)
    _add_link(feed, "start", base, NAV_TYPE)
    _add_link(feed, "search", f"{base}/opensearch.xml", OPENSEARCH_TYPE)
    return feed


def _atom_response(feed: ET.Element, kind_type: str) -> Response:
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
        feed, encoding="unicode"
    )
    return Response(content=xml, media_type=kind_type)


def _book_entry(feed: ET.Element, book: Book, base: str) -> None:
    entry = ET.SubElement(feed, "entry")
    ET.SubElement(entry, "title").text = book.title or book.epub_title or "Untitled"
    ET.SubElement(entry, "id").text = f"urn:uuid:{book.id}"
    ET.SubElement(entry, "updated").text = _rfc3339(book.updated_at)
    for name in book.authors or book.epub_authors or []:
        author = ET.SubElement(entry, "author")
        ET.SubElement(author, "name").text = name
    if book.epub_language:
        ET.SubElement(entry, "dc:language").text = book.epub_language
    if book.epub_publisher:
        ET.SubElement(entry, "dc:publisher").text = book.epub_publisher
    description = book.description or book.epub_description
    if description:
        summary = ET.SubElement(entry, "summary")
        summary.set("type", "text")
        summary.text = description
    _add_link(
        entry,
        ACQUISITION_REL,
        f"{base}/books/{book.id}/file",
        "application/epub+zip",
    )
    if book.cover_path:
        cover_href = f"{base}/books/{book.id}/cover"
        _add_link(entry, IMAGE_REL, cover_href, "image/jpeg")
        _add_link(entry, THUMBNAIL_REL, cover_href, "image/jpeg")


def _nav_entry(feed: ET.Element, title: str, entry_id: str, href: str, content: str):
    entry = ET.SubElement(feed, "entry")
    ET.SubElement(entry, "title").text = title
    ET.SubElement(entry, "id").text = entry_id
    ET.SubElement(entry, "updated").text = _rfc3339(None)
    body = ET.SubElement(entry, "content")
    body.set("type", "text")
    body.text = content
    _add_link(entry, "subsection", href, ACQ_TYPE)


# --- Feeds ------------------------------------------------------------------


def _accessible_books_query(user: User):
    # Physical (file-less) books are excluded outright: an OPDS entry
    # without an acquisition link is useless to every client.
    return select(Book).where(
        Book.id.in_(accessible_book_ids_select(user)),
        Book.file_path.isnot(None),
    )


async def _acquisition_feed(
    db: AsyncSession,
    *,
    title: str,
    feed_id: str,
    path: str,
    query,
    page: int,
    base: str,
    extra_params: str = "",
) -> Response:
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    result = await db.execute(
        query.order_by(Book.created_at.desc(), Book.id.desc())
        .offset((page - 1) * PAGE_SIZE)
        .limit(PAGE_SIZE)
    )
    books = result.scalars().all()

    self_href = f"{path}?{extra_params}page={page}"
    feed = _feed(title, feed_id, self_href, ACQ_TYPE, base)
    if page > 1:
        _add_link(feed, "previous", f"{path}?{extra_params}page={page - 1}", ACQ_TYPE)
    if page * PAGE_SIZE < (total or 0):
        _add_link(feed, "next", f"{path}?{extra_params}page={page + 1}", ACQ_TYPE)
    for book in books:
        _book_entry(feed, book, base)
    return _atom_response(feed, ACQ_TYPE)


@router.get("")
async def opds_root(
    request: Request,
    current_user: Annotated[User, Depends(get_opds_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Root navigation feed: all books + one entry per accessible library."""
    query = select(Library)
    cond = accessible_libraries_condition(current_user)
    if cond is not True:
        query = query.where(cond)
    result = await db.execute(query.order_by(Library.created_at.desc()))
    libraries = result.scalars().all()

    base = _base_path(request)
    feed = _feed("BeePub", "urn:beepub:opds:root", base, NAV_TYPE, base)
    _nav_entry(
        feed,
        "All books",
        "urn:beepub:opds:all",
        f"{base}/all",
        "Every book you can access, newest first",
    )
    for library in libraries:
        _nav_entry(
            feed,
            library.name,
            f"urn:beepub:opds:library:{library.id}",
            f"{base}/libraries/{library.id}",
            library.description or f"Books in {library.name}",
        )
    return _atom_response(feed, NAV_TYPE)


@router.get("/opensearch.xml")
async def opds_opensearch(
    request: Request,
    current_user: Annotated[User, Depends(get_opds_user)],
):
    root = ET.Element("OpenSearchDescription", {"xmlns": OPENSEARCH_NS})
    ET.SubElement(root, "ShortName").text = "BeePub"
    ET.SubElement(root, "Description").text = "Search the BeePub library"
    ET.SubElement(
        root,
        "Url",
        {
            "type": ACQ_TYPE,
            "template": f"{_base_path(request)}/search?q={{searchTerms}}",
        },
    )
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
        root, encoding="unicode"
    )
    return Response(content=xml, media_type=OPENSEARCH_TYPE)


@router.get("/all")
async def opds_all_books(
    request: Request,
    current_user: Annotated[User, Depends(get_opds_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
):
    base = _base_path(request)
    return await _acquisition_feed(
        db,
        title="All books",
        feed_id="urn:beepub:opds:all",
        path=f"{base}/all",
        query=_accessible_books_query(current_user),
        page=page,
        base=base,
    )


@router.get("/libraries/{library_id}")
async def opds_library(
    request: Request,
    library_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_opds_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
):
    query = select(Library).where(Library.id == library_id)
    cond = accessible_libraries_condition(current_user)
    if cond is not True:
        # Excluded libraries 404 rather than 403: don't leak their existence.
        query = query.where(cond)
    library = (await db.execute(query)).scalar_one_or_none()
    if library is None:
        raise HTTPException(status_code=404, detail="Library not found")

    books = _accessible_books_query(current_user).where(
        Book.id.in_(
            select(LibraryBook.book_id).where(LibraryBook.library_id == library_id)
        )
    )
    base = _base_path(request)
    return await _acquisition_feed(
        db,
        title=library.name,
        feed_id=f"urn:beepub:opds:library:{library_id}",
        path=f"{base}/libraries/{library_id}",
        query=books,
        page=page,
        base=base,
    )


@router.get("/search")
async def opds_search(
    request: Request,
    current_user: Annotated[User, Depends(get_opds_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    q: Annotated[str, Query(min_length=1, max_length=200)],
    page: Annotated[int, Query(ge=1)] = 1,
):
    from urllib.parse import quote

    base = _base_path(request)
    query = _accessible_books_query(current_user).where(or_(*book_search_conditions(q)))
    return await _acquisition_feed(
        db,
        title=f"Search: {q}",
        feed_id=f"urn:beepub:opds:search:{quote(q)}",
        path=f"{base}/search",
        query=query,
        page=page,
        base=base,
        extra_params=f"q={quote(q)}&",
    )


# --- Object endpoints (same auth scheme so OPDS clients can follow links) ---


async def _opds_book_with_access(
    book_id: uuid.UUID, user: User, db: AsyncSession
) -> Book:
    result = await db.execute(_accessible_books_query(user).where(Book.id == book_id))
    book = result.scalar_one_or_none()
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    return book


@router.get("/books/{book_id}/file")
async def opds_book_file(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_opds_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if current_user.role != UserRole.admin and not current_user.can_download:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Download permission required",
        )
    book = await _opds_book_with_access(book_id, current_user, db)
    if not os.path.exists(book.file_path):
        raise HTTPException(status_code=404, detail="File not found")
    title = book.title or book.epub_title or "book"
    return FileResponse(
        book.file_path,
        media_type="application/epub+zip",
        filename=f"{title}.epub",
    )


@router.get("/books/{book_id}/cover")
async def opds_book_cover(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_opds_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    book = await _opds_book_with_access(book_id, current_user, db)
    if not book.cover_path or not os.path.exists(book.cover_path):
        raise HTTPException(status_code=404, detail="Cover not found")
    return FileResponse(book.cover_path, media_type="image/jpeg")
