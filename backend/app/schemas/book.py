import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class BookTagNested(BaseModel):
    id: uuid.UUID
    tag: str
    label: str = ""
    category: str
    source: str = ""
    confidence: float

    model_config = {"from_attributes": True}

    def model_post_init(self, __context: object) -> None:
        if not self.label:
            from app.services.tags import TAG_LABELS

            self.label = TAG_LABELS.get(self.tag, self.tag)


class BookOut(BaseModel):
    id: uuid.UUID
    file_size: int | None  # None = physical book (no file)
    format: str
    cover_path: str | None
    epub_title: str | None
    epub_authors: list[str] | None
    epub_publisher: str | None
    epub_language: str | None
    epub_isbn: str | None
    epub_description: str | None
    epub_published_date: str | None
    epub_series: str | None = None
    epub_series_index: float | None = None
    epub_tags: list[str] | None = None
    title: str | None
    authors: list[str] | None
    publisher: str | None
    description: str | None
    published_date: str | None
    series: str | None = None
    series_index: float | None = None
    tags: list[str] | None = None
    field_sources: dict[str, str] | None = None
    word_count: int | None = None
    is_image_book: bool | None = None
    # Per-spine-section text sizes (chars), dense by spine index. The reader
    # interpolates reading percentage from these — position weight over total
    # weight — instead of generating epub.js locations. None until text
    # extraction has run; sections with no text weigh 0.
    section_weights: list[int] | None = None
    has_unresolved_reports: bool = False
    display_title: str | None
    display_authors: list[str] | None
    display_series: str | None = None
    display_series_index: float | None = None
    display_tags: list[str] | None = None
    book_tags: list[BookTagNested] = []
    work_id: uuid.UUID | None = None
    edition_count: int | None = None
    popularity_score: int = 0
    calibre_id: int | None = None
    calibre_added_at: datetime | None = None
    added_by: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
    library_id: uuid.UUID | None = None
    library_names: list[str] = []

    model_config = {"from_attributes": True}


class BookLibraryUpdate(BaseModel):
    """Target library for PUT /books/{id}/library — a book lives in exactly one."""

    library_id: uuid.UUID


class PaginatedBooks(BaseModel):
    items: list[BookOut]
    total: int

    model_config = {"from_attributes": True}


class BookWithInteractionOut(BookOut):
    reading_status: str | None = None
    is_favorite: bool = False
    user_rating: float | None = None
    reading_percentage: float | None = None
    last_read_at: str | None = None
    seed_book_id: uuid.UUID | None = None
    seed_book_title: str | None = None


class PaginatedBooksWithInteraction(BaseModel):
    items: list[BookWithInteractionOut]
    total: int

    model_config = {"from_attributes": True}


class BookSearchResult(BookOut):
    library_name: str | None = None


class PaginatedBookSearchResults(BaseModel):
    items: list[BookSearchResult]
    total: int


class BookMetadataUpdate(BaseModel):
    title: str | None = None
    authors: list[str] | None = None
    publisher: str | None = None
    description: str | None = None
    published_date: str | None = None
    series: str | None = None
    series_index: float | None = None
    tags: list[str] | None = None
    # Provenance map maintained by the edit page — replaced wholesale
    # when sent ({} clears everything). Values are plugin names or
    # "manual"; keys are the overridable fields plus "cover".
    field_sources: dict[str, str] | None = None

    @field_validator("field_sources")
    @classmethod
    def _known_fields_only(cls, value: dict | None) -> dict | None:
        if value is None:
            return None
        allowed = set(cls.model_fields) - {"field_sources"} | {"cover"}
        for key, source in value.items():
            if key not in allowed:
                raise ValueError(f"Unknown field: {key}")
            if not source or len(source) > 50:
                raise ValueError(f"Invalid source for {key}")
        return value


class PhysicalBookCreate(BaseModel):
    """A file-less Book row tracking a paper copy."""

    library_id: uuid.UUID
    title: str = Field(min_length=1, max_length=500)
    authors: list[str] = Field(default_factory=list)
    publisher: str | None = Field(default=None, max_length=255)
    description: str | None = None
    published_date: str | None = Field(default=None, max_length=50)
    isbn: str | None = Field(default=None, max_length=20)
    language: str | None = Field(default=None, max_length=10)
    series: str | None = Field(default=None, max_length=500)
    series_index: float | None = None
    # Cover image fetched server-side; restricted to known metadata hosts.
    cover_url: str | None = Field(default=None, max_length=1000)


