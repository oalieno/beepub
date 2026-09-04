import {
  test,
  expect,
  devices,
  type APIRequestContext,
  type Page,
} from "@playwright/test";
import { ADMIN_STATE } from "./helpers";
import {
  ANCHOR_BOOK,
  armMenuWatcher,
  iphone,
  marks,
  menuTimeline,
  openBook,
  pointOnWord,
  seedBook,
  seedFixture,
  touchTap,
} from "./ng-helpers";

/**
 * reader-ng G2 ①: saved highlights on the new engine — drawn from the
 * CFIs the current reader stored, byte-compatible CFIs written back, the
 * menu on a saved mark (restyle / remove), and anchors healed by quote
 * when the stored CFI no longer resolves.
 */

/** The first "librarian" as epub.js anchors it (reader-ios-touch.spec). */
const HIGHLIGHT_CFI = "epubcfi(/6/2!/4/4,/1:13,/1:22)";
const YELLOW = "#fef08a";
const BLUE = "#bfdbfe";

test.use({ storageState: ADMIN_STATE, ...iphone });

interface Row {
  id: string;
  cfi_range: string;
  text: string;
  color: string;
  section_index: number | null;
  prefix: string | null;
  suffix: string | null;
}

async function listHighlights(
  request: APIRequestContext,
  bookId: string,
): Promise<Row[]> {
  return (await request.get(`/api/books/${bookId}/highlights`)).json();
}

async function ensureHighlight(
  request: APIRequestContext,
  bookId: string,
  data: { cfi_range: string; text: string; color?: string },
): Promise<Row> {
  const existing = (await listHighlights(request, bookId)).find(
    (h) => h.cfi_range === data.cfi_range,
  );
  if (existing) return existing;
  const created = await request.post(`/api/books/${bookId}/highlights`, {
    data: { color: "yellow", ...data },
  });
  expect(created.ok()).toBeTruthy();
  return created.json();
}

async function deleteHighlights(
  request: APIRequestContext,
  bookId: string,
  match: (row: Row) => boolean,
) {
  for (const h of await listHighlights(request, bookId)) {
    if (!match(h)) continue;
    const res = await request.delete(`/api/books/${bookId}/highlights/${h.id}`);
    expect(res.ok()).toBeTruthy();
  }
}

/** Iframe-local rect of the nth occurrence of a word. */
function wordRect(page: Page, word: string, occurrence: number) {
  return page.evaluate(
    ([word, occurrence]) => {
      const doc: Document = window.__beepubReaderNG.core.getContents()[0].doc;
      const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT);
      let hits = 0;
      while (walker.nextNode()) {
        const node = walker.currentNode;
        const idx = (node.textContent ?? "").indexOf(word as string);
        if (idx < 0 || hits++ < (occurrence as number)) continue;
        const range = doc.createRange();
        range.setStart(node, idx);
        range.setEnd(node, idx + (word as string).length);
        const r = range.getBoundingClientRect();
        return { x: r.left, y: r.top, w: r.width, h: r.height };
      }
      return null;
    },
    [word, occurrence] as const,
  );
}

/** Viewport point at the centre of the first drawn mark. */
async function pointOnMark(page: Page) {
  return page.evaluate(() => {
    const contents = window.__beepubReaderNG.core.getContents()[0];
    const rect = contents.overlayer?.element.querySelector("rect");
    if (!rect) return null;
    const io = (
      contents.doc.defaultView!.frameElement as HTMLIFrameElement
    ).getBoundingClientRect();
    const b = (rect as SVGRectElement).getBBox();
    return { x: io.left + b.x + b.width / 2, y: io.top + b.y + b.height / 2 };
  });
}

function textOfCfi(page: Page, cfi: string) {
  return page.evaluate((cfi) => {
    const core = window.__beepubReaderNG.core;
    const target = core.resolve(cfi);
    const doc: Document = core.getContents()[0].doc;
    return { index: target.index as number, text: String(target.anchor(doc)) };
  }, cfi);
}

test("a highlight saved by the current reader is drawn on the word it anchors", async ({
  page,
}) => {
  const bookId = await seedBook(page.request);
  await ensureHighlight(page.request, bookId, {
    cfi_range: HIGHLIGHT_CFI,
    text: "librarian",
  });
  await openBook(page, bookId);

  await expect.poll(() => marks(page)).toHaveLength(1);
  const [mark] = await marks(page);
  expect(mark.fill).toBe(YELLOW);
  expect(mark.rects).toHaveLength(1);
  const word = await wordRect(page, "librarian", 0);
  expect(word).toBeTruthy();
  const r = mark.rects[0];
  expect(Math.abs(r.x - word!.x)).toBeLessThan(1.5);
  expect(Math.abs(r.w - word!.w)).toBeLessThan(1.5);
  expect(r.y).toBeLessThanOrEqual(word!.y + 0.5);
  expect(r.y + r.h).toBeGreaterThanOrEqual(word!.y + word!.h - 0.5);
});

