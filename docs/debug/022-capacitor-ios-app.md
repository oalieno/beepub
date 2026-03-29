# 022 — Capacitor iOS App with Offline Reading

## Problem

BeePub is a web-based EPUB reader (SvelteKit SSR + FastAPI). Users wanted a native iOS app for offline book reading. Goal: single codebase producing both web and iOS app, no fork.

## Architecture: Dual Build Target

```
pnpm build          → adapter-node (SSR web, unchanged)
pnpm build:app      → adapter-static (SPA for Capacitor)
```

The same frontend codebase compiles to either SSR (web) or static SPA (Capacitor) depending on environment variables.

### Key Files

| File | Purpose |
|------|---------|
| `frontend/scripts/build-app.js` | Build script that temporarily removes `+layout.server.ts`, sets env vars, runs vite build |
| `frontend/src/routes/+layout.ts` | Universal load: SSR uses server data, SPA does client-side auth |
| `frontend/src/lib/platform.ts` | `isNative()` / `isWeb()` runtime detection via Capacitor |
| `frontend/src/lib/api/client.ts` | Dynamic base URL + conditional auth headers |
| `frontend/src/lib/stores/auth.ts` | Token in localStorage + cached user in Preferences |
| `frontend/src/lib/services/network.ts` | Reactive `isOnline` store wrapping `@capacitor/network` |
| `frontend/src/lib/services/offline.ts` | EPUB download manager with cover caching |
| `frontend/capacitor.config.ts` | Capacitor config (app ID, keyboard settings) |
| `backend/app/routers/auth.py` | Login returns both cookie AND `access_token` in response body |

## Auth: Dual Mode

Web and native use different auth mechanisms from the same backend:

| | Web | Native (iOS) |
|--|-----|-------------|
| **Storage** | HttpOnly cookie (set by backend) | `localStorage` token + Preferences cached user |
| **Request auth** | Cookie (implicit, browser sends it) | `Authorization: Bearer {token}` header |
| **Login flow** | Parse response, cookie auto-set | Parse `access_token` from response body, store in localStorage |
| **Offline** | N/A | Cached user from Preferences prevents auth chain from breaking |

### Why not just use Bearer everywhere?

Web SSR needs cookies for server-side auth. Mixing both would cause conflicts: a stale Bearer token could override a valid fresh cookie. So web deliberately sends NO Authorization header.

### Backend change

`POST /api/auth/login` returns `LoginResponse` with `access_token` field alongside the existing cookie:

```python
_set_token_cookie(response, token)  # HttpOnly cookie for web
return LoginResponse(..., access_token=token)  # JSON body for native
```

Backend `deps.py` already supported both Bearer header and cookie. No change needed there.

## Build Script Gotcha

`frontend/scripts/build-app.js` temporarily removes `+layout.server.ts` during the Capacitor build because `adapter-static` can't have server-only files. It restores the file after build completes.

This is fragile. If the script is interrupted (Ctrl+C), the file gets restored via a trap, but be aware. The alternative (separate svelte config file) didn't work reliably with SvelteKit's config resolution.

## Offline Download System

### How it works

1. User taps download on book detail page
2. `downloadBook()` in `offline.ts` fetches EPUB via streaming (with progress callback)
3. Writes to `Capacitor.Filesystem` at `books/{bookId}.epub` (base64 encoded)
4. Also downloads cover to `covers/{bookId}.jpg`
5. Stores manifest entry in `@capacitor/preferences` under key `offline-manifest`

### DownloadEntry manifest

```typescript
interface DownloadEntry {
  bookId: string;
  title: string;        // display_title, not raw EPUB title
  authors: string[];    // display_authors
  coverPath: string | null;
  filePath: string;
  downloadedAt: string;
  fileSize: number;
}
```

### Cover URI staleness (important gotcha)

`Capacitor.convertFileSrc()` converts a `file://` URI to a WebView-safe URI (e.g., `capacitor://localhost/_capacitor_file_/...`). This URI can become stale after app restart.

**Rule: never trust stored `coverPath`. Always re-derive from disk:**

```typescript
export async function getCoverSrc(entry: DownloadEntry): Promise<string | null> {
  try {
    const uriResult = await Filesystem.getUri({
      path: `covers/${entry.bookId}.jpg`,
      directory: Directory.Data,
    });
    return Capacitor.convertFileSrc(uriResult.uri);
  } catch { return null; }
}
```

