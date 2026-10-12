import {
  test,
  expect,
  type APIRequestContext,
  type Page,
} from "@playwright/test";
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
 * The scroll mode (?turn=scroll), when something under the reader
 * changes: a chapter that will not load at the end of the strip, and
 * new styles or a new screen size taken in place — every mounted chapter
 * laid out again where it stands, the line at the reading line put back.
 */

test.use({ storageState: ADMIN_STATE });
test.setTimeout(120_000);

const YELLOW = "#fef08a";

const strip = (page: Page) =>
  page.evaluate(() => {
    const s = window.__beepubReaderNG.core.strip;
    return {
      vertical: s.vertical as boolean,
      position: s.position as number,
      pinned: s.pinnedIndex as number,
      indices: (s.chapters as { index: number }[]).map((c) => c.index),
      log: (s.log as { what: string; index?: number }[]).map(
        (l) => `${l.what}${l.index ?? ""}`,
      ),
    };
  });

const place = (page: Page) =>
  page.evaluate(() => {
    const l = window.__beepubReaderNG.core.lastLocation;
    return {
      index: l.index as number,
      reason: l.reason as string,
      cfi: l.startCfi as string,
      text: ((l.range as Range | null)?.toString() ?? "")
        .trim()
        .replace(/\s+/g, " ")
        .slice(0, 16),
    };
  });

function goTo(page: Page, target: unknown) {
  return page.evaluate(
    (t) => window.__beepubReaderNG.core.goTo(t) as Promise<unknown>,
    target,
  );
}

/** Mark every mounted chapter's frame and iframe: what is still marked
 *  afterwards was not built anew. */
async function markFrames(page: Page) {
  return page.evaluate(() => {
    const frames = window.__beepubReaderNG.core.strip.scroller.querySelectorAll(
      "[data-index], [data-index] iframe",
    );
    for (const el of frames) el.setAttribute("data-kept", "");
    return frames.length as number;
  });
}

const keptFrames = (page: Page) =>
  page.evaluate(
    () =>
      window.__beepubReaderNG.core.strip.scroller.querySelectorAll(
        "[data-kept]",
      ).length as number,
  );

/** How far the first character at `cfi` is from the screen's leading
 *  edge, along the strip (px). */
function fromEdge(page: Page, cfi: string) {
  return page.evaluate((cfi) => {
    const core = window.__beepubReaderNG.core;
    const s = core.strip;
    const target = core.resolve(cfi);
    const { doc } = (
      core.getContents() as { index: number; doc: Document }[]
    ).find((c) => c.index === target.index)!;
    const anchor = target.anchor(doc) as Range;
    const probe = doc.createRange();
    probe.setStart(anchor.startContainer, anchor.startOffset);
    probe.setEnd(anchor.startContainer, anchor.startOffset + 1);
    const rect = probe.getBoundingClientRect();
    const frame = (
      doc.defaultView!.frameElement as HTMLElement
    ).getBoundingClientRect();
    const box = (s.scroller as HTMLElement).getBoundingClientRect();
    return Math.round(
      s.vertical
        ? box.right - (frame.left + rect.right)
        : frame.top + rect.top - box.top,
    );
  }, cfi);
}

