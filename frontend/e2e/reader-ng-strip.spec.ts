import { test, expect, type Page } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";
import {
  LONG_CHAPTERS_BOOK,
  NINE_CHAPTERS_BOOK,
  connection,
  openBook,
  resetProgress,
  seedFixture,
  type Fixture,
} from "./ng-helpers";

/**
 * The scroll mode (?turn=scroll): the book is one strip of chapters on a
 * canvas, laid out from the chapter being read.
 *
 * The layout's rule: a chapter joining or leaving the strip never moves
 * the text on screen, and the scroll position is not written for it.
 *
 * The strip is a renderer behind the reader's core, so everything that
 * follows the reader's place — the chapter named, the percentage, the
 * position saved and restored, a jump from the table of contents — is
 * the paged reader's own, told where the reading line is.
 */

test.use({ storageState: ADMIN_STATE });
test.setTimeout(120_000);

async function openStrip(
  page: Page,
  bookId: string,
  index: number,
  fixture: Fixture = NINE_CHAPTERS_BOOK,
) {
  await openBook(page, bookId, { turn: "scroll" }, fixture);
  await page.evaluate(
    (i) => window.__beepubReaderNG.core.goTo(i) as Promise<unknown>,
    index,
  );
  await expect.poll(async () => (await state(page)).pinned).toBe(index);
}

const state = (page: Page) =>
  page.evaluate(() => {
    const s = window.__beepubReaderNG.core.strip;
    const frame = s.scroller.querySelector(
      `[data-index="${s.pinnedIndex}"]`,
    ) as HTMLElement;
    const box = s.scroller.getBoundingClientRect();
    const at = frame.getBoundingClientRect();
    const chapters = s.chapters as {
      index: number;
      top: number;
      height: number;
    }[];
    return {
      vertical: s.vertical as boolean,
      scrollTop: s.position as number,
      pinned: s.pinnedIndex as number,
      // How far the read chapter's start is from the screen's leading edge.
      screenTop: Math.round(
        s.vertical ? box.right - at.right : at.top - box.top,
      ),
      indices: chapters.map((c) => c.index),
      tops: chapters.map((c) => c.top),
      heights: chapters.map((c) => c.height),
      canvas: (s.vertical
        ? s.scroller.scrollWidth
        : s.scroller.scrollHeight) as number,
      log: (s.log as { what: string; index?: number }[]).map(
        (l) => `${l.what}${l.index ?? ""}`,
      ),
    };
  });

/** Where the core says the reader is, and the first words there. */
const place = (page: Page) =>
  page.evaluate(() => {
    const l = window.__beepubReaderNG.core.lastLocation;
    return {
      index: l.index as number,
      fraction: l.fraction as number,
      reason: l.reason as string,
      cfi: l.startCfi as string,
      text: ((l.range as Range | null)?.toString() ?? "")
        .trim()
        .replace(/\s+/g, " ")
        .slice(0, 24),
    };
  });

const percent = async (page: Page) =>
  parseInt(
    (await page
      .locator('[data-testid="reader-percent"]:visible')
      .textContent()) ?? "",
    10,
  );

const chapterLabel = async (page: Page) =>
  (
    (await page
      .locator('[data-testid="reader-chapter"]:visible')
      .textContent()) ?? ""
  ).trim();

/** The table of contents' label for each section it names. */
const tocLabels = (page: Page) =>
  page.evaluate(() => {
    const { book } = window.__beepubReaderNG.core;
    const out: Record<number, string> = {};
    for (const item of book.toc as { label: string; href: string }[]) {
      const index = book.resolveHref(item.href)?.index;
      if (index != null && !(index in out)) out[index] = item.label.trim();
    }
    return out;
  });

