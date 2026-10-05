# Vendored: foliate-js (subset)

- Upstream: https://github.com/johnfactotum/foliate-js
- Pinned commit: `78914aef4466eb960965702401634c2cb348e9b1` (2026-05-01,
  "Use original hrefs for external links and add isExternal in fb2.js (#129)")
- License: MIT — see `LICENSE` in this directory (verbatim copy of upstream).
  Copyright (c) 2022 John Factotum.

## Files taken

| File | Upstream lines | Role |
|---|---|---|
| `paginator.js` | 1130 | Renderer: `View` (one iframe's geometry) + `<foliate-paginator>` element |
| `epub.js` | 1083 | EPUB parser → `book` contract; takes a `{ loadText, loadBlob, getSize, sha1? }` loader |
| `epubcfi.js` | 349 | CFI parse / compare / fromRange / toRange |
| `overlayer.js` | 175 | SVG overlay layer for highlights (add / remove / redraw / hitTest) |
| `search.js` | 130 | In-book text search: `searchMatcher` (Intl.Segmenter / collator matching, excerpts) |
| `text-walker.js` | 43 | Text-node walker that turns match offsets back into Ranges |

Deliberately not taken: `view.js` (glue; replaced by `../../core.ts`), `reader.js` and `ui/`,
`mobi.js` / `fb2.js` / `comic-book.js` / `pdf.js` (formats are handled server-side),
`vendor/zip.js` (local books use the existing `jszip` dependency), `tts.js`, `dict.js`,
`opds.js`, `progress.js`, `footnotes.js` (its noteref/backlink heuristics are
re-implemented in `BookReader.svelte` against the pristine section document).
`fixed-layout.js` may be added later; record it here when it is.

## Rules

1. The initial import is byte-identical to upstream at the pinned commit.
2. This directory is excluded from Prettier (`.prettierignore`) and from
   `svelte-check` (`tsconfig.json` `exclude`) so local edits stay reviewable
   against upstream: `diff <upstream>/<file> <this dir>/<file>`.
3. Every local modification adds one line to the changelog below
   (date · file · what · why). Keep the sizing core of `paginator.js`
   (`#beforeRender` / `columnize` / `expand` / `#scrollToAnchor`) untouched
   unless the changelog line explains why.
4. Pulling an upstream fix: diff upstream between the pinned commit and the
   fix, port by hand, then bump the pinned commit here.

## Changelog

- 2026-09-03 · all · initial import of the four files above, unmodified.
- 2026-09-03 · paginator.js · `attributeChangedCallback`: `gap` and `margin` call `render()` like `max-inline-size` · under a max-size cap the container does not resize, so the observer never applied the new value (found by the G0 probe on a 900px viewport).
- 2026-09-03 · paginator.js · removed `#onTouchStart/Move/End`, their listener registration and the `#touchState`/`#touchScrolled` fields · gestures are the integration layer's (tap zones, swipe, iOS long-press selection arbitration); `scrollBy()`/`snap()` stay public for the finger-follow page-turn mode.
- 2026-09-05 · paginator.js · `#beforeRender`: a `gap` given in px is used as-is (the `%` form keeps the evening-out transform) · the settings sheet sets margins in px; a % of the container would need re-pushing on every container resize.
- 2026-09-05 · paginator.js · host CSS: in `.vertical` the grid swaps axes — gap (inline padding) on the rows, margin (block outer margin) on the columns; `#container`/`#header`/`#footer` placed accordingly (scrolled flow untouched) · upstream keeps margin on the rows in every writing mode (for running heads, which BeePub does not use), so a vertical book's top/bottom gutter was margin + gap/2 and its sides gap/2 only; now "top/bottom" and "left/right" map to one engine value each in both writing modes. CSS only — `columnize`/`expand`/`#scrollToAnchor` untouched; paged-mode scroll math never reads the margin, so which tracks bound the container does not matter to it.
- 2026-09-05 · search.js, text-walker.js · added, unmodified (upstream at the pinned commit) · in-book search for read-ng (G2 ⑤); `ReaderCore.search()` replaces the `view.js` glue around them.
- 2026-10-04 · paginator.js · added `reload(anchor, styles)` next to `goTo` · the per-book writing-direction override changes the body's writing mode through the injected styles, and the View reads writing mode/direction once at load; `#goTo` to the current index does not load again. Unloads before loading (the Loader would otherwise revoke the live blob URL on a repeated reload) and hands the new styles to the new document only. Sizing core untouched.
- 2026-10-04 · epub.js · `resolveCFI(cfi, filter)` (both the `Resources` method and the `EPUB` passthrough) hands an optional node filter to `CFI.toRange` · a book forced vertical gets its short digit runs wrapped in `<beepub-tcy>` in the rendered document (`../../tcy.ts`); `epubcfi.js` already takes a filter that makes such an element transparent (SKIP: children indexed as the parent's, adjacent text nodes merged with running offsets), `resolveCFI` just had no way to pass one. `ReaderCore.load` binds the filter, so every resolved CFI reads a wrapped section exactly as the untouched one. `epubcfi.js` itself is unmodified.
- 2026-10-05 · paginator.js · `setImageSize`: in vertical writing an image's `max-width` is the container width, no longer minus `margin * 2` · since the 09-05 axis swap the vertical container already sits inside the side margins, so they were subtracted twice: a full-page illustration came out a margin narrower than its page, flush right, with a line of text squeezed in beside it. The horizontal branch and the sizing core are untouched.
- 2026-10-06 · paginator.js · `#turnPage`: the 100ms pause that follows a page turn is skipped while the host carries the `no-turn-lock` attribute · the slide page turn (`../../slide.ts`) animates the turn itself on two layers and only then has the paginator jump; a turn asked for mid-slide ends the slide early and follows at once, and the pause would silently drop that second `next()`. The core sets the attribute only in the slide mode, so the fade keeps the lock its queueing is built on. `scrollBy()`/`snap()` and the `animated` attribute are no longer used by BeePub (the old finger-follow push); they stay as upstream wrote them. Sizing core untouched.
