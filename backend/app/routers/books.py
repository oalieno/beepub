import logging
import re
import uuid
from typing import Annotated, Any, NamedTuple

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from sqlalchemy import and_, exists, func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.functions import coalesce

from app.database import get_db
from app.deps import get_current_user, require_admin
from app.models.book import Book, ExternalMetadata
from app.models.book_text import BookTextChunk
from app.models.library import Library, LibraryBook, UserLibraryExclusion
from app.models.reading import UserBookInteraction
from app.models.tag import BookTag
from app.models.user import User, UserRole
from app.plugins.metadata import BookQuery, Clue
from app.plugins.metadata import registry as metadata_registry
from app.plugins.metadata.service import lookup_all, resolve_one, search_all
from app.rate_limit import limiter
from app.schemas.book import (
    BookIdsRequest,
    BookLibraryUpdate,
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
    PaginatedBooksWithInteraction,
    PhysicalBookCreate,
    SeriesBookBrief,
    SeriesNeighborsOut,
    SeriesProgress,
)
from app.schemas.series import PaginatedGrouped
from app.services.access import (
    accessible_book_ids_select,
    get_accessible_book,
    get_accessible_library,
)
from app.services.book_cards import book_cards
from app.services.book_files import (
    book_files,
)
from app.services.book_search import relevance_ranked_ids, tiered_book_search
from app.services.ingest import (
    UNSUPPORTED_UPLOAD,
    commit_ingested,
    discard_ingested,
    ingest_upload,
    require_upload_permission,
    upload_suffix,
    validate_upload_library,
)
from app.services.metadata_fetch import cached_resolve
from app.services.series import series_key_of
from app.services.settings import (
    get_all_settings,
    get_setting,
)
from app.services.storage import (
    cover_url_allowed,
    delete_file,
    download_cover,
    get_cover_path,
)
from app.tasks.auto_tag import auto_tag_book
from app.tasks.metadata import fetch_book_metadata, fetch_metadata_source

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/books", tags=["books"])


@router.post("", response_model=BookOut, status_code=status.HTTP_201_CREATED)
async def upload_book(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    file: UploadFile = File(...),
    library_id: str = Form(...),
):
    require_upload_permission(current_user)
    if upload_suffix(file) is None:
        raise HTTPException(status_code=400, detail=UNSUPPORTED_UPLOAD)

    lib_id = await validate_upload_library(library_id, current_user, db)
    book = await ingest_upload(file, current_user, lib_id, db)
    await commit_ingested(db, [book])
    return book


@router.post("/bulk", response_model=list[BookOut], status_code=status.HTTP_201_CREATED)
async def upload_books_bulk(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    files: list[UploadFile] = File(...),
    library_id: str = Form(...),
):
    require_upload_permission(current_user)
    lib_id = await validate_upload_library(library_id, current_user, db)

    # All or none: one file that cannot be read refuses the request, and
    # the ones staged before it go with it.
    books: list[Book] = []
    try:
        for file in files:
            if upload_suffix(file) is None:
                continue
            books.append(await ingest_upload(file, current_user, lib_id, db))
    except Exception:
        discard_ingested(books)
        raise
    await commit_ingested(db, books)
    return books