Both `downloads/+page.svelte` and `+page.svelte` call `getCoverSrc()` for every entry on load.

### Reading offline books

`EpubReader.svelte` checks `isBookDownloaded()` on mount. If available, reads the local file as base64 → ArrayBuffer and passes it to epub.js instead of fetching from server. The epub.js `replacements: "blobUrl"` option handles authenticated images by inlining them as blob URLs.

## Network Status & Offline UX

### Reactive network store

`services/network.ts` wraps `@capacitor/network` in a Svelte writable store. Initialized in `+layout.svelte` onMount. Web always reports online.

### How offline state propagates

1. **Navbar**: Links with `requiresOnline: true` get `opacity-25` + `aria-disabled` + toast on click. Search and gacha icons also disabled.
2. **Homepage**: `offline` is `$derived(!$isOnline && isNative())`. Reactively switches between online content and offline view (downloaded books grid). `$effect` re-fetches data when coming back online.
3. **Reader toolbar**: AI buttons (Companion, Illustrations) greyed out with toast "AI features require an internet connection".
4. **Reader highlight menu**: Same treatment for AI Illustration and Ask Companion buttons in the text selection context menu.
5. **API client**: 401 responses are ignored when offline (token may still be valid, server just unreachable).

### Auth offline resilience

When `+layout.ts` fails to fetch `/api/auth/me` (server unreachable), it falls back to cached user from Preferences instead of returning `null` (which would trigger redirect to login).

## iOS-Specific Fixes

Several iOS WebView issues required workarounds:

| Issue | Fix | File |
|-------|-----|------|
| Double-tap zoom | `<meta name="viewport" ... maximum-scale=1` + CSS `touch-action: manipulation` | `app.html`, various components |
| Keyboard accessory bar (prev/next/done) | Capacitor keyboard plugin `hideFormAccessoryBar: true` | `capacitor.config.ts` |
| Safe area (notch, home indicator) | `env(safe-area-inset-top/bottom)` on navbar, toolbar, sidebars, toast | Multiple components |
| Text selection magnifier | Custom long-press handler replacing native selection | `EpubReader.svelte` |
| Auto-zoom on input focus | `font-size: 16px` minimum on search inputs | `SearchSidebar.svelte`, `SearchModal.svelte` |
| Cover images need auth | `authedSrc` Svelte action that fetches with Bearer header, creates blob URL | `actions/authedSrc.ts` |

## Toast Positioning

Toast is centered horizontally with `left-1/2 -translate-x-1/2` and respects iOS safe area:

```html
style="bottom: calc(1rem + env(safe-area-inset-bottom, 0px));"
```

## Lessons Learned

1. **Capacitor WebView URIs are ephemeral.** Never persist `convertFileSrc()` output. Always re-derive from `Filesystem.getUri()`.

2. **Cookie auth and Bearer auth don't mix well.** Keep them separate: cookies for web SSR, Bearer for native SPA. A stale Bearer token overriding a valid cookie causes silent auth failures.

3. **Build-time vs runtime platform detection matters.** `import.meta.env.VITE_CAPACITOR` is compile-time (use only for `ssr` export in `+layout.ts`). `isNative()` is runtime (use everywhere else). Mixing them up causes hydration mismatches or tree-shaking issues.

4. **iOS WebView purges iframe content on background.** The existing `visibilitychange` handler in EpubReader handles this (see `018-ios-pwa-resume-fixes.md`).

5. **base64 encoding for Filesystem writes.** Capacitor's Filesystem plugin requires base64 for binary data. Large files need chunked conversion to avoid stack overflow. A 100MB EPUB becomes ~133MB in base64.

6. **Offline state must be reactive, not snapshot-based.** The homepage originally used `$state(false)` set in a catch block (snapshot). This didn't react to airplane mode toggling. Changed to `$derived(!$isOnline && isNative())` which reacts to the network store.

7. **`display_title` vs `title`.** Backend computes `display_title` from EPUB metadata. Raw `title` field is often null or unhelpful. Always use `display_title` for user-facing strings (download manifest, page titles, etc.).
