import uuid
from datetime import date, datetime

from pydantic import AwareDatetime, BaseModel, Field, field_validator, model_validator


class RatingUpdate(BaseModel):
    rating: float | None = None  # 0.5-5 in 0.5 steps, or null


class FavoriteUpdate(BaseModel):
    is_favorite: bool


class ProgressUpdate(BaseModel):
    cfi: str
    # None = the reader's CFI moved before the canonical (locations-based)
    # percentage was known; the previously stored percentage is kept.
    percentage: float | None = None
    current_page: int | None = None
    font_size: int | None = None
    section_index: int | None = None
    section_page: int | None = None
    section_page_counts: list[int] | None = None
    total_pages: int | None = None
    # crengine-style xpointer computed by the reader for the same position;
    # kosync GET serves it to e-readers for a paragraph-level landing.
    xpointer: str | None = Field(default=None, max_length=1000)
    track_activity: bool = True


class KosyncMarkerOut(BaseModel):
    """E-reader position bridged from kosync, newer than the stored CFI.

    Written by the kosync bridge; the web PUT /progress rebuilds the whole
    progress dict, so the marker disappears once the user reads on the web.
    """

    percentage: float | None = None
    device: str | None = None
    synced_at: str | None = None
    # Chapter hint parsed from the device xpointer (DocFragment[N] → N-1).
    section_index: int | None = None
    # Raw device xpointer (present only when it parsed as an EPUB path):
    # the reader walks it through the section DOM for a paragraph-level jump.
    xpointer: str | None = None


class ProgressOut(BaseModel):
    cfi: str | None = None
    percentage: float | None = None
    current_page: int | None = None
    font_size: int | None = None
    section_index: int | None = None
    section_page: int | None = None
    section_page_counts: list[int] | None = None
    total_pages: int | None = None
    last_read_at: str | None = None
    kosync: KosyncMarkerOut | None = None


class HighlightCreate(BaseModel):
    # Client-supplied id makes creation idempotent (offline retry / device
    # sync). Omitted -> server generates, as before.
    id: uuid.UUID | None = None
    cfi_range: str
    text: str
    color: str = "yellow"
    note: str | None = None
    # TextQuoteSelector context for re-anchoring (see model comment).
    prefix: str | None = Field(default=None, max_length=255)
    suffix: str | None = Field(default=None, max_length=255)
    section_index: int | None = Field(default=None, ge=0)


class HighlightUpdate(BaseModel):
    color: str | None = None
    note: str | None = None
    # Healing: the client re-anchored the quote after the book file changed
    # and writes the new position back.
    cfi_range: str | None = Field(default=None, max_length=2000)
    section_index: int | None = Field(default=None, ge=0)


class HighlightOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    book_id: uuid.UUID
    cfi_range: str
    text: str
    color: str
    note: str | None
    prefix: str | None = None
    suffix: str | None = None
    section_index: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ReadingStatusUpdate(BaseModel):
    reading_status: str | None = (
        None  # want_to_read, currently_reading, read, did_not_finish
    )
    started_at: date | None = None
    finished_at: date | None = None


class NotesUpdate(BaseModel):
    notes: str | None = None  # markdown


class ManualProgressUpdate(BaseModel):
    """Hand-entered progress for physical (file-less) books, same 0..100
    scale the reader stores (beepub.ts: totalProgression * 100)."""

    percentage: float = Field(ge=0, le=100)


class ReadingActivityOut(BaseModel):
    date: date
    seconds: int

    model_config = {"from_attributes": True}


class ReadingStatsOut(BaseModel):
    current_streak: int
    longest_streak: int
    today_seconds: int
    goal_seconds: int | None


class ReadingGoalUpdate(BaseModel):
    goal_seconds: int | None = None  # null to remove goal

    model_config = {
        "json_schema_extra": {
            "examples": [{"goal_seconds": 1800}],
        }
    }


class InteractionOut(BaseModel):
    rating: float | None
    is_favorite: bool
    reading_progress: dict | None
    reading_status: str | None
    started_at: date | None
    finished_at: date | None
    notes: str | None
    updated_at: datetime

    model_config = {"from_attributes": True}


