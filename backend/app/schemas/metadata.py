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
    # Manual-linking metadata (absent for non-linkable sources)
    url_prefix: str | None = None
    id_pattern: str | None = None
    id_hint: str | None = None


class MetadataSourcesOut(BaseModel):
    sources: list[MetadataSourceOut]
