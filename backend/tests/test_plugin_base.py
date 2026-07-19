"""Unit tests for the default resolve() in MetadataPlugin: exact-hit
short-circuit, fuzzy confidence floor, prefetched records, and the URL
clue."""

import asyncio

from app.plugins.metadata.base import (
    BookQuery,
    BookRecord,
    Clue,
    MetadataPlugin,
    SearchCandidate,
)


class FakePlugin(MetadataPlugin):
    name = "fake"
    label = "Fake"
    accepts = frozenset({Clue.ISBN, Clue.TITLE, Clue.URL})
    provides = frozenset({"rating"})
    url_prefix = "https://fake.example/"
    id_pattern = r"^\d+$"
    id_hint = "e.g. 1"

    def __init__(self, candidates: list[SearchCandidate]):
        super().__init__({})
        self._candidates = candidates
        self.fetched: list[str] = []

    async def _search(self, query: BookQuery) -> list[SearchCandidate]:
        return self._candidates

    async def _fetch(self, url: str) -> BookRecord:
        self.fetched.append(url)
        return BookRecord(source_url=url, rating=4.0)


def test_url_clue_goes_straight_to_fetch():
    plugin = FakePlugin([SearchCandidate(url="unused", title="unused")])
    record = asyncio.run(plugin.resolve(BookQuery(url="https://fake.example/9")))

    assert record is not None
    assert record.source_url == "https://fake.example/9"
    assert plugin.fetched == ["https://fake.example/9"]


def test_exact_candidate_wins_without_title_scoring():
    plugin = FakePlugin(
        [
            SearchCandidate(url="fuzzy", title="Some Totally Different Book"),
            SearchCandidate(url="exact", exact=True),
        ]
    )
    # Fuzzy first in the list, but the exact hit must win.
    record = asyncio.run(plugin.resolve(BookQuery(title="極限返航", isbn="123")))

    assert record is not None
    assert plugin.fetched == ["exact"]


def test_low_confidence_matches_are_discarded():
    plugin = FakePlugin([SearchCandidate(url="wrong", title="完全無關的另一本書")])
    record = asyncio.run(plugin.resolve(BookQuery(title="極限返航")))

    assert record is None
    assert plugin.fetched == []


def test_best_scoring_candidate_is_fetched():
    plugin = FakePlugin(
        [
            SearchCandidate(url="worse", title="Project Hail"),
            SearchCandidate(url="better", title="Project Hail Mary"),
        ]
    )
    record = asyncio.run(plugin.resolve(BookQuery(title="Project Hail Mary")))

    assert record is not None
    assert plugin.fetched == ["better"]


def test_prefetched_record_skips_fetch():
    prefetched = BookRecord(source_url="slug", rating=4.5)
    plugin = FakePlugin(
        [SearchCandidate(url="slug", title="Project Hail Mary", prefetched=prefetched)]
    )
    record = asyncio.run(plugin.resolve(BookQuery(title="Project Hail Mary")))

    assert record is prefetched
    assert plugin.fetched == []


def test_no_candidates_and_no_title_return_none():
    plugin = FakePlugin([])
    assert asyncio.run(plugin.resolve(BookQuery(title="x"))) is None

    plugin = FakePlugin([SearchCandidate(url="a", title="a")])
    # Non-exact candidates can't be scored without a query title.
    assert asyncio.run(plugin.resolve(BookQuery(isbn="123"))) is None


def test_candidates_lift_search_without_judgment():
    hits = [
        SearchCandidate(url="1", title="完全無關的另一本書"),
        SearchCandidate(url="2", title="極限返航"),
    ]
    plugin = FakePlugin(hits)
    # Every hit comes back — even ones resolve() would score below the
    # confidence floor. The user is the judge in the two-step flow.
    assert asyncio.run(plugin.candidates(BookQuery(title="極限返航"))) == hits
    assert plugin.fetched == []


def test_candidates_default_to_empty_without_search():
    class SingleShot(MetadataPlugin):
        name = "single"
        label = "Single"
        accepts = frozenset({Clue.ISBN})
        provides = frozenset({"cover_url"})

        async def resolve(self, query: BookQuery) -> BookRecord | None:
            return None

    plugin = SingleShot({})
    assert asyncio.run(plugin.candidates(BookQuery(title="x"))) == []