@router.post("/physical", response_model=BookOut, status_code=status.HTTP_201_CREATED)
async def create_physical_book(
    body: PhysicalBookCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Track a paper copy: a Book row with no file behind it."""
    require_upload_permission(current_user)
    lib_id = await validate_upload_library(str(body.library_id), current_user, db)

    book_id = uuid.uuid4()
    cover_path = None
    if body.cover_url:
        if not cover_url_allowed(body.cover_url):
            raise HTTPException(status_code=422, detail="cover_url host is not allowed")
        dest = get_cover_path(book_id)
        if await download_cover(body.cover_url, dest):
            cover_path = dest

    book = Book(
        id=book_id,
        file_path=None,
        file_size=None,
        format="physical",
        cover_path=cover_path,
        # "" is the established no-digest marker — non-NULL so the digest
        # backfill scan never picks the book up.
        partial_md5="",
        # False (not NULL) keeps the text-extraction scan from queueing it.
        is_image_book=False,
        added_by=current_user.id,
        # Physical books have no EPUB source metadata; everything lives in
        # the manual-override columns (which win in display anyway).
        title=body.title,
        authors=body.authors or None,
        publisher=body.publisher,
        description=body.description,
        published_date=body.published_date,
        series=body.series,
        series_index=body.series_index,
        epub_isbn=body.isbn,
        epub_language=body.language,
    )
    db.add(book)
    await db.flush()
    db.add(LibraryBook(library_id=lib_id, book_id=book_id, added_by=current_user.id))
    await db.commit()
    await db.refresh(book)

    # External ratings/reviews and auto-tagging work from metadata alone;
    # text extraction is meaningless without a file and is not queued.
    fetch_book_metadata.delay(str(book.id))
    return book


@router.put("/{book_id}/library")
async def move_book_to_library(
    book_id: uuid.UUID,
    body: BookLibraryUpdate,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Set the library a book belongs to (a book lives in exactly one)."""
    book_result = await db.execute(select(Book).where(Book.id == book_id))
    if not book_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Book not found")

    lib_result = await db.execute(select(Library).where(Library.id == body.library_id))
    target = lib_result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Library not found")
    if target.calibre_path:
        raise HTTPException(
            status_code=403, detail="Cannot move books into a Calibre library"
        )

    membership_result = await db.execute(
        select(LibraryBook).where(LibraryBook.book_id == book_id)
    )
    membership = membership_result.scalar_one_or_none()
    if membership is not None and membership.library_id == body.library_id:
        return {"status": "unchanged"}

    from app.services.work_library import book_is_in_work

    if await book_is_in_work(book_id, db):
        # A Work's editions must live in one library — move them together
        # or not at all.
        raise HTTPException(
            status_code=409,
            detail=(
                "Book is part of a Work. Dissolve the Work first, "
                "or move all its editions together."
            ),
        )

    if membership is None:
        # Legacy orphan (pre-invariant data) — adopt it into the target.
        db.add(
            LibraryBook(
                library_id=body.library_id,
                book_id=book_id,
                added_by=current_user.id,
            )
        )
    else:
        source = await db.get(Library, membership.library_id)
        if source is not None and source.calibre_path:
            raise HTTPException(
                status_code=403,
                detail="Cannot move books out of a Calibre library",
            )
        membership.library_id = body.library_id
        membership.added_by = current_user.id
    await db.commit()
    return {"status": "moved"}


class _Place(NamedTuple):
    """Where a book stands in the list: how many come before it, and —
    when the order is one key and the id — that key and the book's own
    value of it (None when numbering every row was the only way)."""

    index: int
    key: Any = None
    value: Any = None
    book_id: uuid.UUID | None = None

    def before(self, order: str):
        tie = and_(self.key == self.value, Book.id < self.book_id)
        if order == "desc":
            # Descending, Postgres puts the books with no key first.
            return or_(self.key > self.value, self.key.is_(None), tie)
        return or_(self.key < self.value, tie)

    def from_here(self, order: str):
        tie = and_(self.key == self.value, Book.id >= self.book_id)
        if order == "desc":
            return or_(self.key < self.value, tie)
        return or_(self.key > self.value, self.key.is_(None), tie)


async def _place_in_order(
    db: AsyncSession,
    base_query,
    book_id: uuid.UUID,
    sort: str,
    order: str,
    order_by: list,
) -> _Place | None:
    """The book's place in the list in the given order (None when it is
    not in the list).

    Counted, where the order is one key and the id: the books whose key
    sorts before this book's — a walk of the key's index up to the book,
    where numbering every row of the list sorts all of it first."""
    if sort != "series_index":
        key = order_by[0].element
        found = (
            await db.execute(
                base_query.with_only_columns(key).where(Book.id == book_id)
            )
        ).first()
        if found is None:
            return None
        if found[0] is not None:
            place = _Place(0, key, found[0], book_id)
            count = await db.scalar(
                select(func.count()).select_from(
                    base_query.with_only_columns(Book.id)
                    .where(place.before(order))
                    .subquery()
                )
            )
            return place._replace(index=count or 0)
    ranked = base_query.with_only_columns(
        Book.id.label("id"),
        func.row_number().over(order_by=order_by).label("rn"),
    ).subquery()
    rank = await db.scalar(select(ranked.c.rn).where(ranked.c.id == book_id))
    return None if rank is None else _Place(rank - 1)


async def _page_at(
    db: AsyncSession, base_query, place: _Place, order: str, limit: int
) -> list[Book]:
    """The page that opens AROUND_BEFORE books ahead of the place: those
    few, read backwards from it, then the rest forwards — two short walks
    from the book, where an OFFSET walks the whole list up to it."""
    key = place.key
    backwards = (
        [key.asc(), Book.id.desc()] if order == "desc" else [key.desc(), Book.id.desc()]
    )
    forwards = [key.desc(), Book.id] if order == "desc" else [key.asc(), Book.id]
    ahead = list(
        await db.scalars(
            base_query.where(place.before(order))
            .order_by(*backwards)
            .limit(min(AROUND_BEFORE, place.index))
        )
    )
    ahead.reverse()
    # (The page is `limit` books from its start, wherever the book falls.)
    ahead = ahead[:limit]
    if len(ahead) == limit:
        return ahead
    rest = list(
        await db.scalars(
            base_query.where(place.from_here(order))
            .order_by(*forwards)
            .limit(limit - len(ahead))
        )
    )
    return ahead + rest


# How many books the page opened ``around`` a book shows before it.
AROUND_BEFORE = 20


def _list_order(sort: str, order: str) -> list:
    """The flat book list's ORDER BY — ending on Book.id, so the order is
    total and a book's place in it (``around``) is the place it is paged at."""
    sort_map = {
        "display_title": coalesce(Book.title, Book.epub_title),
        "added_at": coalesce(Book.calibre_added_at, Book.created_at),
        "series_index": coalesce(Book.series_index, Book.epub_series_index),
        "popularity_score": Book.popularity_score,
    }
    # A column of the table by its name, or the newest first: any other
    # attribute of the model (a relationship, `metadata`) is not an order.
    sort_col = sort_map.get(sort)
    if sort_col is None:
        sort_col = (
            getattr(Book, sort) if sort in Book.__table__.columns else Book.created_at
        )
    if sort == "series_index":
        series_col = coalesce(Book.series, Book.epub_series)
        if order == "desc":
            return [series_col.desc().nullslast(), sort_col.desc().nullslast(), Book.id]
        return [series_col.asc().nullslast(), sort_col.asc().nullslast(), Book.id]
    if order == "desc":
        return [sort_col.desc(), Book.id]
    return [sort_col.asc(), Book.id]


@router.get("", response_model=PaginatedBooksWithInteraction)
async def list_all_books(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    search: str | None = Query(None),
    author: str | None = Query(None),
    tag: str | None = Query(None),
    series: str | None = Query(None),
    format: str | None = Query(None),
    library: uuid.UUID | None = Query(None),
    ids: list[uuid.UUID] | None = Query(None, max_length=200),
    has_rating: bool = Query(False),
    sort: str = Query("created_at"),
    order: str = Query("desc"),
    limit: int = Query(60, ge=1, le=200),
    offset: int = Query(0, ge=0),
    around: uuid.UUID | None = Query(None),
):
    """The flat book list: one row per book, across every accessible library.

    ``library`` scopes the result to one library (404 when it does not exist,
    403 when the user is excluded from it) — a library's own page, and with
    ``series`` the series-detail page, which only shows that library's volumes
    (series identity is ``(library_id, series_key)``).

    ``ids`` narrows to the given books — the app's "downloaded" shelf, whose
    membership lives on the device; it pages the ids itself.

    ``around`` opens the page on a book instead of at ``offset``: it starts
    a few books before it (the library table keeps the book in view when its
    order changes). A book not in the list leaves ``offset`` as asked; the
    response's ``around_index`` says which happened.
    """

    if library is not None:
        await get_accessible_library(library, current_user, db)

    # Accessible book IDs (avoids DISTINCT on the main query)
    accessible_ids = accessible_book_ids_select(current_user)

    base_query = select(Book).where(Book.id.in_(accessible_ids))
    if ids:
        base_query = base_query.where(Book.id.in_(ids))

    # Apply filters. Search is applied last, below — its tier probe must
    # see the fully-filtered scope.
    if author:
        base_query = base_query.where(
            or_(
                Book.authors.any(author),
                Book.epub_authors.any(author),
            )
        )
    if tag:
        base_query = base_query.where(
            or_(
                Book.tags.any(tag),
                Book.epub_tags.any(tag),
                Book.id.in_(select(BookTag.book_id).where(BookTag.tag == tag)),
            )
        )
    if series:
        base_query = base_query.where(
            or_(
                Book.series == series,
                Book.epub_series == series,
            )
        )
    if format:
        base_query = base_query.where(Book.format == format)
    if library:
        base_query = base_query.where(
            Book.id.in_(
                select(LibraryBook.book_id).where(LibraryBook.library_id == library)
            )
        )
    if has_rating:
        base_query = base_query.where(
            Book.id.in_(
                select(UserBookInteraction.book_id).where(
                    UserBookInteraction.user_id == current_user.id,
                    UserBookInteraction.rating.is_not(None),
                )
            )
        )
    tiered = None
    if search:
        tiered = await tiered_book_search(db, search, base_query)
        base_query = base_query.where(or_(*tiered.conditions))

    if ids or author or tag or series or format or has_rating or search:
        # Count over ids — the total needs nothing else from a book.
        count_query = select(func.count()).select_from(
            base_query.with_only_columns(Book.id).subquery()
        )
    else:
        # Nothing about the books themselves is asked: the count is of
        # their places in the libraries (a book has exactly one), without
        # reading the books table — on every page of an endless list.
        placed = accessible_ids
        if library:
            placed = placed.where(LibraryBook.library_id == library)
        count_query = select(func.count()).select_from(placed.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Apply sorting and pagination
    if series and sort == "created_at":
        sort = "series_index"
        order = "asc"
    if sort == "relevance" and tiered is None:
        # Nothing to be relevant to (a stale URL) — the default order.
        sort, order = "created_at", "desc"
    around_index: int | None = None
    if sort == "relevance":
        # Ranked over ids, the page's books fetched afterwards (see
        # relevance_ranked_ids). ``around`` does not apply: a search starts
        # from its best match.
        page_ids = list(
            await db.scalars(
                relevance_ranked_ids(base_query, tiered, search)
                .offset(offset)
                .limit(limit)
            )
        )
        books_by_id = {
            book.id: book
            for book in await db.scalars(select(Book).where(Book.id.in_(page_ids)))
        }
        books = [books_by_id[book_id] for book_id in page_ids]
    else:
        order_by = _list_order(sort, order)
        if around is not None:
            # The book's place in this very order, so the page can open on it.
            place = await _place_in_order(db, base_query, around, sort, order, order_by)
        if around is not None and place is not None:
            around_index = place.index
            offset = max(0, around_index - AROUND_BEFORE)
        if around is not None and place is not None and place.key is not None:
            books = await _page_at(db, base_query, place, order, limit)
        else:
            result = await db.execute(
                base_query.order_by(*order_by).offset(offset).limit(limit)
            )
            books = result.scalars().all()

    items = await book_cards(db, current_user.id, books)

    return PaginatedBooksWithInteraction(
        items=items, total=total, offset=offset, around_index=around_index
    )


@router.get("/grouped", response_model=PaginatedGrouped)
async def list_books_grouped(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    search: str | None = Query(None),
    author: str | None = Query(None),
    tag: str | None = Query(None),
    library: uuid.UUID | None = Query(None),
    sort: str = Query("added_at"),
    order: str = Query("desc"),
    limit: int = Query(60, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """The grouped book list: a series is one item, editions of the same work
    are one item, every other book is its own.

    ``library`` scopes the result to one library (404 when it does not exist,
    403 when the user is excluded from it); without it the list spans every
    accessible library.
    """
    from app.services.series import list_grouped_books

    # The service does not apply the exclusion filter when scoped to one
    # library, so access to that library is settled here.
    if library is not None:
        await get_accessible_library(library, current_user, db)

    items, total = await list_grouped_books(
        db,
        current_user,
        library_id=library,
        search=search,
        author=author,
        tag=tag,
        sort=sort,
        order=order,
        limit=limit,
        offset=offset,
    )
    return PaginatedGrouped(items=items, total=total)


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


# Spine indices come from our own extractor enumerating a real OPF spine,
# but the dense array below is sized by the largest index — cap it so a
# pathological row can never balloon the response.
_MAX_SPINE_SECTIONS = 10_000


async def _section_weights(book_id: uuid.UUID, db: AsyncSession) -> list[int] | None:
    """Per-section text sizes, dense by spine index, from the text chunks.

    The chunks are the single source of truth — this is derived on read
    (indexed aggregate over at most a few hundred rows), never stored.
    None = extraction hasn't produced chunks (pending, or image-only book).
    """
    rows = (
        await db.execute(
            select(
                BookTextChunk.spine_index,
                func.sum(func.length(BookTextChunk.text)),
            )
            .where(
                BookTextChunk.book_id == book_id,
                BookTextChunk.spine_index < _MAX_SPINE_SECTIONS,
            )
            .group_by(BookTextChunk.spine_index)
        )
    ).all()
    if not rows:
        return None
    weights = [0] * (max(idx for idx, _ in rows) + 1)
    for idx, total in rows:
        if idx >= 0:
            weights[idx] = int(total or 0)
    return weights


@router.get("/{book_id}", response_model=BookOut)
async def get_book(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    book = await get_accessible_book(book_id, current_user, db)
    # Find libraries this book belongs to
    lb_result = await db.execute(
        select(Library.id, Library.name)
        .join(LibraryBook, LibraryBook.library_id == Library.id)
        .where(LibraryBook.book_id == book_id)
    )
    libraries = lb_result.all()
    out = BookOut.model_validate(book)
    out.library_id = libraries[0].id if libraries else None
    out.library_names = [lib.name for lib in libraries]

    # Check for unresolved reports
    from app.models.book_report import BookReport

    report_result = await db.execute(
        select(BookReport.id)
        .where(BookReport.book_id == book_id, BookReport.resolved.is_(False))
        .limit(1)
    )
    out.has_unresolved_reports = report_result.scalar_one_or_none() is not None
    out.section_weights = await _section_weights(book_id, db)
    return out


@router.get("/{book_id}/editions")
async def get_book_editions(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get other editions of the same Work plus the Work's primary_book_id.

    Returns {primary_book_id: null, editions: []} if the book has no Work.
    """
    book = await get_accessible_book(book_id, current_user, db)
    if not book.work_id:
        return {"primary_book_id": None, "editions": []}

    from app.models.work import Work

    work_result = await db.execute(select(Work).where(Work.id == book.work_id))
    work = work_result.scalar_one_or_none()

    result = await db.execute(
        select(Book)
        .where(Book.work_id == book.work_id, Book.id != book_id)
        .order_by(Book.created_at.desc())
    )
    siblings = result.scalars().all()
    return {
        "primary_book_id": work.primary_book_id if work else None,
        "editions": [
            {
                "id": b.id,
                "display_title": b.display_title,
                "display_authors": b.display_authors,
                "cover_path": b.cover_path,
                "epub_isbn": b.epub_isbn,
                "metadata_count": b.metadata_count,
                "created_at": b.created_at,
            }
            for b in siblings
        ],
    }


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
        raise HTTPException(status_code=404, detail="Book not found")
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


async def _books_by_ids(db: AsyncSession, ids: list[uuid.UUID]) -> list[Book]:
    """The books, in the order asked; 404 naming any that do not exist."""
    found = {b.id: b for b in await db.scalars(select(Book).where(Book.id.in_(ids)))}
    missing = [str(i) for i in ids if i not in found]
    if missing:
        raise HTTPException(
            status_code=404, detail=f"Books not found: {', '.join(missing)}"
        )
    return [found[i] for i in ids]


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
    books = await _books_by_ids(db, ids)

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


@router.post("/delete", status_code=status.HTTP_204_NO_CONTENT)
async def delete_books(
    body: BookIdsRequest,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Delete several books at once, all or none. Not Calibre books: the
    next sync would bring them back."""
    books = await _books_by_ids(db, list(dict.fromkeys(body.book_ids)))
    calibre = [str(b.id) for b in books if b.calibre_id is not None]
    if calibre:
        raise HTTPException(
            status_code=409,
            detail=f"Books in a Calibre library cannot be deleted: {', '.join(calibre)}",
        )
    paths = [path for b in books for path in book_files(b)]
    work_ids = {b.work_id for b in books if b.work_id}
    for book in books:
        await db.delete(book)
    if work_ids:
        from app.services.work_library import cleanup_orphan_works

        await cleanup_orphan_works(db, list(work_ids))
    # Files go after the commit: a failed commit must not leave rows
    # pointing at deleted files.
    await db.commit()
    for path in paths:
        delete_file(path)


@router.delete("/{book_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_book(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(Book).where(Book.id == book_id))
    book = result.scalar_one_or_none()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    # Files are removed AFTER the commit — if the commit fails, a row
    # pointing at a deleted file would be unrecoverable.
    paths = book_files(book)
    work_id = book.work_id
    await db.delete(book)
    if work_id:
        from app.services.work_library import cleanup_orphan_works

        await cleanup_orphan_works(db, [work_id])
    await db.commit()
    for path in paths:
        delete_file(path)


@router.post("/{book_id}/refresh")
async def refresh_book_metadata(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await get_accessible_book(book_id, current_user, db)
    fetch_book_metadata.delay(str(book_id))
    return {"status": "queued"}


@router.get("/{book_id}/similar")
async def get_similar_books_endpoint(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(10, ge=1, le=50),
):
    """Get books similar to this one, with similarity scores."""
    from app.services.recommendations import get_similar_books

    await get_accessible_book(book_id, current_user, db)
    similar = await get_similar_books(
        db,
        book_id,
        current_user.id,
        is_admin=current_user.role == UserRole.admin,
        limit=limit,
    )
    if not similar:
        return []

    result = await db.execute(
        select(Book).where(Book.id.in_([s["book_id"] for s in similar]))
    )
    books = {b.id: b for b in result.scalars().all()}

    # Build response with scores, ordered by total_score
    similar_map = {s["book_id"]: s for s in similar}
    ordered = sorted(
        books.values(),
        key=lambda b: similar_map.get(b.id, {}).get("score", 0),
        reverse=True,
    )

    # Dedup by Work: keep only the highest-scoring book per Work
    seen_work_ids: set[uuid.UUID] = set()
    deduped = []
    for book in ordered:
        if book.work_id:
            if book.work_id in seen_work_ids:
                continue
            seen_work_ids.add(book.work_id)
        deduped.append(book)

    from app.schemas.tag import SimilarBookOut

    return [
        SimilarBookOut(
            **BookOut.model_validate(book, from_attributes=True).model_dump(),
            similarity_score=similar_map.get(book.id, {}).get("score", 0),
            cosine_similarity=similar_map.get(book.id, {}).get("cosine_similarity"),
        )
        for book in deduped
    ]


@router.get("/{book_id}/series-neighbors", response_model=SeriesNeighborsOut)
async def get_series_neighbors(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get next/previous books in the same series, with series progress."""
    book = await get_accessible_book(book_id, current_user, db)

    series_name = book.display_series
    current_index = book.display_series_index
    if not series_name:
        return SeriesNeighborsOut()

    is_admin = current_user.role == UserRole.admin
    # "The book's series is this one", spelled so that the indexes on the
    # two columns can answer it — an equality on the coalesce of them
    # reads every book.
    in_series = or_(
        Book.series == series_name,
        and_(Book.series.is_(None), Book.epub_series == series_name),
    )
    index_col = coalesce(Book.series_index, Book.epub_series_index)

    # Accessible libraries subquery (deny-list: exclude libraries user is excluded from)
    if is_admin:
        accessible_libs = select(Library.id).scalar_subquery()
    else:
        accessible_libs = (
            select(Library.id)
            .where(
                ~exists(
                    select(UserLibraryExclusion.library_id).where(
                        UserLibraryExclusion.user_id == current_user.id,
                        UserLibraryExclusion.library_id == Library.id,
                    )
                )
            )
            .scalar_subquery()
        )

    # Series identity is scoped per library, so neighbors stay within the
    # current book's own library set (e.g. a light novel and its manga
    # adaptation share a name but are different series).
    scoped_libs = (
        select(LibraryBook.library_id)
        .where(
            LibraryBook.book_id == book_id,
            LibraryBook.library_id.in_(accessible_libs),
        )
        .scalar_subquery()
    )

    # Subquery: book IDs in the same library set as the current book
    accessible_book_ids = (
        select(LibraryBook.book_id)
        .where(LibraryBook.library_id.in_(scoped_libs))
        .scalar_subquery()
    )

    # Base: books in same series within the current book's libraries (excluding current)
    base = select(Book).where(
        in_series,
        index_col.isnot(None),
        Book.id != book_id,
        Book.id.in_(accessible_book_ids),
    )

    next_book = None
    prev_book = None

    if current_index is not None:
        # Next: smallest index > current (prefer newest edition if same index)
        result = await db.execute(
            base.where(index_col > current_index)
            .order_by(index_col.asc(), Book.created_at.desc())
            .limit(1)
        )
        next_book = result.scalar_one_or_none()

        # Previous: largest index < current (prefer newest edition if same index)
        result = await db.execute(
            base.where(index_col < current_index)
            .order_by(index_col.desc(), Book.created_at.desc())
            .limit(1)
        )
        prev_book = result.scalar_one_or_none()

    # Series progress: count distinct volumes (not books, since editions share index)
    # Work-aware: a volume is "read" if ANY edition in its Work is read by this user
    from sqlalchemy import case

    # Subquery: book IDs that this user has read (direct or via work propagation)
    user_read_books = (
        select(UserBookInteraction.book_id)
        .where(
            UserBookInteraction.user_id == current_user.id,
            UserBookInteraction.reading_status == "read",
        )
        .scalar_subquery()
    )

    # A book counts as "read" if it's directly read OR any work-sibling is read
    is_read = or_(
        Book.id.in_(user_read_books),
        exists(
            select(literal_column("1"))
            .select_from(Book.__table__.alias("sibling"))
            .where(
                literal_column("sibling.work_id").isnot(None),
                literal_column("sibling.work_id") == Book.work_id,
                literal_column("sibling.id").in_(user_read_books),
            )
        ),
    )

    progress_result = await db.execute(
        select(
            func.count(func.distinct(index_col)),
            func.max(index_col),
            func.count(
                func.distinct(
                    case(
                        (is_read, index_col),
                    )
                )
            ),
        )
        .select_from(Book)
        .join(LibraryBook, LibraryBook.book_id == Book.id)
        .where(
            in_series,
            index_col.isnot(None),
            LibraryBook.library_id.in_(scoped_libs),
        )
    )
    total_in_library, max_series_index, read_count = progress_result.one()
    total_in_library = total_in_library or 0
    read_count = read_count or 0

    def _brief(b: Book) -> SeriesBookBrief:
        return SeriesBookBrief(
            id=b.id,
            title=b.display_title,
            authors=b.display_authors,
            cover_path=b.cover_path,
            series_index=b.display_series_index,
        )

    return SeriesNeighborsOut(
        series_name=series_name,
        current_index=current_index,
        next=_brief(next_book) if next_book else None,
        previous=_brief(prev_book) if prev_book else None,
        progress=SeriesProgress(
            total_in_library=total_in_library,
            max_series_index=max_series_index,
            read_count=read_count,
        ),
    )


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
        raise HTTPException(status_code=404, detail="Book not found")

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
        raise HTTPException(status_code=400, detail="Invalid source")
    validated_source = source

    result = await db.execute(
        select(ExternalMetadata).where(
            ExternalMetadata.book_id == book_id,
            ExternalMetadata.source == validated_source,
        )
    )
    meta = result.scalar_one_or_none()
    if not meta:
        raise HTTPException(status_code=404, detail="External metadata not found")
    await db.delete(meta)
    await db.commit()

    # Re-run tag mapping
    from app.services.tag_mapping import generate_tags_from_metadata

    await generate_tags_from_metadata(db, book_id)
    await db.commit()
