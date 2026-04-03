from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar


class RateLimitError(Exception):
    """Raised when an external API returns 429 Too Many Requests."""

    def __init__(self, source: str):
        self.source = source
        super().__init__(f"{source} rate limited (429)")


@dataclass
class SearchResult:
    url: str
    title: str
    authors: list[str]
    score: float = 0.0
    prefetched: "FetchResult | None" = None  # Skip fetch() if search already has data


@dataclass
class FetchResult:
    source_url: str
    rating: float | None = None
    rating_count: int | None = None
    reviews: list[dict] | None = None
    raw_data: dict | None = None


class AbstractMetadataSource(ABC):
    source_name: ClassVar[str]

    @abstractmethod
    async def search(
        self, title: str, authors: list[str], isbn: str | None
    ) -> list[SearchResult]:
        pass

    @abstractmethod
    async def fetch(self, url: str) -> FetchResult:
        pass
