"""A book's metadata: editing it, looking it up, and its outside sources."""

import logging
import re
import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import errors
from app.database import get_db
from app.deps import get_current_user, require_admin
from app.models.book import Book, ExternalMetadata
from app.models.library import LibraryBook
from app.models.user import User
from app.plugins.metadata import BookQuery, Clue
from app.plugins.metadata import registry as metadata_registry
from app.plugins.metadata.service import lookup_all, resolve_one, search_all
from app.rate_limit import limiter
from app.schemas.book import (
    BookMetadataBulkUpdate,
    BookMetadataUpdate,
    BookOut,
    ExternalMetadataOut,
    ExternalMetadataUrlUpdate,
    IsbnCoverCandidate,
    IsbnLookupOut,
    IsbnSourceResult,
    MetadataSearchCandidate,
    MetadataSearchOut,
)
from app.services.access import (
    get_accessible_book,
    get_books,
)
from app.services.ingest import (
    require_upload_permission,
)
from app.services.metadata_fetch import cached_resolve
from app.services.series import series_key_of
from app.services.settings import (
    get_all_settings,
    get_setting,
)
from app.tasks.auto_tag import auto_tag_book
from app.tasks.metadata import fetch_book_metadata, fetch_metadata_source

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/books", tags=["books"])


def _source_page_url(plugin_cls: type | None, ref: str | None) -> str | None:
    """Human-clickable page for a source-side ref, which may be a full
    URL or a bare ID (google volume ids, hardcover slugs) that needs the
    plugin's url_prefix to become one."""
    if not ref:
        return None
    if ref.startswith("http"):
        return ref
    prefix = getattr(plugin_cls, "url_prefix", None)
    return prefix + ref if prefix else None


@router.get("/metadata-lookup", response_model=IsbnLookupOut)
@limiter.limit("10/minute")
async def metadata_lookup(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    isbn: str | None = Query(None, min_length=5, max_length=20),
    title: str | None = Query(None, min_length=1, max_length=500),
    author: str | None = Query(None, max_length=255),
    url: str | None = Query(None, max_length=1000),
    source: str | None = Query(None, max_length=50),
    ref: str | None = Query(None, max_length=1000),
):
    """Fan the clues out to every capable enabled plugin (a pasted URL
    dispatches to its owning plugin instead) and return per-source
    results with provenance. Always 200 — empty lists mean nothing was
    found anywhere.

    (source, ref) is the pick step of the two-step search: `ref` is a
    candidate from metadata-search, echoed back verbatim, and resolves
    on its owning plugin only. It can't ride the `url` param because
    some refs are bare source-side IDs (google volume ids) that no
    url_prefix can dispatch."""
    require_upload_permission(current_user)
    app_settings = await get_all_settings(db)

    if source or ref:
        if not (source and ref):
            raise HTTPException(status_code=422, detail="source and ref go together")
        plugin_cls = metadata_registry.get_plugin_class(source)
        if plugin_cls is None:
            raise HTTPException(
                status_code=400, detail=f"Unknown metadata source: {source}"
            )
        if not metadata_registry.is_enabled(plugin_cls, app_settings):
            raise HTTPException(
                status_code=409, detail=f"{plugin_cls.name} is disabled"
            )
        if Clue.URL not in plugin_cls.accepts or not plugin_cls.url_prefix:
            raise HTTPException(
                status_code=400,
                detail=f"{plugin_cls.name} does not support candidate picks",
            )
        # The owning plugin will fetch whatever ref says — constrain it
        # to the plugin's own ID shape, bare or full-URL (the same rule
        # manual linking enforces), so it can't point anywhere else.
        id_body = plugin_cls.id_pattern.lstrip("^").rstrip("$")
        if not re.fullmatch(f"(?:{re.escape(plugin_cls.url_prefix)})?{id_body}", ref):
            raise HTTPException(
                status_code=400, detail=f"Invalid ref for {plugin_cls.name}"
            )
        # Original clues ride along: google re-runs its search with them
        # to restore the search/detail merge (TW descriptions).
        query = BookQuery(
            isbn=isbn,
            title=title,
            authors=[author] if author else [],
            url=ref,
        )
        record = await resolve_one(
            plugin_cls(app_settings), query, resolver=cached_resolve
        )
        pairs = [(plugin_cls.name, record)] if record else []
    elif not (isbn or title or url):
        raise HTTPException(
            status_code=422, detail="Provide an isbn, a title, or a url"
        )
    else:
        query = BookQuery(
            isbn=isbn,
            title=title,
            authors=[author] if author else [],
            url=url,
        )
        pairs = await lookup_all(query, app_settings, resolver=cached_resolve)

    results: list[IsbnSourceResult] = []
    covers: list[IsbnCoverCandidate] = []
    seen_cover_urls: set[str] = set()
    for name, record in pairs:
        plugin_cls = metadata_registry.get_plugin_class(name)
        label = plugin_cls.label if plugin_cls else name
        # Records without a title (cover-only degradations) still feed
        # the cover candidates but don't become a pickable source.
        if record.title:
            results.append(
                IsbnSourceResult(
                    source=name,
                    label=label,
                    title=record.title,
                    authors=record.authors,
                    publisher=record.publisher,
                    description=record.description,
                    published_date=record.published_date,
                    language=record.language,
                    cover_url=record.cover_url,
                    tags=record.tags or [],
                    url=_source_page_url(plugin_cls, record.source_url),
                )
            )
        if record.cover_url and record.cover_url not in seen_cover_urls:
            seen_cover_urls.add(record.cover_url)
            covers.append(
                IsbnCoverCandidate(source=name, label=label, url=record.cover_url)
            )
    return IsbnLookupOut(results=results, covers=covers)


