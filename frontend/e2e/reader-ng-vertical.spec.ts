import { test, expect, type Page } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";
import {
  VERTICAL_BOOK,
  VPUNCT_BOOK,
  marks,
  resetProgress,
  seedFixture,
} from "./ng-helpers";

/**
 * reader-ng: vertical-rl (直排) on the new engine — the two engine-agnostic
 * checks from reader-vertical.spec.ts. The paging-grid cases there are
 * about the old fork's pageStep; read-ng's geometry is covered by
 * reader-ng.spec.ts.
 */

test.use({ storageState: ADMIN_STATE });

declare global {
  interface Window {
    __beepubReaderNG?: any;
  }
}

async function openNg(page: Page, bookId: string, text: string, font: string) {
  await resetProgress(page.request, bookId);
  await page.goto(`/books/${bookId}/read-ng?font=${font}&panel=0`);
  await page.waitForFunction(
    () => !!window.__beepubReaderNG?.core?.lastLocation,
    null,
    { timeout: 30_000 },
  );
  await expect
    .poll(() =>
      page.evaluate(
        (t) =>
          (
            window.__beepubReaderNG.core.getContents()[0].doc as Document
          ).body?.textContent?.includes(t) ?? false,
        text,
      ),
    )
    .toBe(true);
}

test("vertical book renders vertical-rl in read-ng", async ({ page }) => {
  const bookId = await seedFixture(page.request, VERTICAL_BOOK);
  await openNg(page, bookId, "話說天下大勢", "sans");
  const state = await page.evaluate(() => {
    const core = window.__beepubReaderNG.core;
    const doc: Document = core.getContents()[0].doc;
    return {
      vertical: core.vertical as boolean,
      bodyWritingMode: getComputedStyle(doc.body).writingMode,
      // Vertical pagination stacks pages along the block axis: the iframe
      // keeps the container's width and grows in whole container heights.
      axis: (() => {
        const frame = doc.defaultView!.frameElement as HTMLElement;
        const f = frame.getBoundingClientRect();
        const c = frame.parentElement!.parentElement!.getBoundingClientRect();
        return {
          widthMatches: Math.abs(f.width - c.width) < 1,
          pages: f.height / c.height,
        };
      })(),
    };
  });
  expect(state.vertical).toBe(true);
  expect(state.bodyWritingMode).toBe("vertical-rl");
  expect(state.axis.widthMatches).toBe(true);
  expect(
    Math.abs(state.axis.pages - Math.round(state.axis.pages)),
  ).toBeLessThan(0.01);
});

test("vertical punctuation faces reach a book that bypasses the body font stack", async ({
  page,
}) => {
  const bookId = await seedFixture(page.request, VPUNCT_BOOK);
  await openNg(page, bookId, "免費服務已終止", "serif");

  const state = await page.evaluate(() => {
    const core = window.__beepubReaderNG.core;
    const doc: Document = core.getContents()[0].doc;
    const p = [...doc.querySelectorAll("p")].find((n) =>
      n.textContent?.includes("免費服務已終止"),
    ) as HTMLElement | undefined;
    const kai = doc.querySelector("span.kai") as HTMLElement | null;
    const em = doc.querySelector("em") as HTMLElement | null;
    return {
      vertical: core.vertical as boolean,
      faces: [...doc.querySelectorAll("style")]
        .map((s) => s.textContent)
        .join("\n"),
      pPin: p?.style.fontFamily ?? "",
      kaiPin: kai?.style.fontFamily ?? "",
      emPin: em?.style.fontFamily ?? "",
    };
  });

  // The -webkit-prefixed-only writing-mode still routes the vertical path.
  expect(state.vertical).toBe(true);

  // Both faces arrive in the section, and the range stays curated: it must
  // claim the bracket but not — or － (no vert forms in the subset source).
  expect(state.faces).toContain('"BeePub VPunct Serif"');
  expect(state.faces).toContain('"BeePub VPunct Sans"');
  expect(state.faces).toContain("U+FF3B");
  expect(state.faces).not.toContain("U+2014");
  expect(state.faces).not.toContain("U+FF0D");

  // `p { font-family: serif }` bypasses the body stack → pinned inline with
  // the book's own stack preserved behind the face. Same for class-declared
  // fonts. Elements that merely inherit must stay unpinned.
  expect(state.pPin).toMatch(/^"BeePub VPunct (Serif|Sans)", serif$/);
  expect(state.kaiPin).toContain("BeePub VPunct");
  expect(state.kaiPin).toContain("標楷體");
  expect(state.emPin).toBe("");

  const bracketLoaded = await page.evaluate(async () => {
    const doc: Document = window.__beepubReaderNG.core.getContents()[0].doc;
    await doc.fonts.ready;
    return doc.fonts.check('16px "BeePub VPunct Serif"', "［");
  });
  expect(bracketLoaded).toBe(true);
  const woff = await page.request.get("/fonts/beepub-vpunct-serif.woff2");
  expect(woff.ok()).toBeTruthy();
});

