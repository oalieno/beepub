# 023 - iOS Manga Lazy Image Loading

## Problem
Opening a manga (200+ images) on iOS Capacitor took 30+ seconds before the first page appeared. The reader showed a spinner while epub.js's `resources.replacements()` fetched ALL images as blob URLs via `Promise.all()` before resolving the book opening promise.

This was only an issue on iOS native — the web version loaded images on-demand via cookie auth.

## Root Cause Chain

1. **Why blob URLs?** In Capacitor, the WebView runs at `capacitor://localhost` while the API is at a remote server. The backend's HttpOnly cookie has `samesite=lax`, so iframe `<image>` subrequests don't send cookies. Verified: cookie-only `fetch()` returns **401**, `fetch()` with Bearer token returns **200**.

2. **Why slow?** epub.js's `replacements()` uses `Promise.all()` on every asset in the manifest (images, CSS, fonts) and blocks `book.opening.resolve()` until all complete. A manga with 200 images means 200 sequential-ish XHR requests before anything renders.

3. **Why not just use external hooks?** We tried `rendition.hooks.content` (fires AFTER view is visible → broken image flash) and `spine.hooks.serialize` + `rendition.hooks.content` (serialize strips src, content replaces with blob → first page still broken due to timing). External hooks can't reliably run before the view is shown.

## Solution
Modified the epub.js fork directly (we own it) — two files:

### resources.js
- `replacements()`: Only blocks on CSS/fonts. Records image indices in `_imageIndices` set but does NOT fetch them.
- `_fetchImage(index)`: On-demand fetch for a single image. Caches the promise in `imagePromises` map, stores the blob URL in `replacementUrls[index]` when resolved.
- `substituteAsync(content, url)`: Scans the section HTML for image asset hrefs, calls `_fetchImage()` for each match, awaits only those, then calls the existing sync `substitute()`.

### book.js
- `replacements()` serialize hook changed from sync to async — returns `resources.substituteAsync()` promise. Since `Hook.trigger()` already does `Promise.all(promises)` and `section.render()` awaits the hook, images are replaced in the HTML string BEFORE DOM injection. No flash.

### image-prefetch.ts
- Native mode: calls `resources._fetchImage(i)` for adjacent sections' images (fire-and-forget). When user navigates there, `substituteAsync` finds blob URL already resolved → instant.
- Web mode: falls back to `new Image()` for browser cache warming (cookie auth works).

## Debugging Lessons Learned

### 1. `querySelectorAll` doesn't match SVG namespaced attributes
`doc.querySelectorAll('image[xlink\\:href]')` returns **0 results** for `<image xlink:href="...">`. CSS selectors don't support XML namespace prefixes with colon. Fix: select `image` without attribute condition, then use `getAttributeNS()` in JS.

### 2. `relativeTo()` returns absolute URLs in directory mode
`resources.relativeTo(sectionUrl)` returns fully resolved absolute URLs like `https://server/api/books/.../EPUB/image/0.jpg`. But the serialized HTML contains the original relative path `image/0.jpg`. So `content.indexOf(relUrl)` never matches. Fix: check both the raw `href` from the manifest AND the resolved URL.

### 3. `img.getAttribute("src")` vs `img.src` (DOM property)
In an iframe with a `<base>` tag, `getAttribute("src")` returns the raw attribute value (relative path), while `img.src` (the DOM property) returns the fully resolved URL. For XHR fetching, you need the resolved URL. This was the fix that made the debug version work but the clean version break.

### 4. Hook.trigger() runs hooks in forEach but with same args
All hooks registered on the same Hook instance receive the **same original arguments** from `trigger()`. If hook A modifies `section.output`, hook B must read `section.output` (not the `output` parameter) to see A's changes. Both hooks run in the same synchronous `forEach`, so A's side effects are visible to B.

### 5. Starting 200+ fetches "in background" still saturates the connection
Even without `await`, calling `createUrl()` for 200 images starts 200 XHR requests. The browser's 6-connection limit means they queue up, and the first section's image might be stuck behind 199 others. True lazy = only fetch when the section is about to render.

### 6. Don't assume — verify with logs
We assumed WKWebView cookies would work because the login endpoint sets an HttpOnly cookie. Wrong — `samesite=lax` prevents it on cross-origin subrequests. A simple two-line test (fetch with/without auth header, log status codes) proved the assumption false and saved hours of wrong-direction debugging.

### 7. When hacking around a library fails, modify the library
We spent multiple iterations trying to work around epub.js's behavior with external hooks (serialize → strip src, content → replace with blob URL). Each approach had timing or scoping issues. Once we modified the epub.js fork directly (making the serialize hook async in `book.js` and adding `substituteAsync` in `resources.js`), the fix was clean and reliable — images are replaced before DOM injection, guaranteed by the existing promise chain in `section.render()`.

## Key Files
- `frontend/src/lib/epubjs/resources.js` — `replacements()`, `_fetchImage()`, `substituteAsync()`
- `frontend/src/lib/epubjs/book.js` — async serialize hook
- `frontend/src/lib/components/reader/image-prefetch.ts` — dual-mode prefetch
- `frontend/src/lib/components/reader/EpubReader.svelte` — updated comments only
