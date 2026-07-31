import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test, expect } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";

const FIXTURE = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  "fixtures",
  "e2e-vertical-book.epub",
);
const LONG_FIXTURE = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  "fixtures",
  "e2e-vertical-long-book.epub",
);
const VPUNCT_FIXTURE = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  "fixtures",
  "e2e-vpunct-book.epub",
);
const CHAPTERS_FIXTURE = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  "fixtures",
  "e2e-vertical-chapters-book.epub",
);

test.use({ storageState: ADMIN_STATE });

// Correct vertical-rl (直排) rendering is the reason this reader exists —
// regressions here must fail CI, not wait for a bug report.
test("vertical book renders vertical-rl in the reader", async ({ page }) => {
  // Seed through the API (page.request shares the session cookie).
  const libraries = await (await page.request.get("/api/libraries")).json();
  const uploaded = await page.request.post("/api/books", {
    multipart: {
      file: {
        name: "vertical.epub",
        mimeType: "application/epub+zip",
        buffer: fs.readFileSync(FIXTURE),
      },
      library_id: libraries[0].id,
    },
  });
  expect(uploaded.ok()).toBeTruthy();
  const book = await uploaded.json();

  await page.goto(`/books/${book.id}/read`);
  const frame = page.frameLocator("iframe").first();
  await expect(frame.getByText("話說天下大勢").first()).toBeVisible({
    timeout: 30_000,
  });

  const writingMode = await page
    .locator("iframe")
    .first()
    .evaluate((el) => {
      const doc = (el as HTMLIFrameElement).contentDocument;
      if (!doc) return "no-document";
      return getComputedStyle(doc.documentElement).writingMode;
    });
  expect(writingMode).toBe("vertical-rl");
});

// Vertical pagination scrolls by a pageStep that MUST equal the page tile
// pitch exactly. When the reader container has a fractional height
// (browser zoom, flex sub-pixels), measuring the container and flooring it
// used to give a step 1px short of the pitch — the error accumulated one
// page at a time until pages visibly sheared (bottom cut off, previous
// page peeking at the top). The step now derives from layout.height, the
// same number the tiles are built from.
test("vertical pages stay on the grid with a fractional container height", async ({
  page,
}) => {
  const libraries = await (await page.request.get("/api/libraries")).json();
  const uploaded = await page.request.post("/api/books", {
    multipart: {
      file: {
        name: "vertical-long.epub",
        mimeType: "application/epub+zip",
        buffer: fs.readFileSync(LONG_FIXTURE),
      },
      library_id: libraries[0].id,
    },
  });
  expect(uploaded.ok()).toBeTruthy();
  const book = await uploaded.json();

  await page.addInitScript(() =>
    localStorage.setItem("reader-gestures-seen", "1"),
  );
  await page.goto(`/books/${book.id}/read`);
  await page.waitForSelector("iframe", { timeout: 30_000 });
  await page.waitForTimeout(3000);

  // Pin the reader to a fractional height and relayout.
  await page.evaluate(() => {
    const parent = document.querySelector(".epub-container")!
      .parentElement as HTMLElement;
    parent.style.height = "652.7px";
    parent.style.flex = "none";
    window.dispatchEvent(new Event("resize"));
  });
  await page.waitForTimeout(1500);

  const measure = () =>
    page.evaluate(() => {
      const ifr = document.querySelector("iframe") as HTMLIFrameElement;
      const doc = ifr.contentDocument!;
      const sc = document.querySelector(".epub-container")!;
      const box = sc.getBoundingClientRect();
      const ifrTop = ifr.getBoundingClientRect().top;
      const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT);
      let minTop = Infinity;
      let cut = 0;
      while (walker.nextNode()) {
        const n = walker.currentNode;
        if (!n.textContent?.trim()) continue;
        const rg = doc.createRange();
        rg.selectNodeContents(n);
        for (const r of rg.getClientRects()) {
          if (r.width <= 0 || r.height <= 0) continue;
          const top = r.top + ifrTop - box.top;
          const bottom = r.bottom + ifrTop - box.top;
          if (bottom > 1 && top < box.height - 1) {
            minTop = Math.min(minTop, top);
            if (top < -2 || bottom > box.height + 2) cut++;
          }
        }
      }
      return {
        minTop,
        cut,
        pages: (ifr.getBoundingClientRect().height / box.height) | 0,
      };
    });

  const first = await measure();
  // The environment must actually paginate the book (CJK-capable fonts);
  // otherwise the whole chapter collapses to one page and flips are no-ops.
  test.skip(first.pages < 4, "vertical fragmentation unavailable (no CJK fonts)");

  const tops: number[] = [first.minTop];
  for (let i = 0; i < 8; i++) {
    await page.keyboard.press("ArrowLeft"); // next page in an rtl book
    await page.waitForTimeout(400);
    const m = await measure();
    expect(m.cut).toBe(0);
    tops.push(m.minTop);
  }
  // Every page's first line sits at the same offset — no cumulative shear.
  for (const t of tops) {
    expect(Math.abs(t - tops[0])).toBeLessThanOrEqual(1.5);
  }
});

