from app.services.metadata_sources.goodreads import GoodreadsSource
from app.services.metadata_sources.google_books import GoogleBooksSource
from app.services.metadata_sources.hardcover import HardcoverSource
from app.services.metadata_sources.readmoo import ReadmooSource

# Canonical source registry — init_metadata_sources() and the job queue's
# "fully fetched" threshold both derive from this, so adding/removing a
# source can't silently desync them.
ALL_SOURCE_CLASSES = (
    GoodreadsSource,
    ReadmooSource,
    GoogleBooksSource,
    HardcoverSource,
)

NUM_METADATA_SOURCES = len(ALL_SOURCE_CLASSES)

__all__ = [
    "ALL_SOURCE_CLASSES",
    "NUM_METADATA_SOURCES",
    "GoodreadsSource",
    "GoogleBooksSource",
    "HardcoverSource",
    "ReadmooSource",
]
