import {
  test,
  expect,
  type APIRequestContext,
  type Page,
} from "@playwright/test";
import { ADMIN_STATE } from "./helpers";
import {
  CBZ_BOOK,
  TOUCH_BOOK,
  VERTICAL_MIXED_UNDECLARED_BOOK,
  iphone,
  location,
  marks,
  openBook,
  openComic,
  resetProgress,
  seedFixture,
  swipe,
  touchTap,
  type Fixture,
} from "./ng-helpers";

/**
 * reader-ng: the per-book writing direction (Auto / Horizontal /
 * Vertical). A forced mode has to reach the body (the paginator lays the
 * section out by it), pull inner containers along, turn pages the way the
 * forced layout reads, keep the place and the highlights across a switch,
 * and be remembered for that one book.
 */

test.use({ storageState: ADMIN_STATE });

/** A horizontal zh-TW novel that declares no direction; its first
 *  chapter carries a ruby and a tate-chu-yoko run. */
const HORIZONTAL_BOOK: Fixture = {
  file: "e2e-writing-mode-horizontal-book.epub",
  title: "潮間帶抄書人手記",
  readyText: "潮冊甲章第001段",
};

/** vertical-rl on the root, page progression rtl. */
const VERTICAL_BOOK: Fixture = {
  file: "e2e-writing-mode-vertical-book.epub",
  title: "霜降渡船頭紀事",
  readyText: "霜冊卷上第001段",
};

/** vertical-rl on `div.main` only; the body declares nothing. */
const INNER_BOOK: Fixture = {
  file: "e2e-writing-mode-inner-book.epub",
  title: "紙傘巷鐘錶匠雜錄",
  readyText: "傘冊上篇第001段",
};

const KEY = "reader-writing-mode";

type Mode = "Auto" | "Horizontal" | "Vertical";

function row(page: Page) {
  return page.getByTestId("setting-writing-mode");
}

function openSheet(page: Page) {
  return page.getByRole("button", { name: "Reader settings" }).click();
}

async function closeSheet(page: Page) {
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
}

function engine(page: Page) {
  return page.evaluate(() => {
    const core = window.__beepubReaderNG.core;
    const doc: Document = core.getContents()[0].doc;
    return {
      forced: core.forcedWritingMode() as string | null,
      vertical: core.vertical as boolean,
      leftward: core.advancesLeftward() as boolean,
      body: getComputedStyle(doc.body).writingMode,
      root: getComputedStyle(doc.documentElement).writingMode,
    };
  });
}

/** Pick a writing direction in the sheet and wait for the section to be
 *  laid out that way. */
