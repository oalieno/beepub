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

Deliberately not taken: `view.js` (glue; replaced by `../../core.ts`), `reader.js` and `ui/`,
`mobi.js` / `fb2.js` / `comic-book.js` / `pdf.js` (formats are handled server-side),
`vendor/zip.js` (local books use the existing `jszip` dependency), `tts.js`, `dict.js`,
`opds.js`, `progress.js`, `footnotes.js`. `search.js` + `text-walker.js` and
`fixed-layout.js` may be added later; record them here when they are.

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
