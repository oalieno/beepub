"""Unit tests for the metadata lookup fan-out orchestrator (lookup_all)."""

import asyncio

from app.plugins.metadata import service
from app.plugins.metadata.base import (
    BookQuery,
    BookRecord,
    Clue,
    MetadataPlugin,
    RateLimitError,
)


def _make_plugin(
    plugin_name: str,
    record: BookRecord | None,
    *,
    error: Exception | None = None,
    plugin_accepts: frozenset[Clue] = frozenset({Clue.ISBN}),
    plugin_provides: frozenset[str] = frozenset({"title", "cover_url"}),
    prefix: str | None = None,
):
    class Fake(MetadataPlugin):
        name = plugin_name
        label = plugin_name
        accepts = plugin_accepts
        provides = plugin_provides
        url_prefix = prefix

        async def resolve(self, query: BookQuery) -> BookRecord | None:
            if error is not None:
                raise error
            return record

    return Fake


def _run(monkeypatch, plugin_classes, query: BookQuery):
    def fake_enabled(settings_arg, *, need=None, have=None):
        selected = []
        for cls in plugin_classes:
            if need is not None and need not in cls.provides:
                continue
            if have is not None and not (cls.accepts & have):
                continue
            selected.append(cls({}))
        return selected

    monkeypatch.setattr(service.registry, "enabled_plugins", fake_enabled)
    monkeypatch.setattr(service.registry, "all_plugins", lambda: tuple(plugin_classes))
    monkeypatch.setattr(service.registry, "is_enabled", lambda cls, settings: True)
    return asyncio.run(service.lookup_all(query, {}))


def test_results_keep_registry_order_and_drop_empty_sources(monkeypatch):
    results = _run(
        monkeypatch,
        [
            _make_plugin("alpha", BookRecord(title="A")),
            _make_plugin("beta", None),
            _make_plugin("gamma", BookRecord(cover_url="https://c/g.jpg")),
        ],
        BookQuery(isbn="9789570849523"),
    )
    assert [name for name, _ in results] == ["alpha", "gamma"]


def test_one_failing_plugin_does_not_sink_the_rest(monkeypatch):
    results = _run(
        monkeypatch,
        [
            _make_plugin("broken", None, error=RuntimeError("boom")),
            _make_plugin("limited", None, error=RateLimitError("limited")),
            _make_plugin("fine", BookRecord(title="OK")),
        ],
        BookQuery(isbn="9789570849523"),
    )
    assert [name for name, _ in results] == ["fine"]


def test_selection_skips_ratings_only_and_clue_mismatched_plugins(monkeypatch):
    ratings_only = _make_plugin(
        "ratings",
        BookRecord(rating=4.0),
        plugin_provides=frozenset({"rating", "reviews"}),
    )
    title_located = _make_plugin(
        "titleonly",
        BookRecord(title="X"),
        plugin_accepts=frozenset({Clue.TITLE}),
    )
    usable = _make_plugin("usable", BookRecord(title="Y"))

    # ISBN query never reaches the title-only plugin…
    results = _run(
        monkeypatch,
        [ratings_only, title_located, usable],
        BookQuery(isbn="9789570849523"),
    )
    assert [name for name, _ in results] == ["usable"]

    # …and a title query never reaches the ISBN-only one.
    results = _run(
        monkeypatch,
        [ratings_only, title_located, usable],
        BookQuery(title="神"),
    )
    assert [name for name, _ in results] == ["titleonly"]


def test_url_dispatches_to_the_owning_plugin_only(monkeypatch):
    readmoo_like = _make_plugin(
        "readmoo_like",
        BookRecord(title="神", description="全文"),
        prefix="https://readmoo.com/book/",
    )
    other = _make_plugin(
        "other",
        BookRecord(title="wrong"),
        prefix="https://example.com/book/",
    )
    no_linking = _make_plugin("plain", BookRecord(title="wrong too"))

    results = _run(
        monkeypatch,
        [other, readmoo_like, no_linking],
        BookQuery(url="https://readmoo.com/book/210071675000101"),
    )
    assert [name for name, _ in results] == ["readmoo_like"]

    # A URL nobody owns resolves to nothing.
    results = _run(
        monkeypatch,
        [other, readmoo_like, no_linking],
        BookQuery(url="https://unknown.example/x"),
    )
    assert results == []