async function pick(page: Page, mode: Mode, body: string) {
  await openSheet(page);
  await row(page).getByRole("button", { name: mode, exact: true }).click();
  await expect(
    row(page).getByRole("button", { name: mode, exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await closeSheet(page);
  // (Mid-switch the new section document has no body yet.)
  await expect
    .poll(() =>
      page.evaluate(() => {
        const doc: Document | undefined =
          window.__beepubReaderNG.core.getContents()[0]?.doc;
        return doc?.body ? getComputedStyle(doc.body).writingMode : null;
      }),
    )
    .toBe(body);
  // The landing relocation follows the load.
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          window.__beepubReaderNG.core.lastLocation.range?.startContainer
            .ownerDocument ===
          window.__beepubReaderNG.core.getContents()[0].doc,
      ),
    )
    .toBe(true);
  await page.waitForTimeout(300);
}

function startCfi(page: Page): Promise<string> {
  return page.evaluate(
    () => window.__beepubReaderNG.core.lastLocation.startCfi,
  );
}

/** Whether the place a CFI names is on the page now on screen. */
function onScreen(page: Page, cfi: string) {
  return page.evaluate((cfi) => {
    const core = window.__beepubReaderNG.core;
    const doc: Document = core.getContents()[0].doc;
    const target = core.resolve(cfi);
    const point = target?.anchor?.(doc) as Range | null;
    const visible: Range | null = core.lastLocation.range;
    if (!point || !visible) return false;
    return visible.comparePoint(point.startContainer, point.startOffset) === 0;
  }, cfi);
}

/** Page forward `times` with a key, expecting each press to move. */
async function pageForward(page: Page, key: string, times: number) {
  for (let i = 0; i < times; i++) {
    const before = await location(page);
    await page.keyboard.press(key);
    await expect
      .poll(async () => {
        const l = await location(page);
        return l.index > before.index || l.fraction > before.fraction;
      })
      .toBe(true);
    // The paginator drops navigation for ~100ms after a page turn.
    await page.waitForTimeout(200);
  }
}

/** Every paragraph's box against the section frame, on the axis the
 *  pages do not run along: a block left in the other writing mode
 *  overflows it (the half-cut page). */
function paragraphsFit(page: Page) {
  return page.evaluate(() => {
    const core = window.__beepubReaderNG.core;
    const doc: Document = core.getContents()[0].doc;
    const frame = (
      doc.defaultView!.frameElement as HTMLElement
    ).getBoundingClientRect();
    const vertical: boolean = core.vertical;
    const rects = [...doc.querySelectorAll("p")].map((p) =>
      p.getBoundingClientRect(),
    );
    return {
      count: rects.length,
      fit: rects.every((r) =>
        vertical
          ? r.left >= -1 && r.right <= frame.width + 1
          : r.top >= -1 && r.bottom <= frame.height + 1,
      ),
      // A paragraph of a few lines is longer along its lines than across.
      alongLines: rects.filter((r) =>
        vertical ? r.height > r.width : r.width > r.height,
      ).length,
    };
  });
}

/** A point in the left or right tap zone, over the page (on a wide
 *  screen a horizontal page is a 720px column: it does not reach the
 *  reader's edges, and only the section document takes clicks). */
async function tapZonePoint(page: Page, side: "left" | "right") {
  const box = (await page.getByTestId("book-reader").boundingBox())!;
  const column = await page.evaluate(() => {
    const doc: Document = window.__beepubReaderNG.core.getContents()[0].doc;
    // The frame is the whole strip of pages; the box it scrolls in is
    // the page on screen.
    const frame = doc.defaultView!.frameElement as HTMLElement;
    const r = frame.parentElement!.parentElement!.getBoundingClientRect();
    return { left: r.left, right: r.right };
  });
  const left = Math.max(box.x, column.left) + 10;
  const right = Math.min(box.x + box.width, column.right) - 10;
  expect(left).toBeLessThan(box.x + box.width * 0.25);
  expect(right).toBeGreaterThan(box.x + box.width * 0.75);
  return { x: side === "left" ? left : right, y: box.y + box.height / 2 };
}

/** Whether the end of the section's last paragraph is on screen. */
function atChapterEnd(page: Page) {
  return page.evaluate(() => {
    const core = window.__beepubReaderNG.core;
    const doc: Document = core.getContents()[0].doc;
    const last = [...doc.querySelectorAll("p")].pop()!;
    const visible: Range | null = core.lastLocation.range;
    const text = last.lastChild!;
    return (
      !!visible && visible.comparePoint(text, text.textContent!.length) === 0
    );
  });
}

function scrubber(page: Page) {
  return page.getByTestId("ng-progress").locator("input[type=range]");
}

interface Row {
  id: string;
  cfi_range: string;
}

async function clearHighlights(request: APIRequestContext, bookId: string) {
  const rows: Row[] = await (
    await request.get(`/api/books/${bookId}/highlights`)
  ).json();
  for (const h of rows) {
    const res = await request.delete(`/api/books/${bookId}/highlights/${h.id}`);
    expect(res.ok()).toBeTruthy();
  }
}

/** Iframe-local rect of a phrase in the section on screen. */
function phraseRect(page: Page, phrase: string) {
  return page.evaluate((phrase) => {
    const doc: Document = window.__beepubReaderNG.core.getContents()[0].doc;
    const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const node = walker.currentNode;
      const idx = (node.textContent ?? "").indexOf(phrase);
      if (idx < 0) continue;
      const range = doc.createRange();
      range.setStart(node, idx);
      range.setEnd(node, idx + phrase.length);
      const r = range.getBoundingClientRect();
      return { x: r.left, y: r.top, w: r.width, h: r.height };
    }
    return null;
  }, phrase);
}

