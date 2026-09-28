"""OPDS catalogs on the server: the list (admins manage it, everyone
browses), a proxy for feeds and images, and import into a library.

The client parses feeds itself — the same parser the app uses for
on-device catalogs — so the proxy hands back the body and the final URL
its relative links resolve against. Fetch rules live in opds_fetch.
"""

import asyncio
import mimetypes
import os
import re
import uuid
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import unquote, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user, require_admin
from app.models.book import Book
from app.models.opds_catalog import OpdsCatalog
from app.models.user import User, UserRole
from app.routers.books import (
    UPLOAD_SUFFIXES,
    _ingest_upload,
    _require_upload_permission,
    _validate_upload_library,
)
from app.routers.libraries import accessible_book_ids_select
from app.schemas.book import BookOut
from app.services.opds_fetch import (
    FEED_MAX_BYTES,
    IMAGE_MAX_BYTES,
    Credentials,
    OpdsFetcher,
    OpdsFetchError,
    is_http_url,
)
from app.services.partial_md5 import compute_partial_md5
from app.services.settings import get_setting
from app.services.storage import MAX_UPLOAD_SIZE, get_book_path
from app.tasks.metadata import fetch_book_metadata
from app.tasks.text_extract import extract_book_text

router = APIRouter(prefix="/api/opds-catalogs", tags=["opds-catalogs"])

FEED_ACCEPT = (
    "application/atom+xml;profile=opds-catalog, application/atom+xml, "
    "application/opensearchdescription+xml, application/xml;q=0.9, */*;q=0.8"
)

# Acquisition types we ingest, by the suffix the upload path dispatches on.
_TYPE_SUFFIXES = {
    "application/epub+zip": ".epub",
    "application/x-mobipocket-ebook": ".mobi",
    "application/x-mobi8-ebook": ".azw3",
    "application/vnd.amazon.ebook": ".azw3",
    "application/vnd.comicbook+zip": ".cbz",
    "application/x-cbz": ".cbz",
    "text/plain": ".txt",
}


class CatalogOut(BaseModel):
    id: uuid.UUID
    name: str
    url: str
    # Admins only: readers see that a catalog signs in, not as whom.
    username: str | None = None
    has_credentials: bool


class CatalogIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    url: str = Field(min_length=1, max_length=2000)
    username: str | None = Field(None, max_length=255)
    # On update, None keeps the stored password.
    password: str | None = None

    @field_validator("url")
    @classmethod
    def _http_url(cls, value: str) -> str:
        # As entered: trailing slashes are significant on some servers
        # (Gutenberg's .opds/ endpoints 403 without one).
        value = value.strip()
        if not is_http_url(value):
            raise ValueError("url must be an http(s) URL")
        return value


class FeedOut(BaseModel):
    url: str
    body: str


class ImportIn(BaseModel):
    url: str
    library_id: uuid.UUID
    title: str | None = Field(None, max_length=500)
    # Acquisition link type as the feed declared it; the response header
    # can be generic (application/octet-stream).
    type: str | None = Field(None, max_length=200)


class ImportOut(BaseModel):
    status: Literal["imported", "duplicate"]
    book: BookOut


def _out(catalog: OpdsCatalog, user: User) -> CatalogOut:
    return CatalogOut(
        id=catalog.id,
        name=catalog.name,
        url=catalog.url,
        username=catalog.username if user.role == UserRole.admin else None,
        has_credentials=bool(catalog.username),
    )


async def _get(db: AsyncSession, catalog_id: uuid.UUID) -> OpdsCatalog:
    catalog = await db.get(OpdsCatalog, catalog_id)
    if not catalog:
        raise HTTPException(status_code=404, detail="Catalog not found")
    return catalog


async def _fetcher(db: AsyncSession, catalog: OpdsCatalog) -> OpdsFetcher:
    block = await get_setting(db, "opds_block_private_network") == "true"
    creds = (
        Credentials(catalog.username, catalog.password or "")
        if catalog.username
        else None
    )
    return OpdsFetcher(catalog.url, creds, block)


