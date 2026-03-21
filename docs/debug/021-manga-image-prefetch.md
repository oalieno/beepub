# 021 - Manga Image Prefetch

## Problem
Manga EPUBs (one image per page as SVG `<image>`) had a multi-second delay on every page turn because each page's image was fetched on-demand from the backend (zip extraction → HTTP response).

## Solution
Added image prefetching in `EpubReader.svelte` that preloads the next 3 and previous 1 section's images after each page navigation.

### Key Files Modified
- `frontend/src/lib/components/reader/EpubReader.svelte` — prefetch logic
- `backend/app/routers/books.py` — added `Cache-Control` header on content endpoint

### Implementation Details

**Frontend (EpubReader.svelte):**
- On `relocated` event, walk the spine forward 3 / backward 1 sections
- Use `section.load()` to fetch + cache the XHTML (epub.js caches in `section.contents`)
- Parse the loaded DOM to find image URLs (`<img src>` and SVG `<image xlink:href>`)
- Prefetch images **sequentially** using `new Image()` (one at a time to avoid bandwidth competition)
- Cancel previous prefetch chain on new navigation (fast page flipping)
- Track prefetched URLs in a `Set` to avoid duplicates

**Backend (books.py):**
- Added `Cache-Control: private, max-age=86400, immutable` to the `/content/{path}` endpoint
- EPUB content is immutable so long cache is safe; `private` because auth is required

### Lessons Learned

1. **`fetch()` vs `new Image()` cache mismatch**: `fetch()` uses `cors` mode while iframe `<image>` uses `no-cors` — browsers may cache these separately. Using `new Image()` ensures the prefetched entry matches the iframe's request.

2. **`<link rel="prefetch">` too low priority**: Browser may never complete the prefetch if the user navigates before idle time. Direct `new Image()` is more reliable.

3. **Parallel prefetch hurts more than helps**: Loading 4 images simultaneously competes for bandwidth with the current page's image, making everything slower. Sequential loading (await each image) ensures the current page loads fast and prefetch fills in behind it.

4. **Cache-Control is essential**: Without cache headers, the browser won't reuse prefetched responses. The backend content endpoint had no `Cache-Control` at all.

5. **SVG `xlink:href` namespace**: In XML documents, `getAttribute("xlink:href")` may not work. Use `getAttributeNS("http://www.w3.org/1999/xlink", "href")` as primary, with fallbacks.