test.describe("writing direction", () => {
  test.afterEach(async ({ page }) => {
    for (const fixture of [HORIZONTAL_BOOK, VERTICAL_BOOK, INNER_BOOK]) {
      const id = await seedFixture(page.request, fixture);
      await resetProgress(page.request, id);
    }
  });

  test("a horizontal book forced vertical lays out vertically, turns leftward and keeps its place", async ({
    page,
  }) => {
    const bookId = await seedFixture(page.request, HORIZONTAL_BOOK);
    await openBook(page, bookId, { font: "sans" }, HORIZONTAL_BOOK);

    // Untouched, the book is what it always was.
    expect(await engine(page)).toEqual({
      forced: null,
      vertical: false,
      leftward: false,
      body: "horizontal-tb",
      root: "horizontal-tb",
    });
    await expect(scrubber(page)).toHaveAttribute("dir", "ltr");

    await pageForward(page, "ArrowRight", 3);
    const place = await startCfi(page);
    const before = await location(page);
    expect(before.fraction).toBeGreaterThan(0);

    await pick(page, "Vertical", "vertical-rl");
    expect(await engine(page)).toEqual({
      forced: "vertical",
      vertical: true,
      leftward: true,
      body: "vertical-rl",
      root: "vertical-rl",
    });
    // The paginator took the vertical axis: the frame keeps the
    // container's width and grows in whole container heights.
    const axis = await page.evaluate(() => {
      const doc: Document = window.__beepubReaderNG.core.getContents()[0].doc;
      const frame = doc.defaultView!.frameElement as HTMLElement;
      const f = frame.getBoundingClientRect();
      const c = frame.parentElement!.parentElement!.getBoundingClientRect();
      return {
        widthMatches: Math.abs(f.width - c.width) < 1,
        pages: f.height / c.height,
      };
    });
    expect(axis.widthMatches).toBe(true);
    expect(axis.pages).toBeGreaterThan(2);
    expect(Math.abs(axis.pages - Math.round(axis.pages))).toBeLessThan(0.01);

    // Same place, same section.
    expect((await location(page)).index).toBe(before.index);
    expect(await onScreen(page, place)).toBe(true);
    await expect(scrubber(page)).toHaveAttribute("dir", "rtl");

    // Ruby and the tate-chu-yoko run are left to the book.
    const inline = await page.evaluate(() => {
      const doc: Document = window.__beepubReaderNG.core.getContents()[0].doc;
      const rt = doc.querySelector("rt")!;
      const tcy = doc.querySelector(".tcy")!;
      return {
        rt: getComputedStyle(rt).display,
        rtMode: getComputedStyle(rt).writingMode,
        tcy: getComputedStyle(tcy).textCombineUpright,
      };
    });
    expect(inline).toEqual({
      rt: "ruby-text",
      rtMode: "vertical-rl",
      tcy: "all",
    });
    // The vertical punctuation faces lead the stack, as in a book set
    // vertically to begin with.
    expect(
      await page.evaluate(() => {
        const doc: Document = window.__beepubReaderNG.core.getContents()[0].doc;
        return getComputedStyle(doc.body).fontFamily;
      }),
    ).toContain("BeePub VPunct Sans");

    // Leftward now: the left arrow and the left tap zone go forward, the
    // right ones back.
    const l0 = await location(page);
    await pageForward(page, "ArrowLeft", 1);
    const l1 = await location(page);
    const leftZone = await tapZonePoint(page, "left");
    const rightZone = await tapZonePoint(page, "right");
    await page.mouse.click(leftZone.x, leftZone.y);
    await expect
      .poll(async () => (await location(page)).fraction)
      .toBeGreaterThan(l1.fraction);
    await page.waitForTimeout(200);
    await page.mouse.click(rightZone.x, rightZone.y);
    await expect
      .poll(async () => (await location(page)).fraction)
      .toBeCloseTo(l1.fraction, 5);
    await page.waitForTimeout(200);
    await page.keyboard.press("ArrowRight");
    await expect
      .poll(async () => (await location(page)).fraction)
      .toBeCloseTo(l0.fraction, 5);
    await page.waitForTimeout(200);

    // The next chapter loads in the forced mode too.
    await page.evaluate(() => window.__beepubReaderNG.core.goTo(1));
    await expect.poll(async () => (await location(page)).index).toBe(1);
    expect(await engine(page)).toMatchObject({
      vertical: true,
      leftward: true,
      body: "vertical-rl",
    });

    // Back to Auto: nothing of the forced mode stays behind.
    await pick(page, "Auto", "horizontal-tb");
    expect(await engine(page)).toEqual({
      forced: null,
      vertical: false,
      leftward: false,
      body: "horizontal-tb",
      root: "horizontal-tb",
    });
    await expect(scrubber(page)).toHaveAttribute("dir", "ltr");
  });

  test("switching back and forth returns to the same page, and the saved position stays good", async ({
    page,
  }) => {
    const bookId = await seedFixture(page.request, HORIZONTAL_BOOK);
    await openBook(page, bookId, { font: "sans" }, HORIZONTAL_BOOK);
    await pageForward(page, "ArrowRight", 4);
    const place = await startCfi(page);
    const before = await location(page);

    for (let i = 0; i < 3; i++) {
      await pick(page, "Vertical", "vertical-rl");
      expect(await onScreen(page, place)).toBe(true);
      await pick(page, "Horizontal", "horizontal-tb");
      // Not a page earlier each round: the very page it started on.
      expect(await startCfi(page)).toBe(place);
      expect((await location(page)).fraction).toBeCloseTo(before.fraction, 5);
    }

    // Whatever gets saved after the switches names text on this page.
    await pick(page, "Vertical", "vertical-rl");
    await page.waitForTimeout(2600); // the save debounce
    const saved = await (
      await page.request.get(`/api/books/${bookId}/progress`)
    ).json();
    expect(typeof saved.cfi).toBe("string");
    expect(await onScreen(page, saved.cfi)).toBe(true);
    expect(saved.percentage).toBeGreaterThan(0);
    expect(saved.percentage).toBeLessThan(60);
  });

  test("a vertical book forced horizontal lays out horizontally, turns rightward and keeps its place", async ({
    page,
  }) => {
    const bookId = await seedFixture(page.request, VERTICAL_BOOK);
    await openBook(
      page,
      bookId,
      { font: "sans", turn: "animated" },
      VERTICAL_BOOK,
    );
    expect(await engine(page)).toEqual({
      forced: null,
      vertical: true,
      leftward: true,
      body: "vertical-rl",
      root: "vertical-rl",
    });
    await expect(scrubber(page)).toHaveAttribute("dir", "rtl");
    const effective = () =>
      page.evaluate(() => window.__beepubReaderNG.core.effectivePageTurn());
    expect(await effective()).toBe("instant");

    await pageForward(page, "ArrowLeft", 3);
    const place = await startCfi(page);
    const before = await location(page);

    await pick(page, "Horizontal", "horizontal-tb");
    // The spine still says rtl; the forced layout reads left to right.
    expect(
      await page.evaluate(() => window.__beepubReaderNG.core.book.dir),
    ).toBe("rtl");
    expect(await engine(page)).toEqual({
      forced: "horizontal",
      vertical: false,
      leftward: false,
      body: "horizontal-tb",
      root: "horizontal-tb",
    });
    expect(
      await page.evaluate(() =>
        window.__beepubReaderNG.paginator.getAttribute("dir"),
      ),
    ).toBe("ltr");
    await expect(scrubber(page)).toHaveAttribute("dir", "ltr");
    // Horizontal pages slide with the finger's axis again.
    expect(await effective()).toBe("animated");

    expect((await location(page)).index).toBe(before.index);
    expect(await onScreen(page, place)).toBe(true);

    // Rightward: the right arrow and the right tap zone go forward.
    const l0 = await location(page);
    await pageForward(page, "ArrowRight", 1);
    const l1 = await location(page);
    const leftZone = await tapZonePoint(page, "left");
    const rightZone = await tapZonePoint(page, "right");
    await page.waitForTimeout(400);
    await page.mouse.click(rightZone.x, rightZone.y);
    await expect
      .poll(async () => (await location(page)).fraction)
      .toBeGreaterThan(l1.fraction);
    await page.waitForTimeout(400);
    await page.mouse.click(leftZone.x, leftZone.y);
    await expect
      .poll(async () => (await location(page)).fraction)
      .toBeCloseTo(l1.fraction, 5);
    await page.waitForTimeout(400);
    await page.keyboard.press("ArrowLeft");
    await expect
      .poll(async () => (await location(page)).fraction)
      .toBeCloseTo(l0.fraction, 5);
    await page.waitForTimeout(400);

    // Crossing into the next chapter keeps the forced direction.
    await page.evaluate(() => window.__beepubReaderNG.core.goTo(1));
    await expect.poll(async () => (await location(page)).index).toBe(1);
    expect(await engine(page)).toMatchObject({
      vertical: false,
      leftward: false,
      body: "horizontal-tb",
    });

    // Auto hands the book back as it was written.
    await pick(page, "Auto", "vertical-rl");
    expect(await engine(page)).toEqual({
      forced: null,
      vertical: true,
      leftward: true,
      body: "vertical-rl",
      root: "vertical-rl",
    });
    await expect(scrubber(page)).toHaveAttribute("dir", "rtl");
    expect(await effective()).toBe("instant");
  });

  test("a book that sets its writing mode on an inner container follows the forced mode whole", async ({
    page,
  }) => {
    const bookId = await seedFixture(page.request, INNER_BOOK);
    await openBook(page, bookId, { font: "sans" }, INNER_BOOK);
    const inner = () =>
      page.evaluate(() => {
        const doc: Document = window.__beepubReaderNG.core.getContents()[0].doc;
        return getComputedStyle(doc.querySelector("div.main")!).writingMode;
      });
    // As written: a vertical block inside a body that declares nothing.
    expect((await engine(page)).body).toBe("horizontal-tb");
    expect(await inner()).toBe("vertical-rl");

    await pick(page, "Horizontal", "horizontal-tb");
    expect(await inner()).toBe("horizontal-tb");
    expect(await engine(page)).toMatchObject({
      forced: "horizontal",
      vertical: false,
      leftward: false,
    });
    let fit = await paragraphsFit(page);
    expect(fit.count).toBe(60);
    expect(fit.fit).toBe(true);
    // (One split across two pages measures as a box spanning both.)
    expect(fit.alongLines).toBeGreaterThan(50);
    // The chapter runs through to the end of its last paragraph.
    expect(await atChapterEnd(page)).toBe(false);
    await page.evaluate(() =>
      window.__beepubReaderNG.core.goTo({ index: 0, fraction: 1 }),
    );
    await expect.poll(() => atChapterEnd(page)).toBe(true);

    await pick(page, "Vertical", "vertical-rl");
    expect(await inner()).toBe("vertical-rl");
    expect(await engine(page)).toMatchObject({
      forced: "vertical",
      vertical: true,
      leftward: true,
    });
    fit = await paragraphsFit(page);
    expect(fit.count).toBe(60);
    expect(fit.fit).toBe(true);
    // (One split across two pages measures as a box spanning both.)
    expect(fit.alongLines).toBeGreaterThan(50);
    await page.evaluate(() =>
      window.__beepubReaderNG.core.goTo({ index: 0, fraction: 1 }),
    );
    await expect.poll(() => atChapterEnd(page)).toBe(true);
  });

  test("the choice is remembered for that book only", async ({ page }) => {
    const bookId = await seedFixture(page.request, HORIZONTAL_BOOK);
    const otherId = await seedFixture(page.request, INNER_BOOK);
    await openBook(page, bookId, { font: "sans" }, HORIZONTAL_BOOK);
    await pick(page, "Vertical", "vertical-rl");
    const stored = () =>
      page.evaluate(
        ([key, a, b]) => [
          localStorage.getItem(`${key}:${a}`),
          localStorage.getItem(`${key}:${b}`),
          localStorage.getItem(key),
        ],
        [KEY, bookId, otherId],
      );
    expect(await stored()).toEqual(["vertical", null, null]);

    // Reopened: vertical from the first section on, and the sheet says so.
    await openBook(page, bookId, { font: "sans" }, HORIZONTAL_BOOK);
    expect(await engine(page)).toMatchObject({
      forced: "vertical",
      body: "vertical-rl",
      leftward: true,
    });
    await openSheet(page);
    await expect(
      row(page).getByRole("button", { name: "Vertical", exact: true }),
    ).toHaveAttribute("aria-pressed", "true");
    await closeSheet(page);

    // Another book is untouched by it.
    await openBook(page, otherId, { font: "sans" }, INNER_BOOK);
    expect(await engine(page)).toMatchObject({
      forced: null,
      body: "horizontal-tb",
    });
    await openSheet(page);
    await expect(
      row(page).getByRole("button", { name: "Auto", exact: true }),
    ).toHaveAttribute("aria-pressed", "true");
    await closeSheet(page);

    // Auto is the absence of a choice.
    await openBook(page, bookId, { font: "sans" }, HORIZONTAL_BOOK);
    await pick(page, "Auto", "horizontal-tb");
    expect(await stored()).toEqual([null, null, null]);
  });

  test("a highlight made before a switch is painted on its words after", async ({
    page,
  }) => {
    const bookId = await seedFixture(page.request, HORIZONTAL_BOOK);
    await clearHighlights(page.request, bookId);
    await openBook(page, bookId, { font: "sans" }, HORIZONTAL_BOOK);
    const phrase = "潮冊甲章第002段";
    const cfi = await page.evaluate((phrase) => {
      const core = window.__beepubReaderNG.core;
      const doc: Document = core.getContents()[0].doc;
      const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT);
      while (walker.nextNode()) {
        const node = walker.currentNode;
        const idx = (node.textContent ?? "").indexOf(phrase);
        if (idx < 0) continue;
        const range = doc.createRange();
        range.setStart(node, idx);
        range.setEnd(node, idx + phrase.length);
        return core.cfiOf(0, range) as string;
      }
      return null;
    }, phrase);
    expect(cfi).toBeTruthy();
    for (const color of ["yellow", "blue:underline"]) {
      const created = await page.request.post(
        `/api/books/${bookId}/highlights`,
        { data: { cfi_range: cfi, text: phrase, color } },
      );
      expect(created.ok()).toBeTruthy();
    }

    try {
      await openBook(page, bookId, { font: "sans" }, HORIZONTAL_BOOK);
      await expect.poll(async () => (await marks(page)).length).toBe(2);
      const check = async (vertical: boolean) => {
        const word = (await phraseRect(page, phrase))!;
        const drawn = await marks(page);
        const fill = drawn.find((d) => d.fill === "#fef08a")!;
        const line = drawn.find((d) => d.fill === "#3b82f6")!;
        // The fill covers the words where they now are.
        expect(fill.rects.length).toBeGreaterThan(0);
        const r = fill.rects[0];
        expect(Math.abs(r.x - word.x)).toBeLessThanOrEqual(2);
        expect(Math.abs(r.y - word.y)).toBeLessThanOrEqual(2);
        expect(Math.abs(r.w - word.w)).toBeLessThanOrEqual(2);
        expect(Math.abs(r.h - word.h)).toBeLessThanOrEqual(2);
        expect(r.h > r.w).toBe(vertical);
        // The underline runs along the line of text: beside a vertical
        // line, under a horizontal one.
        const u = line.rects[0];
        expect(u.h > u.w).toBe(vertical);
        if (vertical) {
          expect(Math.abs(u.x + u.w - (word.x + word.w))).toBeLessThanOrEqual(
            2,
          );
        } else {
          expect(Math.abs(u.y + u.h - (word.y + word.h))).toBeLessThanOrEqual(
            2,
          );
        }
      };
      await check(false);

      await pick(page, "Vertical", "vertical-rl");
      await expect.poll(async () => (await marks(page)).length).toBe(2);
      await check(true);

      await pick(page, "Auto", "horizontal-tb");
      await expect.poll(async () => (await marks(page)).length).toBe(2);
      await check(false);
    } finally {
      await clearHighlights(page.request, bookId);
    }
  });

  test("a book that is not CJK has no writing direction row", async ({
    page,
  }) => {
    const bookId = await seedFixture(page.request, TOUCH_BOOK);
    await openBook(page, bookId);
    await openSheet(page);
    // The sheet is up with its other rows; this one is absent.
    await expect(page.getByTestId("setting-font-size")).toBeVisible();
    await expect(row(page)).toHaveCount(0);
    await closeSheet(page);
    expect(
      await page.evaluate(() =>
        window.__beepubReaderNG.core.offersWritingMode(),
      ),
    ).toBe(false);
    await resetProgress(page.request, bookId);

    // A CJK text book has it.
    const cjk = await seedFixture(page.request, HORIZONTAL_BOOK);
    await openBook(page, cjk, { font: "sans" }, HORIZONTAL_BOOK);
    await openSheet(page);
    await expect(row(page).getByRole("button")).toHaveCount(3);
  });

  test("a comic in the image pager has no writing direction row, stored choice or not", async ({
    page,
  }) => {
    const bookId = await seedFixture(page.request, CBZ_BOOK);
    await page.addInitScript(
      ([key, id]) => localStorage.setItem(`${key}:${id}`, "vertical"),
      [KEY, bookId],
    );
    await openComic(page, bookId);
    await openSheet(page);
    await expect(page.getByTestId("setting-pager-mode")).toBeVisible();
    await expect(row(page)).toHaveCount(0);
  });

  test("a stored horizontal choice outranks the direction inferred from an undeclared vertical book", async ({
    page,
  }) => {
    const bookId = await seedFixture(
      page.request,
      VERTICAL_MIXED_UNDECLARED_BOOK,
    );
    await page.addInitScript(
      ([key, id]) => localStorage.setItem(`${key}:${id}`, "horizontal"),
      [KEY, bookId],
    );
    await openBook(
      page,
      bookId,
      { font: "sans" },
      VERTICAL_MIXED_UNDECLARED_BOOK,
    );
    expect(await engine(page)).toEqual({
      forced: "horizontal",
      vertical: false,
      leftward: false,
      body: "horizontal-tb",
      root: "horizontal-tb",
    });
    // Its text is vertical by its own sheet: the choice is still offered.
    expect(
      await page.evaluate(() =>
        window.__beepubReaderNG.core.offersWritingMode(),
      ),
    ).toBe(true);
    await resetProgress(page.request, bookId);
  });
});

