import logging
import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy import and_, exists, func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.functions import coalesce

from app import errors
from app.database import get_db
from app.deps import get_current_user, require_admin
from app.models.book import Book
from app.models.book_text import BookTextChunk
from app.models.library import Library, LibraryBook, UserLibraryExclusion
from app.models.reading import UserBookInteraction
from app.models.user import User, UserRole
from app.schemas.book import (
    BookIdsRequest,
    BookLibraryUpdate,
    BookOut,
    PhysicalBookCreate,
    SeriesBookBrief,
    SeriesNeighborsOut,
    SeriesProgress,
)
from app.services.access import (
    get_accessible_book,
    get_books,
)
from app.services.book_files import (
    book_files,
)
from app.services.ingest import (
    commit_ingested,
    discard_ingested,
    ingest_upload,
    require_upload_permission,
    upload_suffix,
    validate_upload_library,
)
from app.services.storage import (
    cover_url_allowed,
    delete_file,
    download_cover,
    get_cover_path,
)
from app.tasks.metadata import fetch_book_metadata

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
        raise errors.UPLOAD_FORMAT(status_code=400)

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
        raise errors.BOOK_NOT_FOUND()

    lib_result = await db.execute(select(Library).where(Library.id == body.library_id))
    target = lib_result.scalar_one_or_none()
    if not target:
        raise errors.LIBRARY_NOT_FOUND()
    if target.calibre_path:
        raise errors.MOVE_INTO_CALIBRE()

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
        raise errors.MOVE_BOOK_IN_WORK()

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
            raise errors.MOVE_OUT_OF_CALIBRE()
        membership.library_id = body.library_id
        membership.added_by = current_user.id
    await db.commit()
    return {"status": "moved"}


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


@router.post("/delete", status_code=status.HTTP_204_NO_CONTENT)
async def delete_books(
    body: BookIdsRequest,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Delete several books at once, all or none. Not Calibre books: the
    next sync would bring them back."""
    books = await get_books(db, list(dict.fromkeys(body.book_ids)))
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
        raise errors.BOOK_NOT_FOUND()
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
