"""Meta-tests for the metadata plugin registry: discovery, declaration
honesty, and import purity. These are the guardrails that keep drop-in
plugins honest."""

import subprocess
import sys
from pathlib import Path

from app.plugins.metadata import registry
from app.plugins.metadata.base import RECORD_FIELDS, Clue

BUILTIN_ORDER = [
    "goodreads",
    "readmoo",
    "google_books",
    "hardcover",
    "books_tw",
    "kingstone",
    "pubu",
    "open_library",
]


def test_discovers_all_builtin_plugins_in_preferred_order():
    assert [cls.name for cls in registry.all_plugins()] == BUILTIN_ORDER


def test_declarations_are_honest():
    for cls in registry.all_plugins():
        assert cls.name and cls.label, cls
        assert cls.kind in ("api", "scraper"), cls.name
        assert cls.accepts, f"{cls.name} declares no accepted clues"
        assert cls.provides, f"{cls.name} declares no provided fields"
        unknown = cls.provides - RECORD_FIELDS
        assert not unknown, f"{cls.name} provides unknown fields: {unknown}"
        assert set(cls.secret_settings_keys) <= set(cls.settings_keys), cls.name
        assert cls.ratelimit_cooldown > 0, cls.name

        # Manual-linking metadata is all-or-nothing and equivalent to
        # declaring the URL clue.
        linking = (cls.url_prefix, cls.id_pattern, cls.id_hint)
        if Clue.URL in cls.accepts:
            assert all(linking), f"{cls.name} accepts URL but lacks linking data"
        else:
            assert not any(linking), f"{cls.name} has linking data without URL clue"


def test_cover_hosts_union_covers_the_known_hosts():
    # storage.COVER_URL_ALLOWED_HOSTS derives from this union — a plugin
    # silently losing a host declaration would shrink the SSRF allowlist.
    assert registry.cover_allowed_hosts() == frozenset(
        {
            "books.google.com",
            "books.googleusercontent.com",
            "lh3.googleusercontent.com",
            "covers.openlibrary.org",
            "im1.book.com.tw",
            "im2.book.com.tw",
            "cdn.readmoo.com",
            "assets.hardcover.app",
            "cdn.kingstone.com.tw",
            "res1.pubu.tw",
            "res2.pubu.tw",
            "res3.pubu.tw",
            "res4.pubu.tw",
        }
    )

    from app.services.storage import COVER_URL_ALLOWED_HOSTS

    assert COVER_URL_ALLOWED_HOSTS == registry.cover_allowed_hosts()


def test_enabled_defaults_to_true_and_respects_toggle():
    cls = registry.get_plugin_class("goodreads")
    assert registry.is_enabled(cls, {})
    assert registry.is_enabled(cls, {"metadata_source_goodreads_enabled": "true"})
    assert not registry.is_enabled(cls, {"metadata_source_goodreads_enabled": "false"})


def test_enabled_plugins_filters_by_need_and_have():
    names = [p.name for p in registry.enabled_plugins({})]
    assert names == BUILTIN_ORDER

    cover_by_isbn = [
        p.name for p in registry.enabled_plugins({}, need="cover_url", have={Clue.ISBN})
    ]
    assert cover_by_isbn == [
        "readmoo",
        "google_books",
        "books_tw",
        "kingstone",
        "open_library",
    ]

    disabled = {"metadata_source_books_tw_enabled": "false"}
    assert [
        p.name
        for p in registry.enabled_plugins(disabled, need="cover_url", have={Clue.ISBN})
    ] == ["readmoo", "google_books", "kingstone", "open_library"]

    # A title-only query never reaches ISBN-only plugins.
    by_title = [p.name for p in registry.enabled_plugins({}, have={Clue.TITLE})]
    assert "books_tw" in by_title
    assert "kingstone" in by_title
    assert "open_library" not in by_title


def test_job_plugins_respect_source_list_and_toggles():
    # Empty list = every enabled plugin.
    assert [p.name for p in registry.job_plugins({})] == BUILTIN_ORDER

    # The job list narrows; unknown names are ignored.
    listed = {"metadata_job_sources": "goodreads, books_tw, nonexistent"}
    assert [p.name for p in registry.job_plugins(listed)] == ["goodreads", "books_tw"]

    # Disabled beats listed.
    disabled = {
        "metadata_job_sources": "goodreads, books_tw",
        "metadata_source_books_tw_enabled": "false",
    }
    assert [p.name for p in registry.job_plugins(disabled)] == ["goodreads"]

    assert registry.job_source_count({}) == len(BUILTIN_ORDER)
    assert registry.job_source_count(listed) == 2

    # The "none" sentinel — empty string already means "all enabled",
    # so switching off the background fetch entirely needs its own value.
    none = {"metadata_job_sources": registry.JOB_SOURCES_NONE}
    assert registry.job_plugins(none) == []
    assert registry.job_source_count(none) == 0


def test_settings_defaults_derive_from_registry():
    from app.services.settings import DEFAULTS, SECRET_SETTINGS

    for name in BUILTIN_ORDER:
        assert DEFAULTS[f"metadata_source_{name}_enabled"] == "true"
    assert DEFAULTS["google_books_api_key"] == ""
    assert DEFAULTS["hardcover_api_token"] == ""
    assert DEFAULTS[registry.JOB_SOURCES_KEY] == ""
    assert {"google_books_api_key", "hardcover_api_token"} <= SECRET_SETTINGS


def test_plugin_setting_defaults_and_secret_keys():
    defaults = registry.plugin_setting_defaults()
    for name in BUILTIN_ORDER:
        assert defaults[f"metadata_source_{name}_enabled"] == "true"
    assert defaults["google_books_api_key"] == ""
    assert defaults["hardcover_api_token"] == ""

    assert registry.plugin_secret_keys() == frozenset(
        {"google_books_api_key", "hardcover_api_token"}
    )


def test_plugin_package_imports_no_app_internals():
    """Plugins must stay importable in isolation: no app.services /
    app.models / app.routers / app.config anywhere in their import
    graph. Run in a subprocess so the test suite's own imports don't
    contaminate sys.modules."""
    code = (
        "import sys\n"
        "from app.plugins.metadata import registry\n"
        "registry.all_plugins()\n"
        "bad = [m for m in sys.modules if m.startswith("
        "('app.services', 'app.models', 'app.routers', 'app.config'))]\n"
        "assert not bad, f'plugin imports leaked: {bad}'\n"
    )
    backend_dir = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=backend_dir,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
