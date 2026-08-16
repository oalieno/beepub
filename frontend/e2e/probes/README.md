# Reader probes

Ad-hoc debugging harness for reader layout/interaction bugs, distilled from
real investigations (highlight-menu flicker, selection overlay geometry,
margin/gap pagination, vertical pageStep drift). Not part of the test suite —
these are for interactive diagnosis against a disposable stack.

## Setup

```sh
./e2e/stack.sh dev                    # working-tree mounts + vite dev — edits
                                      # apply in ~2s, ideal for probe loops
./e2e/stack.sh up                     # built image (run the e2e SUITE against this)
./e2e/stack.sh restart nginx          # after container recreation (stale upstream 502)
```

Probes run with plain node from `frontend/`:

```sh
node e2e/probes/example-alignment.mjs
BASE_URL=http://<docker-host>:8091 node e2e/probes/example-alignment.mjs   # remote docker daemon
```

## What lib.mjs gives you

- `adminApi()` — login (auto-register on a fresh stack) → authed request context
- `seedBook(api, title, epubPath?)` — find-or-upload, returns book id
- `openReader(bookId, {device, margin, fontSize, lineHeight, token})` —
  logged-in page with reader settings pre-seeded and the gesture coach mark
  suppressed; `device: "iphone"` = chromium + iPhone 13 descriptor (the
  reader's iOS paths are UA-gated; CDP still available)
- `measureAlignment(page)` — visible-page text insets + edge-cut rect count,
  axis-agnostic (works for vertical pagination)
- `armMenuWatcher(page)` / `menuTimeline(page)` — MutationObserver timeline of
  highlight-menu SHOW/HIDE (catches one-frame blinks)
- `touchTap(page, pt, holdMs)` — trusted CDP touch (quick tap or long-press)
- `pointOnWord(page, word, n)` — viewport coordinates of a word in the iframe

## Hard-won gotchas (do not relearn these)

- **CJK fonts must be installed on the machine** (`~/.fonts/NotoSansCJKtc-*`)
  or vertical-rl fragmentation degenerates (whole chapter renders as one
  overflowing page) and every vertical measurement lies.
- The paginated **iframe spans every column** of the chapter — its rect
  center is off-screen. Horizontal centering = `window.innerWidth / 2`.
- The fixture `e2e-test-book.epub` has so little text the image-book
  heuristic mutes reader gestures. Use `e2e-touch-book.epub` (text-heavy) or
  `e2e-vertical-long-book.epub` (multi-page vertical).
- Chromium synthesizes a click for quick taps but **not** after long holds —
  emulate WebKit's post-long-press click with CDP `Input.dispatchMouseEvent`.
- Tap-to-turn zones are parent-document buttons `min(48, margin)` px wide at
  the container edges: touches there never reach the iframe.
- `rtl` books: keyboard `ArrowLeft` = next page.
- Playwright WebKit needs system libs (`playwright install-deps webkit`,
  sudo); until installed, iOS behavior is emulated via chromium + UA + CDP.