@router.get("/metadata-search", response_model=MetadataSearchOut)
@limiter.limit("10/minute")
async def metadata_search(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    title: str = Query(..., min_length=1, max_length=500),
    author: str | None = Query(None, max_length=255),
):
    """First step of the two-step title search: raw per-source search
    hits, no fuzzy judgment — the user picks the right book and the
    frontend calls metadata-lookup with (source, ref) to fetch its full
    record. Always 200; empty means no source had candidates."""
    require_upload_permission(current_user)
    app_settings = await get_all_settings(db)
    query = BookQuery(title=title, authors=[author] if author else [])

    candidates: list[MetadataSearchCandidate] = []
    for name, cands in await search_all(query, app_settings):
        plugin_cls = metadata_registry.get_plugin_class(name)
        label = plugin_cls.label if plugin_cls else name
        for cand in cands:
            # A hit without a title can't be judged by the user.
            if not cand.title:
                continue
            candidates.append(
                MetadataSearchCandidate(
                    source=name,
                    label=label,
                    ref=cand.url,
                    title=cand.title,
                    authors=cand.authors,
                    url=_source_page_url(plugin_cls, cand.url),
                    publisher=cand.publisher,
                    published_date=cand.published_date,
                    cover_url=cand.cover_url,
                )
            )
    return MetadataSearchOut(candidates=candidates)


def _series_key(book: Book) -> str | None:
    # (Worked out here, not read from the column: the row may have been
    # changed in this session and not yet written.)
    return series_key_of(book.series, book.epub_series)


async def _series_neighbours(
    db: AsyncSession, books: list[Book], leaving: set[uuid.UUID]
) -> list[uuid.UUID]:
    """One book still in each series these books leave, per library —
    popularity is clustered by (library, series), so the series left
    behind is recomputed too."""
    libraries = dict(
        (
            await db.execute(
                select(LibraryBook.book_id, LibraryBook.library_id).where(
                    LibraryBook.book_id.in_([b.id for b in books])
                )
            )
        ).all()
    )
    neighbours: list[uuid.UUID] = []
    for library_id, key in {
        (libraries.get(b.id), _series_key(b)) for b in books if _series_key(b)
    }:
        query = select(Book.id).where(
            Book.id.not_in(leaving),
            Book.series_key == key,
        )
        if library_id is not None:
            query = query.where(
                Book.id.in_(
                    select(LibraryBook.book_id).where(
                        LibraryBook.library_id == library_id
                    )
                )
            )
        neighbour = await db.scalar(query.limit(1))
        if neighbour is not None:
            neighbours.append(neighbour)
    return neighbours


@router.put("/{book_id}/metadata", response_model=BookOut)
async def update_book_metadata(
    book_id: uuid.UUID,
    body: BookMetadataUpdate,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(Book).where(Book.id == book_id))
    book = result.scalar_one_or_none()
    if not book:
        raise errors.BOOK_NOT_FOUND()
    data = body.model_dump()
    series_will_change = (
        "series" in body.model_fields_set and data["series"] != book.series
    )
    neighbours = (
        await _series_neighbours(db, [book], {book.id}) if series_will_change else []
    )

    for field in body.model_fields_set:
        setattr(book, field, data[field])
    await db.flush()

    if series_will_change:
        from app.services.popularity import recompute_popularity

        await recompute_popularity(db, [book.id, *neighbours])

    await db.commit()
    await db.refresh(book)
    return book