class PaginatedHighlights(BaseModel):
    items: list[HighlightOut]
    total: int


# --- Device sync (routers/device_sync.py) ---
#
# Sync payloads carry CLIENT timestamps: the device is the authority on
# when its writes happened, and the server merges by last-write-wins.
# AwareDatetime rejects naive stamps up front — a naive/aware comparison
# would raise (or silently misorder) deep inside the merge.


class SyncHighlightIn(BaseModel):
    id: uuid.UUID
    cfi_range: str = Field(max_length=2000)
    text: str
    color: str = Field(default="yellow", max_length=20)
    note: str | None = None
    prefix: str | None = Field(default=None, max_length=255)
    suffix: str | None = Field(default=None, max_length=255)
    section_index: int | None = Field(default=None, ge=0)
    created_at: AwareDatetime
    updated_at: AwareDatetime
    deleted_at: AwareDatetime | None = None


class SyncProgressIn(BaseModel):
    """ProgressUpdate minus track_activity (synced reading never counts
    toward activity/streaks) plus the client's LWW anchor."""

    cfi: str
    percentage: float | None = None
    current_page: int | None = None
    font_size: int | None = None
    section_index: int | None = None
    section_page: int | None = None
    section_page_counts: list[int] | None = None
    total_pages: int | None = None
    xpointer: str | None = Field(default=None, max_length=1000)
    last_read_at: AwareDatetime


class SyncInteractionIn(BaseModel):
    """Manually-edited interaction fields, each group under its own LWW
    anchor. A group is only considered when its stamp is present — clients
    send just the groups the user actually touched on-device. Status,
    started_at and finished_at travel as one group because they always
    change together (mirroring PUT /reading-status)."""

    reading_status: str | None = None
    started_at: date | None = None
    finished_at: date | None = None
    status_updated_at: AwareDatetime | None = None
    rating: float | None = None
    rating_updated_at: AwareDatetime | None = None
    is_favorite: bool | None = None
    favorite_updated_at: AwareDatetime | None = None

    @field_validator("reading_status")
    @classmethod
    def validate_reading_status(cls, v: str | None) -> str | None:
        if v is None:
            return v
        from app.models.reading import ReadingStatus

        valid = {s.value for s in ReadingStatus}
        if v not in valid:
            raise ValueError(f"must be one of: {', '.join(sorted(valid))}")
        return v

    @field_validator("rating")
    @classmethod
    def validate_rating(cls, v: float | None) -> float | None:
        if v is not None and not (0.5 <= v <= 5 and (v * 2).is_integer()):
            raise ValueError("must be 0.5-5 in 0.5 steps")
        return v

    @model_validator(mode="after")
    def favorite_needs_value(self) -> "SyncInteractionIn":
        if self.favorite_updated_at is not None and self.is_favorite is None:
            raise ValueError("is_favorite is required with favorite_updated_at")
        return self


class SyncInteractionOut(BaseModel):
    reading_status: str | None
    started_at: date | None
    finished_at: date | None
    status_updated_at: datetime | None
    rating: float | None
    rating_updated_at: datetime | None
    is_favorite: bool
    favorite_updated_at: datetime | None

    model_config = {"from_attributes": True}


class BookSyncRequest(BaseModel):
    # progress None = pull-only (the device has nothing saved yet).
    progress: SyncProgressIn | None = None
    highlights: list[SyncHighlightIn] = Field(default_factory=list, max_length=5000)
    # interaction None = pull-only; the response always carries the
    # server's snapshot so devices can fold web edits back.
    interaction: SyncInteractionIn | None = None


class HighlightSyncOut(HighlightOut):
    # HighlightOut deliberately hides the tombstone; the sync response must
    # expose it so devices can propagate deletions.
    deleted_at: datetime | None = None


class BookSyncResponse(BaseModel):
    # Raw JSONB passthrough — ProgressOut would strip xpointer/kosync,
    # which must round-trip for paragraph-level e-reader landings.
    progress: dict | None
    highlights: list[HighlightSyncOut]
    # None only when the user has never interacted with the book.
    interaction: SyncInteractionOut | None = None