// iOS ships no TC font that can rotate punctuation in vertical writing, so
// the reader injects self-hosted punctuation subsets and pins them ahead of
// element-declared font stacks (EpubReader VPUNCT_*). The rotation itself
// and the cross-font axis alignment are only observable on a real Apple
// device — what CI can hold is the delivery mechanism. The fixture replays
// the trap combo of the book that shipped the bug: OPF says zh-TW but the
// chapter is lang="en", writing-mode is -webkit-prefixed only, and
// `p { font-family: serif }` bypasses the themed body stack.
test("vertical punctuation faces reach a book that bypasses the body font stack", async ({
  page,
}) => {
  const libraries = await (await page.request.get("/api/libraries")).json();
  const uploaded = await page.request.post("/api/books", {
    multipart: {
      file: {
        name: "vpunct.epub",
        mimeType: "application/epub+zip",
        buffer: fs.readFileSync(VPUNCT_FIXTURE),
      },
      library_id: libraries[0].id,
    },
  });
  expect(uploaded.ok()).toBeTruthy();
  const book = await uploaded.json();

  await page.goto(`/books/${book.id}/read`);
  const frame = page.frameLocator("iframe").first();
  await expect(frame.getByText("免費服務已終止").first()).toBeVisible({
    timeout: 30_000,
  });

  const state = await page
    .locator("iframe")
    .first()
    .evaluate((el) => {
      const doc = (el as HTMLIFrameElement).contentDocument!;
      const p = [...doc.querySelectorAll("p")].find((n) =>
        n.textContent?.includes("免費服務已終止"),
      ) as HTMLElement | undefined;
      const kai = doc.querySelector("span.kai") as HTMLElement | null;
      const em = doc.querySelector("em") as HTMLElement | null;
      return {
        writingMode: getComputedStyle(doc.documentElement).writingMode,
        faces: doc.getElementById("beepub-vpunct")?.textContent ?? "",
        pPin: p?.style.fontFamily ?? "",
        kaiPin: kai?.style.fontFamily ?? "",
        emPin: em?.style.fontFamily ?? "",
      };
    });

  // The -webkit-prefixed-only writing-mode still routes the vertical path.
  expect(state.writingMode).toBe("vertical-rl");

  // Both faces arrive in the iframe, and the range stays curated: it must
  // claim the bracket but not — or － (no vert forms in the subset source —
  // claiming them would render them unrotated instead of falling through).
  expect(state.faces).toContain('"BeePub VPunct Serif"');
  expect(state.faces).toContain('"BeePub VPunct Sans"');
  expect(state.faces).toContain("U+FF3B");
  expect(state.faces).not.toContain("U+2014");
  expect(state.faces).not.toContain("U+FF0D");

  // `p { font-family: serif }` bypasses the body stack → pinned inline with
  // the book's own stack preserved behind the face. Same for class-declared
  // fonts. Elements that merely inherit must stay unpinned, or they would
  // freeze the stack across reader font-setting changes.
  expect(state.pPin).toMatch(/^"BeePub VPunct (Serif|Sans)", serif$/);
  expect(state.kaiPin).toContain("BeePub VPunct");
  expect(state.kaiPin).toContain("標楷體");
  expect(state.emPin).toBe("");

  // The face actually loads from the app origin and covers the bracket.
  const bracketLoaded = await page
    .locator("iframe")
    .first()
    .evaluate(async (el) => {
      const doc = (el as HTMLIFrameElement).contentDocument!;
      await doc.fonts.ready;
      return doc.fonts.check('16px "BeePub VPunct Serif"', "［");
    });
  expect(bracketLoaded).toBe(true);
  const woff = await page.request.get("/fonts/beepub-vpunct-serif.woff2");
  expect(woff.ok()).toBeTruthy();
});