async function wheel(page: Page, notches: number) {
  const box = (await page.getByTestId("scroll-strip").boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  const before = (await place(page)).cfi;
  for (let i = 0; i < notches; i++) {
    await page.mouse.wheel(0, 240);
    await page.waitForTimeout(40);
  }
  await expect
    .poll(async () => {
      const p = await place(page);
      return p.reason === "scroll" && p.cfi !== before;
    })
    .toBe(true);
  await page.waitForTimeout(400);
}

const notice = (page: Page) =>
  page.locator(".toast-position").getByTestId("reader-load-notice");

/** A strip whose reader has scrolled to its end and found the next
 *  chapter will not load: the content requests are failing by then. */
async function stuckAtSeam(page: Page, request: APIRequestContext) {
  const bookId = await seedFixture(request, NINE_CHAPTERS_BOOK);
  await resetProgress(request, bookId);
  // Nothing is brought in behind the page (the route also keeps the
  // HTTP cache out).
  await connection(page, { saveData: true });
  const net = { failing: false };
  await page.route("**/api/books/*/content/**", (route) =>
    net.failing ? route.abort() : route.continue(),
  );
  await openBook(page, bookId, { turn: "scroll" }, NINE_CHAPTERS_BOOK);
  net.failing = true;
  // To the end of what is mounted, and again past the chapters the
  // reader had in memory already, until one is missing.
  for (let i = 0; i < 9; i++) {
    await page.evaluate(() => {
      const s = window.__beepubReaderNG.core.strip.scroller;
      s.scrollLeft = -s.scrollWidth;
    });
    try {
      await expect(notice(page)).toBeVisible({ timeout: 1500 });
      break;
    } catch {
      // that one was in memory: it has joined, on to the next
    }
  }
  await expect(notice(page)).toBeVisible();
  return net;
}

test("a chapter that will not load at the end of the strip is said once, and Retry brings it onto the strip", async ({
  page,
  request,
}) => {
  const net = await stuckAtSeam(page, request);
  const stuck = await strip(page);
  const last = stuck.indices.at(-1)!;
  await expect(notice(page)).toHaveCount(1);
  await expect(
    notice(page).getByRole("button", { name: "Retry" }),
  ).toBeVisible();
  // The reader is where they were, and nothing was told of a move.
  expect((await strip(page)).position).toBe(stuck.position);

  // Asked again while it still fails: said again — the one toast.
  await notice(page).getByRole("button", { name: "Retry" }).click();
  await expect
    .poll(
      async () =>
        (await strip(page)).log.filter((l) => l === `failed${last + 1}`).length,
    )
    .toBeGreaterThan(1);
  await expect(notice(page)).toHaveCount(1);
  expect((await strip(page)).indices.at(-1)).toBe(last);

  // The strip also asks again by itself after a while, and fails again:
  // that is not said (no toast that was not on screen before).
  await notice(page).evaluate((el) => el.setAttribute("data-seen", ""));
  const failures = (await strip(page)).log.filter(
    (l) => l === `failed${last + 1}`,
  ).length;
  await expect
    .poll(
      async () =>
        (await strip(page)).log.filter((l) => l === `failed${last + 1}`).length,
      { timeout: 15_000 },
    )
    .toBeGreaterThan(failures);
  await expect(
    page.locator(
      '.toast-position [data-testid="reader-load-notice"]:not([data-seen])',
    ),
  ).toHaveCount(0);
  await expect(notice(page)).toHaveCount(1);
  expect((await strip(page)).indices.at(-1)).toBe(last);

  // The network is back: Retry brings the chapter on, the toast goes.
  net.failing = false;
  await notice(page).getByRole("button", { name: "Retry" }).click();
  await expect
    .poll(async () => (await strip(page)).indices.at(-1))
    .toBe(last + 1);
  await expect(notice(page)).toHaveCount(0);
  // The reader stood at the seam: they are in the chapter that came.
  await expect.poll(async () => (await place(page)).index).toBe(last + 1);
});

test("a chapter that would not load joins by itself once it can, and what was said of it goes", async ({
  page,
  request,
}) => {
  const net = await stuckAtSeam(page, request);
  const last = (await strip(page)).indices.at(-1)!;
  net.failing = false;
  // Nothing is asked of the reader: the strip's own next attempt.
  await expect
    .poll(async () => (await strip(page)).indices.at(-1), { timeout: 15_000 })
    .toBe(last + 1);
  await expect(notice(page)).toHaveCount(0);
  await expect(page.getByTestId("scroll-strip-pending").first()).toBeHidden();
});

test("without a connection a missing chapter is asked for once, said once, and joins by itself when the connection is back", async ({
  page,
  request,
  context,
}) => {
  const bookId = await seedFixture(request, NINE_CHAPTERS_BOOK);
  await resetProgress(request, bookId);
  await connection(page, { saveData: true });
  // (Keeps the HTTP cache out of it.)
  await page.route("**/api/books/*/content/**", (route) => route.continue());
  const asked: string[] = [];
  page.on("request", (r) => {
    const m = /\/content\/.*(c-\d+\.xhtml)/.exec(r.url());
    if (m) asked.push(m[1]);
  });
  await openBook(page, bookId, { turn: "scroll" }, NINE_CHAPTERS_BOOK);
  await context.setOffline(true);
  for (let i = 0; i < 9; i++) {
    await page.evaluate(() => {
      const s = window.__beepubReaderNG.core.strip.scroller;
      s.scrollLeft = -s.scrollWidth;
    });
    try {
      await expect(notice(page)).toBeVisible({ timeout: 1500 });
      break;
    } catch {
      // in memory: joined, on to the next
    }
  }
  await expect(notice(page)).toBeVisible();
  const last = (await strip(page)).indices.at(-1)!;
  const file = `c-00${last + 2}.xhtml`;
  const requests = asked.filter((f) => f === file).length;
  expect(requests).toBeGreaterThan(0);
  // Well past the strip's own time to ask again: offline it does not.
  await page.waitForTimeout(7000);
  expect(asked.filter((f) => f === file).length).toBe(requests);
  expect((await strip(page)).indices.at(-1)).toBe(last);

  await context.setOffline(false);
  await expect
    .poll(async () => (await strip(page)).indices.at(-1), { timeout: 15_000 })
    .toBe(last + 1);
  await expect(notice(page)).toHaveCount(0);
});

for (const [name, fixture, index] of [
  ["vertical", NINE_CHAPTERS_BOOK, 3],
  ["horizontal", LONG_CHAPTERS_BOOK, 1],
] as const satisfies readonly (readonly [string, Fixture, number])[]) {
  test(`a new font size is taken where the chapters stand: the same line at the reading line, no chapter built anew (${name})`, async ({
    page,
    request,
  }) => {
    const bookId = await seedFixture(request, fixture);
    await resetProgress(request, bookId);
    await openBook(page, bookId, { turn: "scroll" }, fixture);
    await goTo(page, index);
    await wheel(page, 9);
    const before = await place(page);
    const edge = await fromEdge(page, before.cfi);
    const frames = await markFrames(page);
    expect(frames).toBeGreaterThan(0);
    const mounted = (await strip(page)).indices;

    await page.getByRole("button", { name: "Reader settings" }).click();
    await page.getByRole("button", { name: "Increase font size" }).click();
    await page.getByRole("button", { name: "Increase font size" }).click();
    await expect(page.getByTestId("setting-font-size")).toHaveText("22px");
    await expect
      .poll(async () => (await strip(page)).log.includes("restyled"))
      .toBe(true);
    await page.waitForTimeout(600);

    // The text is larger in every mounted chapter…
    const sizes = await page.evaluate(() =>
      (window.__beepubReaderNG.core.getContents() as { doc: Document }[]).map(
        (c) => getComputedStyle(c.doc.body).fontSize,
      ),
    );
    expect(new Set(sizes)).toEqual(new Set(["22px"]));
    // …the frames and their documents are the ones that were there…
    expect(await keptFrames(page)).toBe(frames);
    expect((await strip(page)).indices).toEqual(mounted);
    // …and the line that was at the reading line is there still.
    // (Its lines break elsewhere now: the place told is the start of
    // the line that word is in.)
    const after = await place(page);
    expect(after.index).toBe(before.index);
    expect(after.reason).toBe("anchor");
    expect(Math.abs((await fromEdge(page, before.cfi)) - edge)).toBeLessThan(8);

    // And back down again: the same line once more.
    await page.getByRole("button", { name: "Decrease font size" }).click();
    await page.getByRole("button", { name: "Decrease font size" }).click();
    await expect(page.getByTestId("setting-font-size")).toHaveText("18px");
    await page.waitForTimeout(800);
    expect((await place(page)).cfi).toBe(before.cfi);
    expect(Math.abs((await fromEdge(page, before.cfi)) - edge)).toBeLessThan(4);
    expect(await keptFrames(page)).toBe(frames);
  });
}

test("a change of theme moves nothing", async ({ page, request }) => {
  const bookId = await seedFixture(request, NINE_CHAPTERS_BOOK);
  await resetProgress(request, bookId);
  await openBook(page, bookId, { turn: "scroll" }, NINE_CHAPTERS_BOOK);
  await goTo(page, 2);
  await wheel(page, 7);
  const before = await place(page);
  const at = (await strip(page)).position;
  const frames = await markFrames(page);
  const colour = () =>
    page.evaluate(() => {
      const doc = window.__beepubReaderNG.core.getContents()[0].doc as Document;
      return getComputedStyle(doc.body).color;
    });
  const light = await colour();

  await page.getByRole("button", { name: "Toggle dark/light mode" }).click();
  await expect.poll(colour).not.toBe(light);
  await page.waitForTimeout(600);
  expect((await strip(page)).position).toBe(at);
  expect((await place(page)).cfi).toBe(before.cfi);
  expect(await keptFrames(page)).toBe(frames);
});

for (const [name, fixture, index] of [
  ["vertical", NINE_CHAPTERS_BOOK, 3],
  ["horizontal", LONG_CHAPTERS_BOOK, 1],
] as const satisfies readonly (readonly [string, Fixture, number])[]) {
  test(`a window resized keeps the line that was at the reading line (${name})`, async ({
    page,
    request,
  }) => {
    const bookId = await seedFixture(request, fixture);
    await resetProgress(request, bookId);
    await openBook(page, bookId, { turn: "scroll" }, fixture);
    await goTo(page, index);
    await wheel(page, 9);
    const before = await place(page);
    const edge = await fromEdge(page, before.cfi);
    const frames = await markFrames(page);
    const view = page.viewportSize()!;

    await page.setViewportSize({ width: 900, height: 560 });
    await expect
      .poll(async () => (await strip(page)).log.includes("restyled"))
      .toBe(true);
    await page.waitForTimeout(600);
    expect((await place(page)).index).toBe(before.index);
    expect(Math.abs((await fromEdge(page, before.cfi)) - edge)).toBeLessThan(8);
    expect(await keptFrames(page)).toBe(frames);

    await page.setViewportSize(view);
    await page.waitForTimeout(800);
    expect((await place(page)).cfi).toBe(before.cfi);
    expect(Math.abs((await fromEdge(page, before.cfi)) - edge)).toBeLessThan(8);
    expect(await keptFrames(page)).toBe(frames);
  });
}

test("a saved highlight is drawn where its text went after a restyle, and still opens its menu", async ({
  page,
  request,
}) => {
  const bookId = await seedFixture(request, LONG_CHAPTERS_BOOK);
  await resetProgress(request, bookId);
  for (const h of (await (
    await request.get(`/api/books/${bookId}/highlights`)
  ).json()) as { id: string }[])
    await request.delete(`/api/books/${bookId}/highlights/${h.id}`);
  await openBook(page, bookId, { turn: "scroll" }, LONG_CHAPTERS_BOOK);
  await goTo(page, 1);
  // A highlight on words of the chapter's opening lines.
  const made = await page.evaluate(() => {
    const core = window.__beepubReaderNG.core;
    const doc = core.getContents()[0].doc as Document;
    const p = doc.querySelectorAll("p")[0];
    const node = p.firstChild as Text;
    const range = doc.createRange();
    range.setStart(node, 0);
    range.setEnd(node, 24);
    return { cfi: core.cfiOf(1, range) as string, text: range.toString() };
  });
  const created = await request.post(`/api/books/${bookId}/highlights`, {
    data: {
      cfi_range: made.cfi,
      text: made.text,
      color: "yellow",
      section_index: 1,
    },
  });
  expect(created.ok()).toBeTruthy();
  await openBook(page, bookId, { turn: "scroll" }, LONG_CHAPTERS_BOOK);
  await goTo(page, 1);

  /** The mark's first rect and its text's, both in the chapter's own
   *  coordinates, and the mark's centre on screen. */
  const mark = () =>
    page.evaluate((cfi) => {
      const core = window.__beepubReaderNG.core;
      const content = (
        core.getContents() as {
          index: number;
          doc: Document;
          overlayer?: { element: SVGSVGElement };
        }[]
      ).find((c) => c.index === 1)!;
      const g = content.overlayer?.element.querySelector("g");
      const rect = g?.querySelector("rect");
      if (!g || !rect) return null;
      const text = (
        core.resolve(cfi).anchor(content.doc) as Range
      ).getClientRects()[0];
      const frame = (
        content.doc.defaultView!.frameElement as HTMLElement
      ).getBoundingClientRect();
      const x = Number(rect.getAttribute("x"));
      const y = Number(rect.getAttribute("y"));
      const w = Number(rect.getAttribute("width"));
      const h = Number(rect.getAttribute("height"));
      return {
        fill: g.getAttribute("fill"),
        y,
        h,
        textY: text.top,
        textH: text.height,
        centre: {
          x: frame.left + x + Math.min(w, 60) / 2,
          y: frame.top + y + h / 2,
        },
      };
    }, made.cfi);
  await expect.poll(async () => (await mark())?.fill).toBe(YELLOW);
  const before = (await mark())!;
  const frames = await markFrames(page);

  await page.getByRole("button", { name: "Reader settings" }).click();
  for (let i = 0; i < 3; i++)
    await page.getByRole("button", { name: "Increase font size" }).click();
  await expect(page.getByTestId("setting-font-size")).toHaveText("24px");
  await page.keyboard.press("Escape");
  await page.waitForTimeout(800);
  expect(await keptFrames(page)).toBe(frames);
  const after = (await mark())!;
  expect(after.fill).toBe(YELLOW);
  // Drawn over the text where it is now, at its new size.
  expect(after.h).toBeGreaterThan(before.h);
  expect(Math.abs(after.y - after.textY)).toBeLessThan(2);
  expect(Math.abs(after.h - after.textH)).toBeLessThan(2);

  // A tap on it opens the menu on the highlight.
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(after.centre.y).toBeLessThan(page.viewportSize()!.height - 20);
  await page.mouse.click(after.centre.x, after.centre.y);
  const menu = page.getByTestId("highlight-menu");
  await expect(menu).toBeVisible();
  await expect(menu.getByTitle("Remove highlight")).toBeVisible();
  for (const h of (await (
    await request.get(`/api/books/${bookId}/highlights`)
  ).json()) as { id: string }[])
    await request.delete(`/api/books/${bookId}/highlights/${h.id}`);
});
