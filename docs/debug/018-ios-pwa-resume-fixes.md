# 018 — iOS PWA Resume Fixes

## Problem

Two issues when using BeePub as an iOS PWA (Add to Home Screen) and returning from background:

1. **Login page flash with navbar**: After backgrounding and returning, the user briefly sees the login page with the navbar visible, even though they're still authenticated. Any navigation fixes it.
2. **Blank reader at 0% / 16px**: The epub reader shows empty content with default font size and 0% progress. Restarting or navigating back fixes it.

## Root Causes

### Issue 1: Auth state split-brain on SSR resume

iOS triggers a full page reload on PWA resume. `hooks.server.ts` validates the JWT by calling `/api/auth/me`. If the backend is unreachable (network not reconnected yet after resume), the catch block keeps the token but `locals.user` stays `null`. The layout receives `{ user: null, token: "..." }` from SSR. The `$effect` falls into the `else` branch calling `authStore.init()`, which restores user from localStorage — so the navbar shows. But page content was SSR-rendered with no user data, creating an inconsistent UI.

### Issue 2: iOS WebKit iframe content purge

iOS WebKit purges iframe content from memory when the app is backgrounded to reclaim resources. The existing `visibilitychange` handler only called `rendition.resize()`, which adjusts dimensions but doesn't re-render purged content. Additionally, if the progress API is unreachable on resume, there's no fallback for restoring reading position.

## Changes

### `frontend/src/routes/+layout.svelte`

- Added `authRecovering` state flag
- When SSR delivers `data.token` but `data.user === null`, show a "Loading…" screen instead of rendering the page
- Attempt client-side re-validation via `fetch('/api/auth/me')`
  - On success: `authStore.login(user, token)`
  - On 401/403: `authStore.logout()` + redirect to `/login`
  - On network error: keep localStorage state (user is likely still authenticated)
- Hide loading screen in `.finally()`

### `frontend/src/lib/components/reader/EpubReader.svelte`

- **localStorage progress cache** (in `relocated` handler): Saves `{ cfi, percentage, sectionIndex, sectionPage, fontSize }` to `localStorage` key `reader-progress-${bookId}` on every relocation event
- **localStorage fallback on restore** (in `onMount` progress restore): If `booksApi.getProgress()` fails, falls back to cached localStorage progress
- **Enhanced `visibilitychange` handler**: Detects if iframe content was purged by checking `rendition.manager.getContents()`. If purged, re-displays at saved `currentCfi` with retry (3 attempts, 1.5s delay). If content exists, just calls `rendition.resize()` as before.
- **`displayWithRetry()` helper**: Wraps `rendition.display()` with 3-attempt retry (1.5s delay between) for initial book load
- **Cleanup**: Added `handleVisibility` variable hoisted to component scope; properly removes `visibilitychange` listener in `onDestroy`
