"""Metadata plugin registry, as served to the frontend."""

from pydantic import BaseModel


class MetadataSourceOut(BaseModel):
    name: str
    label: str
    kind: str  # "api" | "scraper"
    locale: str | None = None
    accepts: list[str]  # clues it can locate with (isbn/title/url)
    provides: list[str]  # BookRecord fields it can fill
    enabled: bool
    in_job: bool  # would the background job fetch it right now
    configured: bool  # all declared settings keys are non-empty
    setting_keys: list[str] = []
    secret_setting_keys: list[str] = []
    key_url: str | None = None  # where the operator gets a key
    # Manual-linking metadata (absent for non-linkable sources)
    url_prefix: str | None = None
    id_pattern: str | None = None
    id_hint: str | None = None


class MetadataSourcesOut(BaseModel):
    sources: list[MetadataSourceOut]


class MetadataSourceStats(BaseModel):
    """Operational health of one source: archive tallies from
    external_metadata plus the Redis health hash and cooldown flag."""

    books_found: int = 0
    books_not_found: int = 0  # empty markers: queried, nothing there
    last_fetched_at: str | None = None
    cooldown_seconds: int | None = None  # rate-limit cooldown remaining
    last_success_at: str | None = None
    last_error_at: str | None = None
    last_error: str | None = None
    last_ratelimited_at: str | None = None
    consecutive_failures: int = 0


class MetadataSourceStatsOut(BaseModel):
    stats: dict[str, MetadataSourceStats]