/** The wheel over the middle of the strip. */
async function overStrip(page: Page) {
  const box = (await page.getByTestId("scroll-strip").boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  return box;
}

/** Scroll by the wheel and wait for the strip to say where it rests. */
async function wheel(page: Page, notches: number, delta = 240) {
  const before = (await place(page)).cfi;
  for (let i = 0; i < notches; i++) {
    await page.mouse.wheel(0, delta);
    await page.waitForTimeout(40);
  }
  await expect
    .poll(async () => {
      const p = await place(page);
      return p.reason === "scroll" && p.cfi !== before;
    })
    .toBe(true);
  // (At rest: one more report could still be on its way.)
  await page.waitForTimeout(400);
}

/** Open the book again where it was left (openBook waits for the first
 *  chapter's text, which is not where these were). */
async function reopen(page: Page, bookId: string) {
  await page.goto(
    `/books/${bookId}/read?size=18&lh=1.8&mx=24&my=48&turn=scroll`,
  );
  await page.waitForFunction(
    () => !!window.__beepubReaderNG?.core?.lastLocation,
    null,
    { timeout: 30_000 },
  );
  await page.waitForTimeout(500);
}

function savedCfi(page: Page, bookId: string) {
  return page.evaluate(async (id) => {
    const res = await fetch(`/api/books/${id}/progress`);
    return res.ok ? ((await res.json()).cfi as string | null) : null;
  }, bookId);
}

test("a chapter joining above or below leaves the read text where it is", async ({
  page,
  request,
}) => {
  const bookId = await seedFixture(request, NINE_CHAPTERS_BOOK);
  await resetProgress(request, bookId);
  await openStrip(page, bookId, 4);
  const before = await state(page);
  expect(before.pinned).toBe(4);
  // A vertical book: the strip runs leftward.
  expect(before.vertical).toBe(true);
  // The chapter before joins (the one after is not needed yet: the
  // opened chapter is several screens long).
  await expect.poll(async () => (await state(page)).indices).toContain(3);
  const after = await state(page);
  expect(after.scrollTop).toBe(before.scrollTop);
  expect(after.screenTop).toBe(before.screenTop);
  // Stacked without gaps, in order.
  for (let i = 1; i < after.indices.length; i++)
    expect(after.tops[i]).toBe(after.tops[i - 1] + after.heights[i - 1]);
});

test("scrolling back reaches the book's first chapter at the canvas's top, and forward its end", async ({
  page,
  request,
}) => {
  const bookId = await seedFixture(request, NINE_CHAPTERS_BOOK);
  await resetProgress(request, bookId);
  await openStrip(page, bookId, 4);
  const box = await overStrip(page);
  // Back, a screen at a time, until the first chapter is the read one.
  for (let i = 0; i < 400 && (await state(page)).pinned !== 0; i++) {
    await page.mouse.wheel(0, -box.height * 0.8);
    await page.waitForTimeout(60);
  }
  await expect.poll(async () => (await state(page)).pinned).toBe(0);
  // At rest the canvas starts at the first chapter: the browser stops there.
  await expect.poll(async () => (await state(page)).tops[0]).toBe(0);
  for (let i = 0; i < 40; i++) await page.mouse.wheel(0, -box.height);
  await expect.poll(async () => (await state(page)).scrollTop).toBe(0);
  const start = await state(page);
  expect(start.screenTop).toBe(0);
  expect(start.log.some((l) => l.startsWith("rebased"))).toBe(true);
  // The canvas was shifted under the reader; where they are in their
  // chapter was not, and nothing was told of it.
  await expect.poll(async () => (await place(page)).fraction).toBe(0);
  expect((await place(page)).index).toBe(0);

  // Forward to the end of the book (its last chapter is shorter than a
  // wide screen, so the read chapter may still be the one before).
  let last = -1;
  let still = 0;
  for (let i = 0; i < 2000 && still < 5; i++) {
    await page.mouse.wheel(0, box.height * 0.8);
    await page.waitForTimeout(40);
    const s = await state(page);
    still = s.scrollTop === last && s.indices.includes(8) ? still + 1 : 0;
    last = s.scrollTop;
  }
  const end = await state(page);
  const n = end.indices.length - 1;
  expect(end.indices[n]).toBe(8);
  // No blank screen after the last chapter.
  expect(end.canvas).toBe(end.tops[n] + end.heights[n]);
  expect(end.log.some((l) => l.startsWith("let go"))).toBe(true);
});

test("a horizontal book's strip runs downward", async ({ page, request }) => {
  const bookId = await seedFixture(request, LONG_CHAPTERS_BOOK);
  await resetProgress(request, bookId);
  await openStrip(page, bookId, 1, LONG_CHAPTERS_BOOK);
  const before = await state(page);
  expect(before.vertical).toBe(false);
  expect(before.pinned).toBe(1);
  await expect.poll(async () => (await state(page)).indices).toContain(0);
  // The book's first chapter is on the strip now: at rest the canvas is
  // shifted to start at it. Nothing moves on screen for that either.
  await expect.poll(async () => (await state(page)).tops[0]).toBe(0);
  const after = await state(page);
  expect(after.pinned).toBe(1);
  expect(after.scrollTop).toBe(after.tops[1]);
  expect(after.screenTop).toBe(before.screenTop);
  // (Shifting the canvas is not a move of the reader's.)
  expect((await place(page)).reason).toBe("navigation");
});

test("a chapter slow to come is waited for on bare paper, and announced only after a moment", async ({
  page,
  request,
}) => {
  const bookId = await seedFixture(request, NINE_CHAPTERS_BOOK);
  await resetProgress(request, bookId);
  // Nothing is brought in behind the page, and every chapter asked for
  // from here on takes its time (the route also keeps the HTTP cache out).
  await connection(page, { saveData: true });
  let delay = 0;
  await page.route("**/api/books/*/content/**", async (route) => {
    if (delay) await new Promise((r) => setTimeout(r, delay));
    await route.continue();
  });
  await openStrip(page, bookId, 0);
  delay = 2500;
  const pending = page.getByTestId("scroll-strip-pending").first();
  await expect(pending).toBeHidden();
  // To the end of what is mounted, the bare paper after it — and again,
  // past the chapters the reader's prefetch had brought in already, to
  // one that is still on its way.
  for (let i = 0; i < 8; i++) {
    await page.evaluate(() => {
      const s = window.__beepubReaderNG.core.strip.scroller;
      s.scrollLeft = -s.scrollWidth;
    });
    try {
      await expect(pending).toBeVisible({ timeout: 1200 });
      break;
    } catch {
      // that one was in memory: it has joined, on to the next
    }
  }
  await expect(pending).toBeVisible();
  const before = await state(page);
  // It joins where it was waited for; what was on screen has not moved.
  await expect
    .poll(async () => (await state(page)).indices.at(-1), { timeout: 15_000 })
    .toBeGreaterThan(before.indices.at(-1)!);
  await expect(pending).toBeHidden();
  const after = await state(page);
  expect(after.scrollTop).toBe(before.scrollTop);
  expect(after.screenTop).toBe(before.screenTop);
});

for (const [name, fixture, index] of [
  ["vertical", NINE_CHAPTERS_BOOK, 3],
  ["horizontal", LONG_CHAPTERS_BOOK, 1],
] as const) {
  test(`the place scrolled to is saved, and the book opens on the same text again (${name})`, async ({
    page,
    request,
  }) => {
    const bookId = await seedFixture(request, fixture);
    await resetProgress(request, bookId);
    await openStrip(page, bookId, index, fixture);
    await overStrip(page);
    await wheel(page, 7);
    const read = await place(page);
    expect(read.index).toBe(index);
    expect(read.fraction).toBeGreaterThan(0);
    expect(read.text.length).toBeGreaterThan(0);
    await expect.poll(() => savedCfi(page, bookId)).toBe(read.cfi);

    // Opened again, twice: the same text, at the same place — no line
    // gained or lost on the way through the saved position.
    for (let round = 0; round < 2; round++) {
      await reopen(page, bookId);
      const back = await place(page);
      expect(back.index).toBe(index);
      expect(back.cfi).toBe(read.cfi);
      expect(back.text).toBe(read.text);
      // Its own landing is not a move: nothing more is told, and the
      // position saved stays the one that was read.
      await page.waitForTimeout(600);
      expect((await place(page)).reason).not.toBe("scroll");
      expect((await place(page)).cfi).toBe(read.cfi);
    }
  });
}

test("the chapter named and the percentage follow the reading line across a chapter boundary", async ({
  page,
  request,
}) => {
  const bookId = await seedFixture(request, NINE_CHAPTERS_BOOK);
  await resetProgress(request, bookId);
  await openStrip(page, bookId, 2);
  const labels = await tocLabels(page);
  expect(labels[2]).toBeTruthy();
  expect(labels[3]).toBeTruthy();
  expect(labels[3]).not.toBe(labels[2]);
  await expect.poll(() => chapterLabel(page)).toBe(labels[2]);
  const before = await percent(page);

  const box = await overStrip(page);
  for (let i = 0; i < 400 && (await state(page)).pinned !== 3; i++) {
    await page.mouse.wheel(0, box.height * 0.5);
    await page.waitForTimeout(40);
  }
  expect((await state(page)).pinned).toBe(3);
  await expect.poll(() => chapterLabel(page)).toBe(labels[3]);
  await expect.poll(async () => (await place(page)).index).toBe(3);
  const after = await percent(page);
  expect(after).toBeGreaterThan(before);
  expect(after).toBeLessThan(100);

  // And back again.
  for (let i = 0; i < 400 && (await state(page)).pinned !== 2; i++) {
    await page.mouse.wheel(0, -box.height * 0.5);
    await page.waitForTimeout(40);
  }
  await expect.poll(() => chapterLabel(page)).toBe(labels[2]);
});

test("a jump from the table of contents scrolls to a chapter that is mounted and rebuilds the strip around one that is not", async ({
  page,
  request,
}) => {
  const bookId = await seedFixture(request, NINE_CHAPTERS_BOOK);
  await resetProgress(request, bookId);
  await openStrip(page, bookId, 0);
  const labels = await tocLabels(page);
  const dialog = page.getByRole("dialog", { name: "Table of Contents" });
  const jump = async (index: number) => {
    if (!(await dialog.isVisible()))
      await page.getByRole("button", { name: "Table of Contents" }).click();
    await expect(dialog).toBeVisible();
    await dialog
      .getByRole("button", { name: labels[index], exact: true })
      .click();
    await expect.poll(async () => (await place(page)).index).toBe(index);
  };
  const marked = () =>
    page.evaluate(
      () =>
        !!window.__beepubReaderNG.core.strip.scroller.querySelector(
          "[data-kept]",
        ),
    );

  // The second chapter comes onto the strip behind the first; the first
  // one's frame is marked to tell a strip kept from a strip built anew.
  const box = await overStrip(page);
  for (let i = 0; i < 40 && !(await state(page)).indices.includes(1); i++) {
    await page.mouse.wheel(0, box.height * 0.5);
    await page.waitForTimeout(60);
  }
  await expect.poll(async () => (await state(page)).indices).toContain(1);
  expect((await state(page)).pinned).toBe(0);
  await page.evaluate(() =>
    window.__beepubReaderNG.core.strip.scroller
      .querySelector('[data-index="0"]')
      .setAttribute("data-kept", ""),
  );
  await jump(1);
  let at = await place(page);
  expect(at.fraction).toBe(0);
  expect(at.reason).toBe("navigation");
  expect((await state(page)).pinned).toBe(1);
  expect((await state(page)).screenTop).toBe(0);
  expect(await marked()).toBe(true);
  await expect.poll(() => chapterLabel(page)).toBe(labels[1]);

  // Far ahead: nothing of it is mounted.
  expect((await state(page)).indices).not.toContain(7);
  await jump(7);
  at = await place(page);
  expect(at.fraction).toBe(0);
  expect((await state(page)).pinned).toBe(7);
  expect((await state(page)).screenTop).toBe(0);
  expect(await marked()).toBe(false);
  await expect.poll(() => chapterLabel(page)).toBe(labels[7]);
});

test("the book is finished at the end of its last chapter, not on entering it", async ({
  page,
  request,
}) => {
  const bookId = await seedFixture(request, LONG_CHAPTERS_BOOK);
  await resetProgress(request, bookId);
  await openStrip(page, bookId, 0, LONG_CHAPTERS_BOOK);
  const last = await page.evaluate(() =>
    window.__beepubReaderNG.core.lastLinearIndex(),
  );
  await page.evaluate(
    (i) => window.__beepubReaderNG.core.goTo(i) as Promise<unknown>,
    last,
  );
  await expect.poll(async () => (await place(page)).index).toBe(last);
  await page.waitForTimeout(400);
  expect(await percent(page)).toBeLessThan(100);

  // To the very end.
  await overStrip(page);
  await page.evaluate(() => {
    const s = window.__beepubReaderNG.core.strip.scroller;
    s.scrollTop = s.scrollHeight;
  });
  await expect.poll(() => percent(page)).toBe(100);
  // And away from it again.
  await page.evaluate(() => {
    const s = window.__beepubReaderNG.core.strip.scroller;
    s.scrollTop -= 2000;
  });
  await expect.poll(() => percent(page)).toBeLessThan(100);
});

test("switching between pages and the strip keeps the reader's place", async ({
  page,
  request,
}) => {
  const bookId = await seedFixture(request, LONG_CHAPTERS_BOOK);
  await resetProgress(request, bookId);
  await openBook(page, bookId, { turn: "fade" }, LONG_CHAPTERS_BOOK);
  await page.evaluate(
    () =>
      window.__beepubReaderNG.core.goTo({
        index: 1,
        fraction: 0.4,
      }) as Promise<unknown>,
  );
  await expect.poll(async () => (await place(page)).index).toBe(1);
  const paged = await place(page);
  expect(paged.text.length).toBeGreaterThan(0);

  // Pages → strip: the text the page began with is at the reading line.
  await page.evaluate(() => window.__beepubReaderNG.core.setPageTurn("scroll"));
  await expect
    .poll(() => page.evaluate(() => !!window.__beepubReaderNG.core.strip))
    .toBe(true);
  await expect
    .poll(async () => (await place(page)).reason, { timeout: 15_000 })
    .toBe("anchor");
  const strip = await place(page);
  expect(strip.index).toBe(1);
  await expect(page.getByTestId("scroll-strip")).toBeVisible();
  // (The strip breaks its lines elsewhere than the page did: the text is
  // in the line at the screen's leading edge, not always its first word.)
  const held = await page.evaluate((cfi) => {
    const { core } = window.__beepubReaderNG;
    const s = core.strip;
    const doc = core.getContents()[0].doc as Document;
    const anchor = core.resolve(cfi)?.anchor?.(doc) as Range;
    const probe = doc.createRange();
    probe.setStart(anchor.startContainer, anchor.startOffset);
    probe.setEnd(anchor.startContainer, anchor.startOffset + 1);
    const rect = probe.getBoundingClientRect();
    const frame = (
      doc.defaultView!.frameElement as HTMLElement
    ).getBoundingClientRect();
    const box = (s.scroller as HTMLElement).getBoundingClientRect();
    return {
      inRange: (core.lastLocation.range as Range).isPointInRange(
        anchor.startContainer,
        anchor.startOffset,
      ),
      // The word's line, from the top of the screen.
      fromTop: Math.round(frame.top + rect.top - box.top),
    };
  }, paged.cfi);
  expect(held.inRange).toBe(true);
  expect(held.fromTop).toBeGreaterThanOrEqual(0);
  expect(held.fromTop).toBeLessThan(40);

  // Read on, then strip → pages: the page shown holds the text the
  // reading line was on.
  await overStrip(page);
  await wheel(page, 6);
  const read = await place(page);
  expect(read.cfi).not.toBe(strip.cfi);
  await page.evaluate(() => window.__beepubReaderNG.core.setPageTurn("fade"));
  await expect
    .poll(() => page.evaluate(() => !window.__beepubReaderNG.core.strip))
    .toBe(true);
  await expect(page.getByTestId("scroll-strip")).toHaveCount(0);
  await expect
    .poll(
      () =>
        page.evaluate((cfi) => {
          const { core, paginator } = window.__beepubReaderNG;
          const l = core.lastLocation;
          const content = paginator.getContents()[0];
          if (!l?.range || content?.index !== 1 || l.size == null) return false;
          const anchor = core.resolve(cfi)?.anchor?.(content.doc) as Range;
          return (l.range as Range).isPointInRange(
            anchor.startContainer,
            anchor.startOffset,
          );
        }, read.cfi),
      { timeout: 15_000 },
    )
    .toBe(true);
});
