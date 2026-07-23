"""Unit tests for the default resolve() in MetadataPlugin: exact-hit
short-circuit, fuzzy confidence floor, prefetched records, and the URL
clue."""

import asyncio

from app.plugins.metadata.base import (
    MIN_CONFIDENCE,
    BookQuery,
    BookRecord,
    Clue,
    MetadataPlugin,
    SearchCandidate,
    title_confidence,
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


# Real store listings for 平安文化《隨他們去》: the stores rewrote the
# marketing subtitle (數百萬→千萬, extra blurb) and added 【…】 bundle
# markers — the plain full-title ratio lands ~50, well under the floor.
_LET_THEM_QUERY = "隨他們去：改變數百萬人命運的心理技巧"
_LET_THEM_AUTHORS = ["梅爾．羅賓斯"]
_LET_THEM_KINGSTONE = "隨他們去：全球熱銷突破1000萬冊現象級巨作！改變千萬人命運的心理技巧【附放下執念明信片】"
_LET_THEM_READMOO = "隨他們去【附放下執念明信片圖】：全球熱銷突破1000萬冊現象級巨作！改變千萬人命運的心理技巧"


def test_cjk_subtitle_rewrite_clears_the_floor():
    for listing in (_LET_THEM_KINGSTONE, _LET_THEM_READMOO):
        score = title_confidence(
            _LET_THEM_QUERY, listing, _LET_THEM_AUTHORS, _LET_THEM_AUTHORS
        )
        assert score >= MIN_CONFIDENCE


def test_subtitle_overlap_distractors_stay_rejected():
    # Search-result neighbours that share subtitle vocabulary but are
    # different books.
    for distractor in (
        "改變百萬人命運的人際交往術",
        "他們就是我們：犯罪心理學家的人性思辨",
    ):
        assert title_confidence(_LET_THEM_QUERY, distractor) < MIN_CONFIDENCE


def test_series_siblings_share_main_title_but_stay_rejected():
    # Equal mains, unrelated subtitles: the weakest-link min() must keep
    # series entries apart.
    score = title_confidence(
        "哈利波特：火盃的考驗",
        "哈利波特：神秘的魔法石",
        ["J.K. 羅琳"],
        ["J.K. 羅琳"],
    )
    assert score < MIN_CONFIDENCE


def test_disjoint_authors_veto_the_split_view():
    # The veto only withholds the split-view boost — the full-title view
    # never consults authors (stores disagree on name forms: translated
    # vs original), so the pair here keeps its full view below the floor.
    query = "微光：那些留在山裡的話"
    listing = "微光：全球熱銷突破五百萬冊、售出四十國版權現象級巨作！那些留在山裡的話"
    matched = title_confidence(query, listing, ["張三"], ["張三"])
    vetoed = title_confidence(query, listing, ["王小明"], ["張三"])
    assert matched >= MIN_CONFIDENCE
    assert vetoed < MIN_CONFIDENCE


def test_resolve_accepts_subtitle_rewritten_listing():
    plugin = FakePlugin(
        [
            SearchCandidate(
                url="ebook",
                title="【電子書】隨他們去【附放下執念明信片圖】",
                authors=_LET_THEM_AUTHORS,
            ),
            SearchCandidate(
                url="print", title=_LET_THEM_KINGSTONE, authors=_LET_THEM_AUTHORS
            ),
        ]
    )
    record = asyncio.run(
        plugin.resolve(BookQuery(title=_LET_THEM_QUERY, authors=_LET_THEM_AUTHORS))
    )

    assert record is not None
    assert plugin.fetched == ["print"]


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