test.describe("writing direction on a phone", () => {
  test.use({ ...iphone });

  test.afterEach(async ({ page }) => {
    for (const fixture of [HORIZONTAL_BOOK, VERTICAL_BOOK]) {
      const id = await seedFixture(page.request, fixture);
      await resetProgress(page.request, id);
    }
  });

  test("forced vertical: a rightward swipe and the left edge turn forward", async ({
    page,
    context,
  }) => {
    const bookId = await seedFixture(page.request, HORIZONTAL_BOOK);
    await page.addInitScript(
      ([key, id]) => localStorage.setItem(`${key}:${id}`, "vertical"),
      [KEY, bookId],
    );
    await openBook(page, bookId, { font: "sans" }, HORIZONTAL_BOOK);
    expect(await engine(page)).toMatchObject({
      forced: "vertical",
      vertical: true,
      leftward: true,
    });
    const cdp = await context.newCDPSession(page);
    const fraction = async () => (await location(page)).fraction;

    await swipe(cdp, { x: 80, y: 400 }, { x: 300, y: 400 });
    await expect.poll(fraction).toBeGreaterThan(0);
    const one = await fraction();
    await page.waitForTimeout(400);
    await touchTap(cdp, { x: 30, y: 400 }, 50);
    await expect.poll(fraction).toBeGreaterThan(one);
    await page.waitForTimeout(400);
    await touchTap(cdp, { x: 360, y: 400 }, 50);
    await expect.poll(fraction).toBeCloseTo(one, 5);
    await page.waitForTimeout(400);
    await swipe(cdp, { x: 300, y: 400 }, { x: 80, y: 400 });
    await expect.poll(fraction).toBe(0);
  });

  test("forced horizontal on a vertical book: a leftward swipe and the right edge turn forward, and the sheet offers the way back", async ({
    page,
    context,
  }) => {
    const bookId = await seedFixture(page.request, VERTICAL_BOOK);
    await page.addInitScript(
      ([key, id]) => localStorage.setItem(`${key}:${id}`, "horizontal"),
      [KEY, bookId],
    );
    await openBook(page, bookId, { font: "sans" }, VERTICAL_BOOK);
    expect(await engine(page)).toMatchObject({
      forced: "horizontal",
      vertical: false,
      leftward: false,
    });
    const cdp = await context.newCDPSession(page);
    const fraction = async () => (await location(page)).fraction;

    await swipe(cdp, { x: 300, y: 400 }, { x: 80, y: 400 });
    await expect.poll(fraction).toBeGreaterThan(0);
    const one = await fraction();
    await page.waitForTimeout(400);
    await touchTap(cdp, { x: 360, y: 400 }, 50);
    await expect.poll(fraction).toBeGreaterThan(one);
    await page.waitForTimeout(400);
    await touchTap(cdp, { x: 30, y: 400 }, 50);
    await expect.poll(fraction).toBeCloseTo(one, 5);
    await page.waitForTimeout(400);
    await swipe(cdp, { x: 80, y: 400 }, { x: 300, y: 400 });
    await expect.poll(fraction).toBe(0);

    // The phone's sheet (middle tap → bottom bar → settings) fits the
    // three choices in its row.
    await page.waitForTimeout(400);
    await touchTap(cdp, { x: 195, y: 400 }, 50);
    await page.getByRole("button", { name: "Reader settings" }).click();
    const buttons = row(page).getByRole("button");
    await expect(buttons).toHaveCount(3);
    await expect(
      row(page).getByRole("button", { name: "Horizontal", exact: true }),
    ).toHaveAttribute("aria-pressed", "true");
    const sheet = (await page.getByRole("dialog").boundingBox())!;
    for (const b of await buttons.all()) {
      const box = (await b.boundingBox())!;
      expect(box.x).toBeGreaterThanOrEqual(sheet.x);
      expect(box.x + box.width).toBeLessThanOrEqual(sheet.x + sheet.width);
    }
  });
});
