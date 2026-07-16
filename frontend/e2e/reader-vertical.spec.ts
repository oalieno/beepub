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
