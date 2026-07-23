# Metadata plugins

A metadata plugin locates a book from whatever clues it is given and
returns everything it can parse about it. One plugin = one `.py` file in
this directory.

**Adding a plugin is drop-in:**

1. Copy `_template.py` to `your_source.py` and fill it in (the
   registry skips `_`-prefixed modules, so the template itself is
   never loaded)
2. Put it in this directory
3. Restart the backend

Everything else is automatic: the registry discovers the class, its
enable toggle and declared settings keys appear in the settings
whitelist and the admin UI, the background fetch job and the ISBN lookup
start calling it, and its `cover_hosts` join the server-side cover
download allowlist. No DB change, no frontend change, no settings.py
edit.

> A plugin is arbitrary code running inside the backend — dropping a
> file in here means trusting it, same as any self-hosted plugin system.

## The contract

```python
async def resolve(self, query: BookQuery) -> BookRecord | None
```

That is the whole contract. `BookQuery` carries optional clues —
`title`, `authors`, `isbn`, `url` — and callers pass **everything they
have**; the plugin decides its own strategy (convention: exact ISBN
lookup first, fall back to title/author search). Return `None` when the
book can't be located confidently: for fuzzy title matches, anything
scoring below `MIN_CONFIDENCE` (60, rapidfuzz `token_sort_ratio`) must
be treated as not found — a wrong link is worse than no link.

When `query.url` is set it is a value **this same plugin** produced
earlier (its stored `source_url`) or that an admin entered for it, so
interpret it liberally — bare IDs, slugs, or full URLs.

`BookRecord` is the fixed output shape. Fill every field you can parse;
partial records are fine. Values are **raw, as the source states
them** — tags are the source's raw strings, dates keep the source's
format. Normalization (tag vocabulary mapping, date/language
canonicalization) happens centrally, never in plugins. If a source has
data worth keeping that has no field, the answer is adding an optional
field to `BookRecord` (storage is JSONB — no migration), not a raw dump.

### The default resolve()

Plugins that fit the common "search, pick the best hit, parse its book
page" shape don't override `resolve()` — they implement two hooks and
inherit it:

```python
async def _search(self, query: BookQuery) -> list[SearchCandidate]
async def _fetch(self, url: str) -> BookRecord
```

The contract is two-sided, and the naming encodes it: `resolve()` and
`candidates()` are what callers invoke; `_search`/`_fetch` are
implement-only — nothing outside the plugin ever calls them, and
calling them directly would bypass the confidence floor, the
prefetched short-circuit, and the resolve cache. The leading
underscore means "yours to write, not yours to call".

The default resolve handles the generic logic uniformly: a `url` clue
goes straight to `_fetch`; ISBN-located candidates (`exact=True`) win
outright; otherwise candidates are scored against `query.title` and
anything under `MIN_CONFIDENCE` is discarded; a candidate carrying
`prefetched` (search response already had the full document) skips the
`_fetch` round-trip. `_fetch` is not limited to one request —
google_books makes a volume-detail call inside it. If your source's
shape doesn't fit at all, override `resolve()` directly and crawl
however you need (open_library is a single-shot ISBN lookup; books_tw
has no reachable product page, so its picks re-run the search and match
the product id — every record rides in `prefetched`).

`_fetch` must be a real lookup of the identifier it is handed. Never
try to reconstruct a search query from an opaque ref (slugs for CJK
titles are year+UUID — no title words survive), and never substitute a
"best" hit when the identifier itself wasn't found: below that bar,
answering a bare record beats linking a different book.

### candidates() — the interactive two-step search

```python
async def candidates(self, query: BookQuery) -> list[SearchCandidate]
```

Optional. Exposes the plugin's raw search hits so a user can pick the
right book before anything is fetched — deliberately without the fuzzy
judgment resolve() applies, because here the user is the judge. The
picked candidate's `url` value comes back later as the `url` clue of a
resolve() call, so it must be something your `_fetch`/resolve
understands (a page URL or a bare source-side ID matching your
`id_pattern`). Callers echo the original search clues alongside that
`url` — a plugin whose record quality depends on its search response
(google_books merges it in) can re-run the search from them. The
default implementation lifts `_search()`; plugins that override
resolve() directly inherit an empty candidate list unless they also
implement this.

## Declarations

| ClassVar | Meaning |
|---|---|
| `name` | Machine key, shared by the settings toggle (`metadata_source_{name}_enabled`), the Redis rate-limit key, and the `external_metadata.source` column |
| `label` | Display string (usually a proper noun; not translated) |
| `kind` | `"api"` or `"scraper"` — display only (scrapers break when sites change) |
| `locale` | e.g. `"zh-TW"` — display only, helps operators decide what to enable |
| `accepts` | Which clues this plugin can locate with (`Clue.ISBN/TITLE/URL`). Used to skip pointless calls (a book without an ISBN never reaches an ISBN-only plugin) and shown in the admin UI |
| `provides` | Which `BookRecord` fields it can fill. Drives demand-driven selection ("need a cover" = plugins providing `cover_url`) and the admin UI |
| `cover_hosts` | Hosts its `cover_url` values live on — contributed to the SSRF allowlist for server-side cover downloads |
| `settings_keys` / `secret_settings_keys` | Config the operator must supply (API keys etc.). Auto-whitelisted, auto-rendered in the admin UI; secrets are masked on read |
| `ratelimit_cooldown` | Seconds to pause this source after it answers 429 |
| `url_prefix` / `id_pattern` / `id_hint` | Manual-linking metadata (all three set ⇔ `Clue.URL` in `accepts`): the admin UI validates an entered ID against `id_pattern` and builds the URL with `url_prefix` |

There is deliberately **no priority declaration** — display/fan-out
ordering is the caller's business (`registry._PREFERRED_ORDER`), and a
plugin can't know the global scale anyway.

## Framework guarantees (never reimplement these)

- **HTTP**: use `self._client(headers)` — timeout, redirect following,
  and 429 → `RateLimitError` are built in.
- **Caching**: the framework caches found resolve() results by
  (source, most-precise clue) for 24h — repeated questions never hit
  your upstream twice. Don't build your own cache.
- **Rate limiting**: raise/propagate `RateLimitError`; the job runner
  records the cooldown in Redis using your `ratelimit_cooldown`. No
  Redis, no `sleep`, no retry loops in plugin code.
- **Politeness pacing** between books in batch jobs is the runner's job.
- **Error ≠ not found**: raising an exception means "try again later";
  returning `None` means "searched, not found" and is recorded so the
  book isn't retried. Keep the existing pattern — catch source-specific
  failures, log, return an empty/partial record or `None`; always re-raise
  `RateLimitError`.

## Import rules (enforced by tests)

Plugin modules import only `app.plugins.metadata.base` plus
stdlib/httpx/bs4/rapidfuzz — never `app.services`, `app.models`,
`app.routers`, or `app.config`. Settings arrive as a plain
`dict[str, str]` at construction (`self.settings`); nothing is read at
import time. This keeps every plugin file self-contained and lets the
rest of the app import the registry without cycles.

`tests/test_plugin_registry.py` also enforces declaration honesty
(e.g. `provides` ⊆ `BookRecord` fields, manual-linking fields ⇔
`Clue.URL` in accepts) — a plugin that declares what it doesn't
implement fails CI.