test("tapping a saved highlight opens the menu once, with the style picker", async ({
  page,
  context,
}) => {
  const bookId = await seedBook(page.request);
  await ensureHighlight(page.request, bookId, {
    cfi_range: HIGHLIGHT_CFI,
    text: "librarian",
  });
  await openBook(page, bookId);
  await expect.poll(() => marks(page)).toHaveLength(1);

  const pt = await pointOnMark(page);
  expect(pt).toBeTruthy();
  await armMenuWatcher(page);
  const cdp = await context.newCDPSession(page);
  // A quick tap: touchstart + touchend + the browser's synthesized click.
  // The touchend's tap-dismiss must not fight the click that opens it.
  await touchTap(cdp, pt!, 80);
  await page.waitForTimeout(1200);
  expect(await menuTimeline(page)).toEqual([expect.stringMatching(/SHOW$/)]);

  const menu = page.getByTestId("highlight-menu");
  await expect(menu).toBeVisible();
  // Existing highlight: the picker row (colours + styles) and remove.
  await expect(menu.getByRole("button", { name: "blue" })).toBeVisible();
  await expect(menu.getByTitle("Remove highlight")).toBeVisible();
  // The page did not turn under the tap (the mark sits in a tap zone).
  await expect(page.getByTestId("ng-chrome")).toBeVisible();
});

test("restyling from the menu repaints the mark and persists", async ({
  page,
  context,
}) => {
  const bookId = await seedBook(page.request);
  const row = await ensureHighlight(page.request, bookId, {
    cfi_range: HIGHLIGHT_CFI,
    text: "librarian",
  });
  await openBook(page, bookId);
  await expect.poll(() => marks(page)).toHaveLength(1);

  const cdp = await context.newCDPSession(page);
  await touchTap(cdp, (await pointOnMark(page))!, 80);
  const menu = page.getByTestId("highlight-menu");
  await expect(menu).toBeVisible();

  const saved = page.waitForResponse(
    (r) => r.request().method() === "PUT" && r.url().includes("/highlights/"),
  );
  await menu.getByRole("button", { name: "blue" }).click();
  expect((await saved).ok()).toBeTruthy();

  await expect(menu).toBeHidden();
  await expect.poll(async () => (await marks(page))[0]?.fill).toBe(BLUE);
  const after = (await listHighlights(page.request, bookId)).find(
    (h) => h.id === row.id,
  );
  expect(after?.color).toBe("blue");

  // Leave the fixture as the other specs expect it.
  await page.request.put(`/api/books/${bookId}/highlights/${row.id}`, {
    data: { color: "yellow" },
  });
});

test("long-press then Highlight saves the CFI the current reader would", async ({
  page,
  context,
}) => {
  const bookId = await seedBook(page.request);
  await deleteHighlights(page.request, bookId, (h) => h.text === "librarian");
  await openBook(page, bookId);
  await expect.poll(() => marks(page)).toHaveLength(0);

  const pt = await pointOnWord(page, "librarian", 0);
  expect(pt).toBeTruthy();
  const cdp = await context.newCDPSession(page);
  await touchTap(cdp, pt!, 900);
  const menu = page.getByTestId("highlight-menu");
  await expect(menu).toBeVisible();
  // Fresh selection: no picker, the plain highlighter.
  await expect(menu.getByRole("button", { name: "blue" })).toHaveCount(0);

  const created = page.waitForResponse(
    (r) => r.request().method() === "POST" && r.url().endsWith("/highlights"),
  );
  await menu.getByTitle("Highlight", { exact: true }).click();
  const res = await created;
  expect(res.ok()).toBeTruthy();
  const row: Row = await res.json();
  // Byte-compatible with epub.js: the same anchor the old reader stores
  // for this word, so either reader draws the other's highlights.
  expect(row.cfi_range).toBe(HIGHLIGHT_CFI);
  expect(row.text).toBe("librarian");
  expect(row.section_index).toBe(0);
  expect(row.prefix).toContain("starship ");
  expect(row.suffix).toContain(" shelved");

  await expect(menu).toBeHidden();
  await expect.poll(() => marks(page)).toHaveLength(1);
  expect((await marks(page))[0].fill).toBe(YELLOW);
});

test("removing from the menu deletes the mark and the row", async ({
  page,
  context,
}) => {
  const bookId = await seedBook(page.request);
  const row = await ensureHighlight(page.request, bookId, {
    cfi_range: HIGHLIGHT_CFI,
    text: "librarian",
  });
  await openBook(page, bookId);
  await expect.poll(() => marks(page)).toHaveLength(1);

  const cdp = await context.newCDPSession(page);
  await touchTap(cdp, (await pointOnMark(page))!, 80);
  const menu = page.getByTestId("highlight-menu");
  await expect(menu).toBeVisible();

  const deleted = page.waitForResponse(
    (r) =>
      r.request().method() === "DELETE" && r.url().includes("/highlights/"),
  );
  await menu.getByTitle("Remove highlight").click();
  expect((await deleted).ok()).toBeTruthy();

  await expect(menu).toBeHidden();
  await expect.poll(() => marks(page)).toHaveLength(0);
  const rows = await listHighlights(page.request, bookId);
  expect(rows.some((h) => h.id === row.id)).toBe(false);

  // Restore for the specs that expect the fixture highlight.
  await ensureHighlight(page.request, bookId, {
    cfi_range: HIGHLIGHT_CFI,
    text: "librarian",
  });
});

