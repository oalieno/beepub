"""Plugin discovery and selection.

The registry scans this package for MetadataPlugin subclasses — adding
a plugin is dropping a .py file here and restarting the backend. No
hardcoded class list, no DB change, no settings.py edit.

Import rule: this module imports only base + plugin modules, and plugin
modules import nothing from app.*, so app.services/settings/storage may
import the registry without cycles.
"""

import importlib
import pkgutil

from app.plugins.metadata.base import Clue, MetadataPlugin

# Display/fan-out ordering for the built-in plugins (callers' choice,
# never self-declared by plugins). Unknown drop-ins sort after these,
# alphabetically.
_PREFERRED_ORDER = (
    "goodreads",
    "readmoo",
    "google_books",
    "hardcover",
    "books_tw",
    "kingstone",
    "pubu",
    "open_library",
)

_NON_PLUGIN_MODULES = {"base", "registry", "service", "store"}

_cache: tuple[type[MetadataPlugin], ...] | None = None


def all_plugins() -> tuple[type[MetadataPlugin], ...]:
    global _cache
    if _cache is None:
        package = importlib.import_module(__package__)
        found: dict[str, type[MetadataPlugin]] = {}
        for mod_info in pkgutil.iter_modules(package.__path__):
            if mod_info.name in _NON_PLUGIN_MODULES or mod_info.name.startswith("_"):
                continue
            module = importlib.import_module(f"{__package__}.{mod_info.name}")
            for obj in vars(module).values():
                if (
                    isinstance(obj, type)
                    and issubclass(obj, MetadataPlugin)
                    and obj is not MetadataPlugin
                    and obj.__module__ == module.__name__
                ):
                    found[obj.name] = obj

        def sort_key(name: str) -> tuple[int, str]:
            if name in _PREFERRED_ORDER:
                return (_PREFERRED_ORDER.index(name), name)
            return (len(_PREFERRED_ORDER), name)

        _cache = tuple(found[name] for name in sorted(found, key=sort_key))
    return _cache


def get_plugin_class(name: str) -> type[MetadataPlugin] | None:
    for cls in all_plugins():
        if cls.name == name:
            return cls
    return None


def enabled_key(name: str) -> str:
    return f"metadata_source_{name}_enabled"


def is_enabled(cls: type[MetadataPlugin], settings: dict[str, str]) -> bool:
    """Every plugin defaults to enabled; the operator opts out."""
    return settings.get(enabled_key(cls.name), "true") != "false"


def enabled_plugins(
    settings: dict[str, str],
    *,
    need: str | None = None,
    have: set[Clue] | None = None,
) -> list[MetadataPlugin]:
    """Demand-driven selection: enabled plugins, optionally narrowed to
    those that provide `need` and can locate with any clue in `have`.
    Returns constructed instances (settings injected)."""
    selected: list[MetadataPlugin] = []
    for cls in all_plugins():
        if not is_enabled(cls, settings):
            continue
        if need is not None and need not in cls.provides:
            continue
        if have is not None and not (cls.accepts & have):
            continue
        selected.append(cls(settings))
    return selected


JOB_SOURCES_KEY = "metadata_job_sources"
# "No sources at all" needs its own sentinel because the empty string
# already means the default ("every enabled source") — without it,
# deselecting the last source would silently round-trip back to all.
JOB_SOURCES_NONE = "-"


def job_plugins(settings: dict[str, str]) -> list[MetadataPlugin]:
    """Plugins the background fetch job iterates: enabled ∩ the job's
    source-list setting (comma-separated names; empty = all enabled,
    JOB_SOURCES_NONE = background fetch off). Interactive surfaces
    (ISBN lookup, manual refetch) ignore the job list and see every
    enabled plugin."""
    selected = enabled_plugins(settings)
    raw = settings.get(JOB_SOURCES_KEY, "").strip()
    if not raw:
        return selected
    if raw == JOB_SOURCES_NONE:
        return []
    wanted = {name.strip() for name in raw.split(",") if name.strip()}
    return [p for p in selected if p.name in wanted]


def job_source_count(settings: dict[str, str]) -> int:
    """The metadata_backfill completion threshold: a book is done once
    it has a row for every source the job would fetch."""
    return len(job_plugins(settings))


def cover_allowed_hosts() -> frozenset[str]:
    """Union of every registered plugin's cover hosts — the SSRF
    allowlist for server-side cover downloads."""
    hosts: set[str] = set()
    for cls in all_plugins():
        hosts |= cls.cover_hosts
    return frozenset(hosts)


def plugin_setting_defaults() -> dict[str, str]:
    """Settings keys contributed by plugins: one enabled-toggle each,
    plus their declared config keys. Merged into the settings DEFAULTS
    whitelist so drop-in plugins need no settings.py edit."""
    defaults: dict[str, str] = {}
    for cls in all_plugins():
        defaults[enabled_key(cls.name)] = "true"
        for key in cls.settings_keys:
            defaults.setdefault(key, "")
    return defaults


def plugin_secret_keys() -> frozenset[str]:
    keys: set[str] = set()
    for cls in all_plugins():
        keys |= set(cls.secret_settings_keys)
    return frozenset(keys)