// Paging backward across a chapter boundary lands on the previous chapter's
// last page — and must STAY there when the chapter reflows late. Chapters
// over-measure on first layout and settle smaller a beat later; when that
// shrink arrives after the show debounce, the browser has already clamped
// scrollTop to the new extent, and counter() used to subtract the height
// delta a second time, landing pages before the chapter end (2026-07-31 iOS
// app report: EP04 → EP03 landed ~a dozen pages short; web only escaped by
// settling inside the debounce). CI replays the mechanism: cross the
// boundary, then push a shrink through the production resize chain.
test("backward chapter jump survives a late content shrink", async ({
  page,
}) => {
  const libraries = await (await page.request.get("/api/libraries")).json();
  const uploaded = await page.request.post("/api/books", {
    multipart: {
      file: {
        name: "vertical-chapters.epub",
        mimeType: "application/epub+zip",
        buffer: fs.readFileSync(CHAPTERS_FIXTURE),
      },
      library_id: libraries[0].id,
    },
  });
  expect(uploaded.ok()).toBeTruthy();
  const book = await uploaded.json();

  await page.addInitScript(() =>
    localStorage.setItem("reader-gestures-seen", "1"),
  );
  await page.goto(`/books/${book.id}/read`);
  const frame = page.frameLocator("iframe").first();
  await expect(frame.getByText("甲章首段").first()).toBeVisible({
    timeout: 30_000,
  });
  await page.waitForTimeout(1000);

  // Jump to chapter 2, then page back across the boundary (ArrowRight is
  // "previous page" in an rtl book).
  await page.evaluate(async () => {
    const handle = (
      window as unknown as {
        __beepubReader: { rendition: { display: (href: string) => Promise<void> } };
      }
    ).__beepubReader;
    await handle.rendition.display("chapter2.xhtml");
  });
  await expect(frame.getByText("乙章開場").first()).toBeVisible();
  await page.waitForTimeout(500);
  await page.keyboard.press("ArrowRight");
  await expect(frame.getByText("甲章末段").first()).toBeVisible({
    timeout: 10_000,
  });
  // Let the backward-navigation show debounce fully settle.
  await page.waitForTimeout(600);

  type Snap = { scrollTop: number; scrollHeight: number; pageStep: number };
  const measure = () =>
    page.evaluate<Snap>(() => {
      const mgr = (
        window as unknown as {
          __beepubReader: {
            rendition: {
              manager: {
                container: HTMLElement;
                getPageStep: () => number;
              };
            };
          };
        }
      ).__beepubReader.rendition.manager;
      return {
        scrollTop: mgr.container.scrollTop,
        scrollHeight: mgr.container.scrollHeight,
        pageStep: mgr.getPageStep(),
      };
    });

  const before = await measure();
  // The environment must actually paginate (CJK-capable fonts).
  test.skip(
    before.scrollHeight < before.pageStep * 4,
    "vertical fragmentation unavailable (no CJK fonts)",
  );
  // Landed on the last page of chapter 1.
  expect(
    Math.abs(before.scrollTop - (before.scrollHeight - before.pageStep)),
  ).toBeLessThanOrEqual(2);
  expect(before.scrollTop).toBeGreaterThan(0);

  // Post-settle shrink, detected the way production detects reflows
  // (resizeCheck → RESIZE → expand → reframe → counter).
  const after = await page.evaluate<Snap>(() => {
    const mgr = (
      window as unknown as {
        __beepubReader: {
          rendition: {
            manager: {
              container: HTMLElement;
              getPageStep: () => number;
              getContents: () => {
                document: Document;
                resizeCheck: () => void;
              }[];
            };
          };
        };
      }
    ).__beepubReader.rendition.manager;
    const contents = mgr.getContents()[0];
    const style = contents.document.createElement("style");
    style.textContent = "p:nth-of-type(n+31){display:none}";
    contents.document.head.appendChild(style);
    contents.resizeCheck();
    return {
      scrollTop: mgr.container.scrollTop,
      scrollHeight: mgr.container.scrollHeight,
      pageStep: mgr.getPageStep(),
    };
  });
  // The content actually shrank, but still spans several pages — if it
  // collapsed to one page, "last page" degenerates to 0 and the final
  // assertion could not tell a correct landing from the double-subtract.
  expect(after.scrollHeight).toBeLessThan(before.scrollHeight);
  expect(after.scrollHeight).toBeGreaterThanOrEqual(after.pageStep * 3);
  // …and the view is still on the (new) last page, not pages before it.
  expect(after.scrollTop).toBeGreaterThan(0);
  expect(
    Math.abs(after.scrollTop - (after.scrollHeight - after.pageStep)),
  ).toBeLessThanOrEqual(2);
});