def _fetch_failed(exc: OpdsFetchError) -> HTTPException:
    """The upstream failure as our own status, with its kind in detail so
    the client can tell a wrong password from a dead server."""
    code = {
        "auth": status.HTTP_401_UNAUTHORIZED,
        "blocked": status.HTTP_403_FORBIDDEN,
        "too_large": status.HTTP_413_CONTENT_TOO_LARGE,
    }.get(exc.kind, status.HTTP_502_BAD_GATEWAY)
    # A bare 401 would read as our own session expiring; the client keys
    # on the detail instead.
    if code == status.HTTP_401_UNAUTHORIZED:
        code = status.HTTP_502_BAD_GATEWAY
    return HTTPException(status_code=code, detail=f"opds:{exc.kind}")


@router.get("", response_model=list[CatalogOut])
async def list_catalogs(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(OpdsCatalog).order_by(OpdsCatalog.created_at))
    return [_out(c, current_user) for c in result.scalars().all()]


@router.get("/{catalog_id}", response_model=CatalogOut)
async def get_catalog(
    catalog_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return _out(await _get(db, catalog_id), current_user)


@router.post("", response_model=CatalogOut, status_code=status.HTTP_201_CREATED)
async def create_catalog(
    body: CatalogIn,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    username = (body.username or "").strip() or None
    catalog = OpdsCatalog(
        name=body.name.strip(),
        url=body.url,
        username=username,
        password=body.password if username else None,
    )
    db.add(catalog)
    await db.commit()
    await db.refresh(catalog)
    return _out(catalog, current_user)


@router.put("/{catalog_id}", response_model=CatalogOut)
async def update_catalog(
    catalog_id: uuid.UUID,
    body: CatalogIn,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    catalog = await _get(db, catalog_id)
    catalog.name = body.name.strip()
    catalog.url = body.url
    catalog.username = (body.username or "").strip() or None
    if not catalog.username:
        catalog.password = None
    elif body.password is not None:
        catalog.password = body.password
    await db.commit()
    await db.refresh(catalog)
    return _out(catalog, current_user)


@router.delete("/{catalog_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_catalog(
    catalog_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await db.delete(await _get(db, catalog_id))
    await db.commit()


@router.get("/{catalog_id}/feed", response_model=FeedOut)
async def fetch_feed(
    catalog_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    url: Annotated[str | None, Query(max_length=4000)] = None,
):
    """A feed (or OpenSearch description) from the catalog, as text."""
    catalog = await _get(db, catalog_id)
    fetcher = await _fetcher(db, catalog)
    try:
        result = await fetcher.fetch(url or catalog.url, FEED_MAX_BYTES, FEED_ACCEPT)
    except OpdsFetchError as exc:
        raise _fetch_failed(exc)
    # Only feeds go back to the client: the catalog's credentials may open
    # more of its host than the catalog (an admin page served as HTML).
    # "opds:parse" is what an HTML answer is to the client — a bare origin
    # that needs /opds.
    head = result.body[:512].lstrip()
    if "xml" not in result.content_type.lower() and not head.startswith(
        (b"<?xml", b"<feed", b"<OpenSearchDescription")
    ):
        raise HTTPException(status_code=415, detail="opds:parse")
    charset = "utf-8"
    match = re.search(r"charset=([\w.-]+)", result.content_type, re.IGNORECASE)
    if match:
        charset = match.group(1)
    try:
        body = result.body.decode(charset, errors="replace")
    except LookupError:
        body = result.body.decode("utf-8", errors="replace")
    return FeedOut(url=result.url, body=body)


@router.get("/{catalog_id}/image")
async def fetch_image(
    catalog_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    url: Annotated[str, Query(max_length=4000)],
):
    catalog = await _get(db, catalog_id)
    fetcher = await _fetcher(db, catalog)
    try:
        result = await fetcher.fetch(url, IMAGE_MAX_BYTES, "image/*")
    except OpdsFetchError as exc:
        raise _fetch_failed(exc)
    content_type = result.content_type.split(";")[0].strip().lower()
    if not content_type.startswith("image/") or content_type == "image/svg+xml":
        raise HTTPException(status_code=415, detail="Not an image")
    body, content_type = await asyncio.to_thread(
        _shrink_image, result.body, content_type
    )
    return Response(
        content=body,
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=86400"},
    )


# Catalog grids ask for the full cover (thumbnails are often ~100px wide,
# too small for the card); it is cut to our own cover size on the way.
IMAGE_MAX_WIDTH = 600


def _shrink_image(data: bytes, content_type: str) -> tuple[bytes, str]:
    """The image at most IMAGE_MAX_WIDTH wide, as JPEG when resized. What
    Pillow can't read passes through as sent."""
    import io

    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as img:
            if img.width <= IMAGE_MAX_WIDTH:
                return data, content_type
            height = round(img.height * IMAGE_MAX_WIDTH / img.width)
            small = img.convert("RGB").resize((IMAGE_MAX_WIDTH, height), Image.LANCZOS)
            out = io.BytesIO()
            small.save(out, "JPEG", quality=85)
            return out.getvalue(), "image/jpeg"
    except Exception:
        return data, content_type


def _filename(disposition: str | None) -> str | None:
    if not disposition:
        return None
    match = re.search(r"filename\*=(?:UTF-8'')?([^;]+)", disposition, re.IGNORECASE)
    if match:
        return unquote(match.group(1).strip().strip('"'))
    match = re.search(r'filename="?([^";]+)"?', disposition, re.IGNORECASE)
    return match.group(1).strip() if match else None


def _suffix(
    declared: str | None, content_type: str, name: str | None, url: str
) -> str | None:
    """The upload suffix for a downloaded file: the feed's declared type,
    then the response type, then a file name's extension."""
    for mime in (declared, content_type):
        mime = (mime or "").split(";")[0].strip().lower()
        if mime in _TYPE_SUFFIXES:
            return _TYPE_SUFFIXES[mime]
    for candidate in (name, unquote(urlsplit(url).path)):
        suffix = Path(candidate or "").suffix.lower()
        if suffix in UPLOAD_SUFFIXES:
            return suffix
    guessed = mimetypes.guess_extension((content_type or "").split(";")[0])
    return guessed if guessed in UPLOAD_SUFFIXES else None


def _safe_stem(title: str | None) -> str:
    stem = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", (title or "").strip())[:120]
    return stem or "book"


@router.post("/{catalog_id}/import", response_model=ImportOut)
async def import_book(
    catalog_id: uuid.UUID,
    body: ImportIn,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Download one acquisition link into a library. An EPUB the server
    already has (same digest, visible to this user) isn't added twice."""
    _require_upload_permission(current_user)
    catalog = await _get(db, catalog_id)
    lib_id = await _validate_upload_library(str(body.library_id), current_user, db)
    fetcher = await _fetcher(db, catalog)

    tmp = get_book_path(uuid.uuid4(), "opds.download")
    try:
        try:
            result = await fetcher.download(body.url, tmp, MAX_UPLOAD_SIZE)
        except OpdsFetchError as exc:
            raise _fetch_failed(exc)
        name = _filename(result.content_disposition)
        suffix = _suffix(body.type, result.content_type, name, result.url)
        if suffix is None:
            raise HTTPException(
                status_code=415,
                detail="Only EPUB, TXT, MOBI, AZW3 or CBZ files are supported",
            )

        if suffix == ".epub":
            digest = await asyncio.to_thread(compute_partial_md5, tmp)
            existing = (
                await db.execute(
                    select(Book)
                    .where(
                        Book.partial_md5 == digest,
                        Book.id.in_(accessible_book_ids_select(current_user)),
                    )
                    .order_by(Book.created_at.asc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if existing:
                return ImportOut(status="duplicate", book=existing)

        # The TXT path takes its title hint from the file name.
        filename = f"{_safe_stem(body.title or Path(name or '').stem)}{suffix}"
        with open(tmp, "rb") as f:
            upload = UploadFile(file=f, filename=filename)
            book = await _ingest_upload(upload, current_user, lib_id, db)
        await db.commit()
        await db.refresh(book)
    finally:
        try:
            os.remove(tmp)
        except FileNotFoundError:
            pass

    extract_book_text.delay(str(book.id))
    fetch_book_metadata.delay(str(book.id))
    return ImportOut(status="imported", book=book)