test("anchors that stopped resolving are healed by their quote, or reported", async ({
  page,
}) => {
  const bookId = await seedFixture(page.request, ANCHOR_BOOK);
  await deleteHighlights(page.request, bookId, () => true);
  // Three rows with a stale anchor (the first word of the first paragraph
  // — resolvable, but not their text): one whose quote is still in that
  // section, one whose quote lives in the next section, one with no quote
  // in the book at all.
  const stale = "epubcfi(/6/2!/4/4,/1:0,/1:3)";
  const post = (data: object) =>
    page.request.post(`/api/books/${bookId}/highlights`, {
      data: { cfi_range: stale, color: "yellow", section_index: 0, ...data },
    });
  const same = await (
    await post({
      text: "green lantern crossed the bay twice",
      prefix: "On the third night a ",
      suffix: ", and the keeper underlined",
    })
  ).json();
  const moved = await (
    await post({ text: "unimpressed by the mystery", prefix: "and back, " })
  ).json();
  const lost = await (
    await post({ text: "no such sentence anywhere in this book" })
  ).json();

  await openBook(page, bookId, {}, ANCHOR_BOOK);

  // The heal writes back through the API; poll the rows.
  await expect
    .poll(
      async () =>
        (await listHighlights(page.request, bookId)).find(
          (h) => h.id === moved.id,
        )?.section_index,
      { timeout: 15_000 },
    )
    .toBe(1);
  const rows = await listHighlights(page.request, bookId);
  const healedSame = rows.find((h) => h.id === same.id)!;
  const healedMoved = rows.find((h) => h.id === moved.id)!;
  const stillLost = rows.find((h) => h.id === lost.id)!;
  expect(healedSame.cfi_range).not.toBe(stale);
  expect(healedSame.section_index).toBe(0);
  expect(healedMoved.cfi_range).not.toBe(stale);
  expect(healedMoved.cfi_range.startsWith("epubcfi(/6/4!")).toBe(true);
  expect(stillLost.cfi_range).toBe(stale);

  // The healed CFI resolves to exactly the quote, and is drawn there.
  expect(await textOfCfi(page, healedSame.cfi_range)).toEqual({
    index: 0,
    text: "green lantern crossed the bay twice",
  });
  // Two marks in this section: the healed one on its quote, and the lost
  // one still at its stale anchor (a CFI that resolves is drawn where it
  // points, as the current reader does; the list flags it).
  await expect.poll(() => marks(page)).toHaveLength(2);
  const twice = await wordRect(page, "twice", 0);
  expect(twice).toBeTruthy();
  const covers = (await marks(page)).some((mark) =>
    mark.rects.some(
      (r) =>
        r.x <= twice!.x + 0.5 &&
        r.x + r.w >= twice!.x + twice!.w - 0.5 &&
        r.y <= twice!.y + 0.5 &&
        r.y + r.h >= twice!.y + twice!.h - 0.5,
    ),
  );
  expect(covers).toBe(true);

  // The unhealable one is flagged in the list.
  await page.getByRole("button", { name: "Highlights" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(
    dialog.getByText("Original position not found (book file changed)"),
  ).toHaveCount(1);
});

test.describe("desktop", () => {
  const { defaultBrowserType: _chrome, ...desktop } = devices["Desktop Chrome"];
  test.use(desktop);

  test("a mouse click on a saved highlight opens the menu; hover shows a pointer", async ({
    page,
  }) => {
    const bookId = await seedBook(page.request);
    await ensureHighlight(page.request, bookId, {
      cfi_range: HIGHLIGHT_CFI,
      text: "librarian",
    });
    await openBook(page, bookId);
    await expect.poll(() => marks(page)).toHaveLength(1);

    const pt = (await pointOnMark(page))!;
    await page.mouse.move(pt.x, pt.y);
    await expect
      .poll(() =>
        page.evaluate(
          () =>
            (window.__beepubReaderNG.core.getContents()[0].doc as Document).body
              .style.cursor,
        ),
      )
      .toBe("pointer");

    await page.mouse.click(pt.x, pt.y);
    const menu = page.getByTestId("highlight-menu");
    await expect(menu).toBeVisible();
    await expect(menu.getByRole("button", { name: "blue" })).toBeVisible();
    // The click landed in a tap zone; the mark won, no page turn.
    expect(
      await page.evaluate(
        () => window.__beepubReaderNG.core.lastLocation.reason,
      ),
    ).not.toBe("page");
  });
});