def _blank_to_none(value: str | None) -> str | None:
    return (value or "").strip() or None


@router.patch("/metadata", response_model=list[BookOut])
async def update_books_metadata(
    body: BookMetadataBulkUpdate,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Batch edit from the library table: the same authors, publisher or
    series for every book given, in one transaction; tags added to or
    taken off each; a title for one book (edit in place) or one per book
    (find and replace, worked out by the client, which showed the result). Like the edit page,
    this writes BeePub's overrides only — a Calibre book's Calibre data is
    left as it is — and a value that reads as the book's own stores none."""
    ids = list(dict.fromkeys(body.book_ids))
    fields = body.model_fields_set - {"book_ids"}
    indexes = body.series_indexes or {}
    if indexes and "series" not in fields:
        raise HTTPException(
            status_code=422, detail="series_indexes needs series alongside"
        )
    if set(indexes) - set(ids):
        raise HTTPException(
            status_code=422, detail="series_indexes names a book not in book_ids"
        )
    if "title" in fields and len(ids) != 1:
        raise HTTPException(
            status_code=422, detail="A title is given to one book at a time"
        )
    titles = body.titles or {}
    if set(titles) - set(ids):
        raise HTTPException(
            status_code=422, detail="titles names a book not in book_ids"
        )
    if "title" in fields and titles:
        raise HTTPException(status_code=422, detail="Give title or titles, not both")
    if any(len(t) > 500 for t in titles.values()):
        raise HTTPException(status_code=422, detail="A title is too long")
    tags_add = list(dict.fromkeys(t.strip() for t in body.tags_add or [] if t.strip()))
    tags_remove = {t.strip() for t in body.tags_remove or [] if t.strip()}
    if tags_remove & set(tags_add):
        raise HTTPException(status_code=422, detail="A tag is both added and removed")
    books = await get_books(db, ids)

    authors = (
        [a.strip() for a in body.authors or [] if a.strip()] or None
        if "authors" in fields
        else None
    )
    publisher = _blank_to_none(body.publisher)
    series = _blank_to_none(body.series)
    title = _blank_to_none(body.title)

    # Books whose shown series changes: their old series and new are both
    # recomputed for popularity.
    leaving = (
        [b for b in books if _series_key(b) != series_key_of(series, b.epub_series)]
        if "series" in fields
        else []
    )
    neighbours = (
        await _series_neighbours(db, leaving, {b.id for b in leaving})
        if leaving
        else []
    )

    for book in books:
        sources = dict(book.field_sources or {})
        written: dict[str, object] = {}
        # A value the book has of its own is no override: the book keeps
        # following its file (or Calibre) there.
        if "title" in fields:
            written["title"] = None if title == book.epub_title else title
        if book.id in titles:
            # Blank reads as "the book's own title again", as elsewhere.
            new_title = _blank_to_none(titles[book.id])
            written["title"] = None if new_title == book.epub_title else new_title
        if tags_add or tags_remove:
            shown = book.display_tags or []
            tags = [t for t in shown if t not in tags_remove]
            tags += [t for t in tags_add if t not in tags]
            # Untouched tags are not rewritten: a book that follows its
            # file's tags goes on following them.
            if tags != shown:
                written["tags"] = None if tags == (book.epub_tags or []) else tags
        if "authors" in fields:
            written["authors"] = (
                None if authors == (book.epub_authors or None) else authors
            )
        if "publisher" in fields:
            written["publisher"] = (
                None if publisher == book.epub_publisher else publisher
            )
        if "series" in fields:
            # The book shows its own number only under a series of its own:
            # one not given keeps the number the book shows now.
            index = (
                indexes[book.id] if book.id in indexes else book.display_series_index
            )
            if series is None or (
                series == book.epub_series and index == book.epub_series_index
            ):
                written["series"] = None
                book.series_index = None
            else:
                written["series"] = series
                book.series_index = index
        for field, value in written.items():
            setattr(book, field, value)
            # Provenance as the edit page keeps it: a typed value is manual,
            # a dropped override loses its key.
            if value is None:
                sources.pop(field, None)
            else:
                sources[field] = "manual"
        book.field_sources = sources or None
    await db.flush()

    if leaving:
        from app.services.popularity import recompute_popularity

        await recompute_popularity(db, [b.id for b in leaving] + neighbours)

    await db.commit()
    return list(
        await db.scalars(
            select(Book)
            .where(Book.id.in_(ids))
            .execution_options(populate_existing=True)
        )
    )


@router.post("/{book_id}/refresh")
async def refresh_book_metadata(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await get_accessible_book(book_id, current_user, db)
    fetch_book_metadata.delay(str(book_id))
    return {"status": "queued"}


@router.post("/{book_id}/retag")
async def retag_book(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Re-run AI tagging for a book (admin only)."""
    await get_accessible_book(book_id, current_user, db)
    auto_tag_book.delay(str(book_id))
    return {"status": "queued"}


@router.get("/{book_id}/external", response_model=list[ExternalMetadataOut])
async def get_book_external_metadata(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await get_accessible_book(book_id, current_user, db)
    result = await db.execute(
        select(ExternalMetadata).where(ExternalMetadata.book_id == book_id)
    )
    return result.scalars().all()


@router.put("/{book_id}/external/{source}/url", response_model=ExternalMetadataOut)
async def update_external_metadata_url(
    book_id: uuid.UUID,
    source: str,
    body: ExternalMetadataUrlUpdate,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    # Validate source against the plugin registry
    plugin_cls = metadata_registry.get_plugin_class(source)
    if plugin_cls is None:
        raise HTTPException(
            status_code=400,
            detail="Invalid source. Must be one of: "
            f"{', '.join(c.name for c in metadata_registry.all_plugins())}",
        )
    validated_source = plugin_cls.name

    enabled_value = await get_setting(
        db, metadata_registry.enabled_key(validated_source)
    )
    if enabled_value == "false":
        raise HTTPException(status_code=409, detail=f"{validated_source} is disabled")

    # Validate source URL format from the plugin's linking declaration
    if body.source_url is not None:
        if not plugin_cls.url_prefix:
            raise HTTPException(
                status_code=400,
                detail=f"{source} does not support manual linking",
            )
        pattern = re.compile(
            "^" + re.escape(plugin_cls.url_prefix) + plugin_cls.id_pattern.lstrip("^")
        )
        if not pattern.match(body.source_url):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid URL format for {source}",
            )

    # Check book exists
    result = await db.execute(select(Book).where(Book.id == book_id))
    if not result.scalar_one_or_none():
        raise errors.BOOK_NOT_FOUND()

    if body.source_url is None:
        # Mark as "not found" — clear data but keep the row as empty marker
        result = await db.execute(
            select(ExternalMetadata).where(
                ExternalMetadata.book_id == book_id,
                ExternalMetadata.source == validated_source,
            )
        )
        meta = result.scalar_one_or_none()
        if meta:
            meta.source_url = None
            meta.rating = None
            meta.rating_count = None
            meta.readers_count = None
            meta.reviews = None
            meta.record = None
        else:
            meta = ExternalMetadata(
                book_id=book_id,
                source=validated_source,
            )
            db.add(meta)
        await db.commit()
        await db.refresh(meta)
        # Re-run tag mapping since we removed a source's data
        from app.services.tag_mapping import generate_tags_from_metadata

        await generate_tags_from_metadata(db, book_id)
        await db.commit()
        return meta
    else:
        # Upsert: update existing or create new row with just the URL
        result = await db.execute(
            select(ExternalMetadata).where(
                ExternalMetadata.book_id == book_id,
                ExternalMetadata.source == validated_source,
            )
        )
        meta = result.scalar_one_or_none()
        if meta:
            meta.source_url = body.source_url
        else:
            meta = ExternalMetadata(
                book_id=book_id,
                source=validated_source,
                source_url=body.source_url,
            )
            db.add(meta)
        await db.commit()
        await db.refresh(meta)
        # Fetch data from the pinned URL and re-map tags
        fetch_metadata_source.delay(str(book_id), source)
        return meta


@router.delete("/{book_id}/external/{source}", status_code=204)
async def delete_external_metadata(
    book_id: uuid.UUID,
    source: str,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Unlink a source completely — removes the row so it can be re-searched."""
    if metadata_registry.get_plugin_class(source) is None:
        raise errors.INVALID_SOURCE()
    validated_source = source

    result = await db.execute(
        select(ExternalMetadata).where(
            ExternalMetadata.book_id == book_id,
            ExternalMetadata.source == validated_source,
        )
    )
    meta = result.scalar_one_or_none()
    if not meta:
        raise errors.METADATA_NOT_FOUND()
    await db.delete(meta)
    await db.commit()

    # Re-run tag mapping
    from app.services.tag_mapping import generate_tags_from_metadata

    await generate_tags_from_metadata(db, book_id)
    await db.commit()