test("highlights follow the vertical line: fill along the run, underline on its right", async ({
  page,
}) => {
  const bookId = await seedFixture(page.request, VERTICAL_BOOK);
  for (const h of await (
    await page.request.get(`/api/books/${bookId}/highlights`)
  ).json()) {
    await page.request.delete(`/api/books/${bookId}/highlights/${h.id}`);
  }
  await openNg(page, bookId, "話說天下大勢", "serif");

  // Anchor two runs of the first sentence through the engine's own CFI
  // writer, the way a selection would.
  const runs = await page.evaluate(() => {
    const core = window.__beepubReaderNG.core;
    const doc: Document = core.getContents()[0].doc;
    const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT);
    let node: Node | null = null;
    while (walker.nextNode()) {
      if ((walker.currentNode.textContent ?? "").length >= 12) {
        node = walker.currentNode;
        break;
      }
    }
    if (!node) return null;
    const run = (from: number, to: number) => {
      const range = doc.createRange();
      range.setStart(node!, from);
      range.setEnd(node!, to);
      const r = range.getBoundingClientRect();
      return {
        cfi: core.cfiOf(core.currentIndex(), range) as string,
        text: range.toString(),
        rect: { x: r.left, y: r.top, w: r.width, h: r.height },
      };
    };
    return { fill: run(2, 6), line: run(8, 12) };
  });
  expect(runs).toBeTruthy();
  // A four-character vertical run is taller than it is wide.
  expect(runs!.fill.rect.h).toBeGreaterThan(runs!.fill.rect.w * 2);

  for (const [run, color] of [
    [runs!.fill, "yellow"],
    [runs!.line, "blue:underline"],
  ] as const) {
    const created = await page.request.post(`/api/books/${bookId}/highlights`, {
      data: { cfi_range: run.cfi, text: run.text, color },
    });
    expect(created.ok()).toBeTruthy();
  }

  await openNg(page, bookId, "話說天下大勢", "serif");
  await expect.poll(() => marks(page)).toHaveLength(2);
  const drawn = await marks(page);

  const fill = drawn.find((m) => m.fill === "#fef08a")!;
  expect(fill).toBeTruthy();
  const fr = fill.rects[0];
  const want = runs!.fill.rect;
  expect(Math.abs(fr.y - want.y)).toBeLessThan(1.5);
  expect(Math.abs(fr.h - want.h)).toBeLessThan(1.5);
  expect(fr.h).toBeGreaterThan(fr.w * 2);

  // Underline in vertical writing: a 2px bar down the right side of the run.
  const line = drawn.find((m) => m.fill === "#3b82f6")!;
  expect(line).toBeTruthy();
  const lr = line.rects[0];
  const lw = runs!.line.rect;
  expect(lr.w).toBe(2);
  expect(Math.abs(lr.x + lr.w - (lw.x + lw.w))).toBeLessThan(1.5);
  expect(Math.abs(lr.y - lw.y)).toBeLessThan(1.5);
  expect(Math.abs(lr.h - lw.h)).toBeLessThan(1.5);
});
