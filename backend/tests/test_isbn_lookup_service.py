"""Unit tests for the ISBN fan-out orchestrator (lookup_isbn_all)."""

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
):
    class Fake(MetadataPlugin):
        name = plugin_name
        label = plugin_name
        accepts = plugin_accepts
        provides = plugin_provides

        async def resolve(self, query: BookQuery) -> BookRecord | None:
            if error is not None:
                raise error
            return record

    return Fake


def _run(monkeypatch, plugin_classes, settings=None):
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
    return asyncio.run(service.lookup_isbn_all("9789570849523", settings or {}))


def test_results_keep_registry_order_and_drop_empty_sources(monkeypatch):
    results = _run(
        monkeypatch,
        [
            _make_plugin("alpha", BookRecord(title="A")),
            _make_plugin("beta", None),
            _make_plugin("gamma", BookRecord(cover_url="https://c/g.jpg")),
        ],
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
    )
    assert [name for name, _ in results] == ["fine"]


def test_selection_skips_ratings_only_and_non_isbn_plugins(monkeypatch):
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

    results = _run(monkeypatch, [ratings_only, title_located, usable])
    assert [name for name, _ in results] == ["usable"]