class MetadataSearchCandidate(BaseModel):
    """One raw search hit from one source. `ref` is opaque (a full page
    URL or a bare source-side ID) — the pick step echoes it back as
    metadata-lookup's `ref` and only its owning plugin interprets it;
    `url` is a human-clickable page link when one can be derived."""

    source: str
    label: str
    ref: str
    title: str
    authors: list[str] = []
    url: str | None = None
    # Display garnish when the search response had them for free.
    publisher: str | None = None
    published_date: str | None = None
    cover_url: str | None = None


class MetadataSearchOut(BaseModel):
    candidates: list[MetadataSearchCandidate] = []


class IsbnSourceResult(BaseModel):
    """One source's bibliographic answer for an ISBN (raw, as the
    plugin parsed it) — the user picks which source to prefill from."""

    source: str
    label: str
    title: str | None = None
    authors: list[str] = []
    publisher: str | None = None
    description: str | None = None
    published_date: str | None = None
    language: str | None = None
    cover_url: str | None = None
    tags: list[str] = []
    # The source's own page for this book — provenance the user can
    # click to verify what was filled in.
    url: str | None = None


class IsbnCoverCandidate(BaseModel):
    source: str
    label: str
    url: str


class IsbnLookupOut(BaseModel):
    """Per-source fan-out results for the add-physical-book form.
    `results` holds sources that located the book (registry order);
    `covers` holds every distinct cover candidate, best-priority first."""

    results: list[IsbnSourceResult] = []
    covers: list[IsbnCoverCandidate] = []


class SeriesBookBrief(BaseModel):
    id: uuid.UUID
    title: str | None
    authors: list[str] | None
    cover_path: str | None
    series_index: float | None

    model_config = {"from_attributes": True}


class SeriesProgress(BaseModel):
    total_in_library: int
    max_series_index: float | None = None
    read_count: int


class SeriesNeighborsOut(BaseModel):
    series_name: str | None = None
    current_index: float | None = None
    next: SeriesBookBrief | None = None
    previous: SeriesBookBrief | None = None
    progress: SeriesProgress | None = None


class BookCoverUpdate(BaseModel):
    """Replace a book's cover from a source URL (server-side fetch,
    restricted to the plugin-declared cover hosts)."""

    url: str = Field(min_length=1, max_length=1000)


class BookReportCreate(BaseModel):
    issue_type: str
    description: str | None = None


class BookReportOut(BaseModel):
    id: uuid.UUID
    book_id: uuid.UUID
    reported_by: uuid.UUID | None
    issue_type: str
    description: str | None
    resolved: bool
    resolved_by: uuid.UUID | None
    created_at: datetime
    resolved_at: datetime | None
    book_title: str | None = None
    book_cover: str | None = None
    reporter_name: str | None = None

    model_config = {"from_attributes": True}


class ExternalMetadataUrlUpdate(BaseModel):
    source_url: str | None = None


class ExternalMetadataOut(BaseModel):
    id: uuid.UUID
    book_id: uuid.UUID
    source: str
    source_url: str | None
    rating: float | None
    rating_count: int | None
    reviews: list | None
    # The archived BookRecord (record store) — the edit-metadata page
    # reads per-field version candidates straight out of it, no refetch.
    record: dict | None = None
    fetched_at: datetime

    model_config = {"from_attributes": True}


class BookLocationsIn(BaseModel):
    """Client-generated epub.js locations (an opaque JSON array of CFIs)."""

    fingerprint: str = Field(min_length=1, max_length=255)
    # ~30 chars per CFI anchor; even a 5000-location monster stays well
    # under this cap, while garbage uploads can't balloon the table.
    locations: str = Field(min_length=2, max_length=1_000_000)

    @field_validator("locations")
    @classmethod
    def _must_be_json_array(cls, value: str) -> str:
        if not value.lstrip().startswith("["):
            raise ValueError("locations must be a JSON array")
        return value


class BookLocationsOut(BaseModel):
    fingerprint: str
    locations: str

    model_config = {"from_attributes": True}
