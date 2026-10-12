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
  NOTES_BOOK,
  iphone,
  openBook,
  resetProgress,
  seedFixture,
  type Fixture,
} from "./ng-helpers";

/**
 * The scroll mode (?turn=scroll), what is done ON the strip: saved
 * highlights and the menu on them, selection, footnotes and links, keys,
 * search — in whichever mounted chapter it happens, not only the one
 * under the reading line — and the place a finished book reports.
 */

test.use({ storageState: ADMIN_STATE });
test.setTimeout(120_000);

const YELLOW = "#fef08a";
const FLASH = "#fed7aa";

interface Row {
  id: string;
  cfi_range: string;
  text: string;
  section_index: number | null;
}

async function listHighlights(
  request: APIRequestContext,
  bookId: string,
): Promise<Row[]> {
  return (await request.get(`/api/books/${bookId}/highlights`)).json();
}

async function clearHighlights(request: APIRequestContext, bookId: string) {
  for (const h of await listHighlights(request, bookId))
    await request.delete(`/api/books/${bookId}/highlights/${h.id}`);
}

async function openStrip(
  page: Page,
  bookId: string,
  fixture: Fixture,
  extra: Record<string, string> = {},
) {
  await openBook(page, bookId, { turn: "scroll", ...extra }, fixture);
}

function goTo(page: Page, target: unknown) {
  return page.evaluate(
    (t) => window.__beepubReaderNG.core.goTo(t) as Promise<unknown>,
    target,
  );
}

const strip = (page: Page) =>
  page.evaluate(() => {
    const s = window.__beepubReaderNG.core.strip;
    return {
      vertical: s.vertical as boolean,
      position: s.position as number,
      pinned: s.pinnedIndex as number,
      indices: (s.chapters as { index: number }[]).map((c) => c.index),
      screen: (s.vertical
        ? s.scroller.clientWidth
        : s.scroller.clientHeight) as number,
    };
  });

const place = (page: Page) =>
  page.evaluate(() => {
    const l = window.__beepubReaderNG.core.lastLocation;
    return {
      index: l.index as number,
      reason: l.reason as string,
      cfi: l.startCfi as string,
    };
  });

/** Read to the last lines of the chapter before `index`: that one comes
 *  onto the strip behind it. */
async function bringIn(page: Page, index: number) {
  await goTo(page, { index: index - 1, fraction: 0.985 });
  await expect.poll(async () => (await strip(page)).indices).toContain(index);
  expect((await strip(page)).pinned).toBe(index - 1);
}

/** Put the start of chapter `index` this far (px) inside the screen:
 *  the chapter before it is the one being read. */
async function showStartOf(page: Page, index: number, inside: number) {
  await page.evaluate(
    ([index, inside]) => {
      const s = window.__beepubReaderNG.core.strip;
      const chapter = (s.chapters as { index: number; top: number }[]).find(
        (c) => c.index === index,
      )!;
      const screen = s.vertical
        ? s.scroller.clientWidth
        : s.scroller.clientHeight;
      const at = chapter.top - (screen - inside);
      if (s.vertical) s.scroller.scrollLeft = -at;
      else s.scroller.scrollTop = at;
    },
    [index, inside] as const,
  );
  await expect.poll(async () => (await strip(page)).pinned).toBe(index - 1);
  await page.waitForTimeout(400);
}

/** The fills of the marks drawn over chapter `index`. */
function marksOf(page: Page, index: number) {
  return page.evaluate((index) => {
    const content = (
      window.__beepubReaderNG.core.getContents() as {
        index: number;
        overlayer?: { element: SVGSVGElement };
      }[]
    ).find((c) => c.index === index);
    if (!content?.overlayer) return null;
    return Array.from(content.overlayer.element.querySelectorAll("g")).map(
      (g) => g.getAttribute("fill"),
    );
  }, index);
}

/** Viewport box of the nth occurrence of `text` in chapter `index`. */
function boxOf(page: Page, index: number, text: string, occurrence = 0) {
  return page.evaluate(
    ([index, text, occurrence]) => {
      const content = (
        window.__beepubReaderNG.core.getContents() as {
          index: number;
          doc: Document;
        }[]
      ).find((c) => c.index === index);
      if (!content) return null;
      const { doc } = content;
      const frame = (
        doc.defaultView!.frameElement as HTMLElement
      ).getBoundingClientRect();
      const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT);
      let hits = 0;
      while (walker.nextNode()) {
        const node = walker.currentNode;
        const at = (node.textContent ?? "").indexOf(text as string);
        if (at < 0 || hits++ < (occurrence as number)) continue;
        const range = doc.createRange();
        range.setStart(node, at);
        range.setEnd(node, at + (text as string).length);
        const r = range.getBoundingClientRect();
        return {
          x: frame.left + r.left,
          y: frame.top + r.top,
          w: r.width,
          h: r.height,
        };
      }
      return null;
    },
    [index, text, occurrence] as const,
  );
}

/** The CFI of `text` in chapter `index`, as the reader would write it. */
function cfiOf(page: Page, index: number, text: string) {
  return page.evaluate(
    ([index, text]) => {
      const core = window.__beepubReaderNG.core;
      const { doc } = (
        core.getContents() as { index: number; doc: Document }[]
      ).find((c) => c.index === index)!;
      const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT);
      while (walker.nextNode()) {
        const node = walker.currentNode;
        const at = (node.textContent ?? "").indexOf(text as string);
        if (at < 0) continue;
        const range = doc.createRange();
        range.setStart(node, at);
        range.setEnd(node, at + (text as string).length);
        return core.cfiOf(index, range) as string;
      }
      return null;
    },
    [index, text] as const,
  );
}

/** What a CFI names, read from the book itself. */
function textOfCfi(page: Page, cfi: string) {
  return page.evaluate(async (cfi) => {
    const core = window.__beepubReaderNG.core;
    const target = core.resolve(cfi);
    const doc = await core.pristineDocument(target.index);
    return (target.anchor(doc) as Range).toString();
  }, cfi);
}

const menu = (page: Page) => page.getByTestId("highlight-menu");

test("a saved highlight is drawn in a chapter that is mounted but not being read, and again when that chapter has left the strip and come back", async ({
  page,
  request,
}) => {
  const bookId = await seedFixture(request, NINE_CHAPTERS_BOOK);
  await resetProgress(request, bookId);
  await clearHighlights(request, bookId);
  await openStrip(page, bookId, NINE_CHAPTERS_BOOK);
  await goTo(page, 4);
  const cfi = await cfiOf(page, 4, "渡客之章第2段");
  expect(cfi).toBeTruthy();
  const created = await request.post(`/api/books/${bookId}/highlights`, {
    data: {
      cfi_range: cfi,
      text: "渡客之章第2段",
      color: "yellow",
      section_index: 4,
    },
  });
  expect(created.ok()).toBeTruthy();

  await openStrip(page, bookId, NINE_CHAPTERS_BOOK);
  // The end of the chapter before: the marked one is on the strip
  // behind it, and its start is not on screen.
  await goTo(page, { index: 3, fraction: 0.6 });
  await expect.poll(async () => (await strip(page)).indices).toContain(4);
  await expect.poll(async () => (await strip(page)).pinned).toBe(3);
  await expect.poll(() => marksOf(page, 4)).toEqual([YELLOW]);
  // No other chapter carries it.
  expect(await marksOf(page, 3)).toEqual([]);

  // Back until that chapter is let go…
  const box = (await page.getByTestId("scroll-strip").boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  for (let i = 0; i < 400 && (await strip(page)).indices.includes(4); i++) {
    await page.mouse.wheel(0, -box.height);
    await page.waitForTimeout(40);
  }
  expect((await strip(page)).indices).not.toContain(4);
  expect(await marksOf(page, 4)).toBeNull();
  // …and forward until it has joined again.
  for (let i = 0; i < 400 && !(await strip(page)).indices.includes(4); i++) {
    await page.mouse.wheel(0, box.height);
    await page.waitForTimeout(40);
  }
  await expect.poll(() => marksOf(page, 4)).toEqual([YELLOW]);
  await clearHighlights(request, bookId);
});

for (const [name, fixture, index, word] of [
  ["vertical", NINE_CHAPTERS_BOOK, 3, "燈語之章第1段"],
  ["horizontal", LONG_CHAPTERS_BOOK, 1, "Midwater"],
] as const) {
  test(`a selection in the chapter after the one being read becomes a highlight there, found again after a reload and opened by a tap (${name})`, async ({
    page,
    request,
  }) => {
    const bookId = await seedFixture(request, fixture);
    await resetProgress(request, bookId);
    await clearHighlights(request, bookId);
    await openStrip(page, bookId, fixture);
    await bringIn(page, index);
    await showStartOf(page, index, 320);

    // Select by dragging the mouse across the words.
    const target = name === "vertical" ? word : "Signal log";
    const at = (await boxOf(page, index, target))!;
    expect(at).toBeTruthy();
    const from = { x: at.x + 2, y: at.y + 2 };
    const to = { x: at.x + at.w - 2, y: at.y + at.h - 2 };
    await page.mouse.move(from.x, from.y);
    await page.mouse.down();
    await page.mouse.move((from.x + to.x) / 2, (from.y + to.y) / 2, {
      steps: 4,
    });
    await page.mouse.move(to.x, to.y, { steps: 4 });
    await page.mouse.up();
    await expect(menu(page)).toBeVisible();
    // The menu stands by the selection, in the chapter it is in.
    const menuBox = (await menu(page).boundingBox())!;
    expect(Math.abs(menuBox.y + menuBox.height - at.y)).toBeLessThan(120);

    const saved = page.waitForResponse(
      (r) => r.request().method() === "POST" && r.url().includes("/highlights"),
    );
    await menu(page).getByTitle("Highlight").last().click();
    expect((await saved).ok()).toBeTruthy();
    const rows = await listHighlights(request, bookId);
    expect(rows).toHaveLength(1);
    // The chapter touched, not the one under the reading line.
    expect((await strip(page)).pinned).toBe(index - 1);
    expect(rows[0].section_index).toBe(index);
    expect(rows[0].text.length).toBeGreaterThan(0);
    expect((await textOfCfi(page, rows[0].cfi_range)).trim()).toBe(
      rows[0].text,
    );
    await expect.poll(() => marksOf(page, index)).toEqual([YELLOW]);

    // Again from the server: drawn where it was made, and a tap on it —
    // still not in the chapter being read — opens the menu on it.
    await openStrip(page, bookId, fixture);
    await bringIn(page, index);
    await showStartOf(page, index, 320);
    await expect.poll(() => marksOf(page, index)).toEqual([YELLOW]);
    const again = (await boxOf(page, index, rows[0].text.slice(0, 4)))!;
    await page.mouse.click(again.x + again.w / 2, again.y + again.h / 2);
    await expect(menu(page)).toBeVisible();
    await expect(menu(page).getByTitle("Remove highlight")).toBeVisible();

    // Scrolled, the menu goes with its text; scrolled away, it goes.
    const before = (await menu(page).boundingBox())!;
    await page.mouse.move(again.x, again.y);
    await page.mouse.wheel(0, 60);
    await expect
      .poll(async () => {
        const b = await menu(page).boundingBox();
        return b ? Math.round(b.x - before.x) || Math.round(b.y - before.y) : 0;
      })
      .not.toBe(0);
    await goTo(page, 0);
    await expect(menu(page)).toBeHidden();
    await clearHighlights(request, bookId);
  });
}

test("a drag that begins in one chapter and ends over the next selects in the first, and nothing breaks", async ({
  page,
  request,
}) => {
  const bookId = await seedFixture(request, LONG_CHAPTERS_BOOK);
  await resetProgress(request, bookId);
  await openStrip(page, bookId, LONG_CHAPTERS_BOOK);
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await bringIn(page, 1);
  await showStartOf(page, 1, 320);
  const heading = (await boxOf(page, 1, "Midwater"))!;
  // From the last words of the first chapter down into the second.
  const tail = (await boxOf(page, 0, "morning distant tide"))!;
  expect(tail).toBeTruthy();
  await page.mouse.move(tail.x + 2, tail.y + tail.h / 2);
  await page.mouse.down();
  await page.mouse.move(tail.x + 40, tail.y + tail.h / 2, { steps: 4 });
  await page.mouse.move(heading.x + 80, heading.y + 60, { steps: 8 });
  await page.mouse.up();
  await page.waitForTimeout(400);
  expect(errors).toEqual([]);
  const selected = await page.evaluate(() =>
    (
      window.__beepubReaderNG.core.getContents() as {
        index: number;
        doc: Document;
      }[]
    ).map((c) => ({
      index: c.index,
      text: c.doc.getSelection()?.toString().trim().length ?? 0,
    })),
  );
  // One chapter holds the selection, and the menu is on it.
  expect(selected.filter((s) => s.text > 0).map((s) => s.index)).toEqual([0]);
  await expect(menu(page)).toBeVisible();
  // A tap beside the text puts it away, in whichever chapter it is.
  await page.waitForTimeout(600);
  await page.mouse.click(8, heading.y + 200);
  await expect(menu(page)).toBeHidden();
});

test("footnotes open their popup and links jump, from any chapter on the strip and into one that is not on it", async ({
  page,
  request,
}) => {
  const clickIn = (index: number, selector: string) =>
    page.evaluate(
      ([index, selector]) => {
        const content = (
          window.__beepubReaderNG.core.getContents() as {
            index: number;
            doc: Document;
          }[]
        ).find((c) => c.index === index);
        const el = content?.doc.querySelector(selector as string);
        if (!el) throw new Error(`no ${selector} in chapter ${index}`);
        (el as HTMLElement).click();
      },
      [index, selector] as const,
    );
  const bookId = await seedFixture(request, NOTES_BOOK);
  await resetProgress(request, bookId);
  await openStrip(page, bookId, NOTES_BOOK);
  const popup = page.locator(".footnote-content");

  // (The second chapter on the strip behind the first.)
  await bringIn(page, 1);
  await page.waitForTimeout(400);
  // A note reference whose target is in another file: the note comes to
  // the reader, who stays put.
  const before = await strip(page);
  await clickIn(0, "#enref1");
  await expect(popup).toBeVisible();
  await expect(popup).toContainText("oil-fed");
  expect((await strip(page)).position).toBe(before.position);
  // A paging key puts the note away instead of moving under it.
  await page.keyboard.press("ArrowDown");
  await expect(popup).toBeHidden();
  await page.waitForTimeout(600);
  expect((await strip(page)).position).toBe(before.position);

  // A same-file note in the second chapter — mounted, not the one read.
  expect((await strip(page)).pinned).toBe(0);
  await clickIn(1, "#fnref1");
  await expect(popup).toBeVisible();
  await expect(popup).toContainText("brown paper");
  await page.keyboard.press("Escape");
  await expect(popup).toBeHidden();

  // A plain cross-file link: the strip goes there.
  await clickIn(0, "#notes-link");
  await expect.poll(async () => (await place(page)).index).toBe(1);
  expect((await place(page)).reason).toBe("navigation");

  // A link into a chapter that is not on the strip: it is loaded first,
  // then the strip is built around it.
  const nine = await seedFixture(request, NINE_CHAPTERS_BOOK);
  await resetProgress(request, nine);
  await openStrip(page, nine, NINE_CHAPTERS_BOOK);
  expect((await strip(page)).indices).not.toContain(7);
  await page.evaluate(() => {
    const doc = window.__beepubReaderNG.core.getContents()[0].doc as Document;
    const a = doc.createElement("a");
    a.setAttribute("href", "c-008.xhtml");
    a.id = "far-link";
    a.textContent = "歸港";
    doc.body.append(a);
  });
  await clickIn(0, "#far-link");
  await expect.poll(async () => (await place(page)).index).toBe(7);
  expect((await strip(page)).pinned).toBe(7);
  expect((await place(page)).reason).toBe("navigation");
});

test("keys move a screen along the strip: down the page in a horizontal book, leftward in a vertical one", async ({
  page,
  request,
}) => {
  const settled = async () => {
    let last = -1;
    await expect
      .poll(async () => {
        const now = (await strip(page)).position;
        const still = now === last;
        last = now;
        return still;
      })
      .toBe(true);
    return (await strip(page)).position;
  };
  const press = async (key: string) => {
    await page.keyboard.press(key);
    await page.waitForTimeout(150);
    return settled();
  };

  const long = await seedFixture(request, LONG_CHAPTERS_BOOK);
  await resetProgress(request, long);
  await openStrip(page, long, LONG_CHAPTERS_BOOK);
  await goTo(page, 1);
  let at = await settled();
  const step = Math.round((await strip(page)).screen * 0.9);
  for (const key of ["ArrowDown", "PageDown", " ", "ArrowRight"]) {
    const next = await press(key);
    expect(next - at).toBe(step);
    at = next;
  }
  for (const key of ["ArrowUp", "PageUp", "ArrowLeft"]) {
    const next = await press(key);
    expect(at - next).toBe(step);
    at = next;
  }
  // A key is a move of the reader's: the place is told and saved as one.
  await expect.poll(async () => (await place(page)).reason).toBe("scroll");

  const nine = await seedFixture(request, NINE_CHAPTERS_BOOK);
  await resetProgress(request, nine);
  await openStrip(page, nine, NINE_CHAPTERS_BOOK);
  await goTo(page, 2);
  expect((await strip(page)).vertical).toBe(true);
  at = await settled();
  const across = Math.round((await strip(page)).screen * 0.9);
  for (const key of ["ArrowLeft", "ArrowDown", "PageDown"]) {
    const next = await press(key);
    expect(next - at).toBe(across);
    at = next;
  }
  for (const key of ["ArrowRight", "ArrowUp"]) {
    const next = await press(key);
    expect(at - next).toBe(across);
    at = next;
  }
});

test("a search hit is jumped to and flashed, in a chapter on the strip and in one that is not", async ({
  page,
  request,
}) => {
  const search = async (query: string, pick: string) => {
    await page.getByRole("button", { name: "Search in Book" }).click();
    const dialog = page.getByRole("dialog", { name: "Search in Book" });
    await dialog.getByRole("textbox").fill(query);
    await expect(dialog).toContainText(/\d+ results/);
    await dialog.getByRole("button").filter({ hasText: pick }).first().click();
    await expect(dialog).toBeHidden();
  };

  // Both chapters of this book are on the strip from the start.
  const notes = await seedFixture(request, NOTES_BOOK);
  await resetProgress(request, notes);
  await openStrip(page, notes, NOTES_BOOK);
  await bringIn(page, 1);
  await page.evaluate(() =>
    window.__beepubReaderNG.core.strip.scroller
      .querySelector('[data-index="0"]')
      .setAttribute("data-kept", ""),
  );
  await search("quillstorm", "quillstorm");
  await expect.poll(() => marksOf(page, 1)).toEqual([FLASH]);
  expect(await marksOf(page, 0)).toEqual([]);
  // (The strip was moved, not built anew.)
  expect(
    await page.evaluate(
      () =>
        !!window.__beepubReaderNG.core.strip.scroller.querySelector(
          "[data-kept]",
        ),
    ),
  ).toBe(true);
  const word = (await boxOf(page, 1, "quillstorm"))!;
  const view = page.viewportSize()!;
  expect(word.y).toBeGreaterThanOrEqual(0);
  expect(word.y + word.h).toBeLessThanOrEqual(view.height);
  await expect.poll(() => marksOf(page, 1), { timeout: 6_000 }).toEqual([]);

  // A hit far ahead, in a chapter that has to be brought in.
  const nine = await seedFixture(request, NINE_CHAPTERS_BOOK);
  await resetProgress(request, nine);
  await openStrip(page, nine, NINE_CHAPTERS_BOOK, { font: "sans" });
  expect((await strip(page)).indices).not.toContain(7);
  await search("歸港之章第3段", "歸港之章第3段");
  await expect.poll(async () => (await place(page)).index).toBe(7);
  await expect.poll(() => marksOf(page, 7)).toEqual([FLASH]);
  const hit = (await boxOf(page, 7, "歸港之章第3段"))!;
  expect(hit.x).toBeGreaterThanOrEqual(0);
  expect(hit.x + hit.w).toBeLessThanOrEqual(view.width);
});

test("a finished book is in its last chapter — by the chapter named and by the place saved — though that chapter is too short to reach the reading line", async ({
  page,
  request,
}) => {
  const bookId = await seedFixture(request, NINE_CHAPTERS_BOOK);
  await resetProgress(request, bookId);
  await openStrip(page, bookId, NINE_CHAPTERS_BOOK);
  const label = () =>
    page
      .locator('[data-testid="reader-chapter"]:visible')
      .textContent()
      .then((t) => (t ?? "").trim());
  const percent = () =>
    page
      .locator('[data-testid="reader-percent"]:visible')
      .textContent()
      .then((t) => parseInt(t ?? "", 10));
  await goTo(page, { index: 7, fraction: 0.3 });
  await expect.poll(label).toBe("歸港");
  expect(await percent()).toBeLessThan(100);

  // To the very end: the last chapter (the 版權頁) is narrower than the
  // screen, so the reading line is still in the chapter before it.
  await page.evaluate(() => {
    const s = window.__beepubReaderNG.core.strip.scroller;
    s.scrollLeft = -s.scrollWidth;
  });
  await expect.poll(percent).toBe(100);
  expect((await strip(page)).pinned).toBe(7);
  await expect.poll(async () => (await place(page)).index).toBe(8);
  await expect.poll(label).toBe("版權頁");
  const end = await place(page);
  await expect
    .poll(async () => {
      const res = await request.get(`/api/books/${bookId}/progress`);
      return (await res.json()).cfi as string;
    })
    .toBe(end.cfi);

  // Opened again: the same screen, the same chapter named, still 100%.
  await page.goto(
    `/books/${bookId}/read?size=18&lh=1.8&mx=24&my=48&turn=scroll`,
  );
  await page.waitForFunction(
    () => !!window.__beepubReaderNG?.core?.lastLocation,
  );
  await expect.poll(async () => (await place(page)).index).toBe(8);
  expect((await place(page)).cfi).toBe(end.cfi);
  await expect.poll(label).toBe("版權頁");
  await expect.poll(percent).toBe(100);

  // And a step back from the end is the chapter under the line again.
  await page.keyboard.press("ArrowRight");
  await expect.poll(async () => (await place(page)).index).toBe(7);
  await expect.poll(label).toBe("歸港");
  await expect.poll(percent).toBeLessThan(100);
});

test("a long press on a picture opens it full-screen, and the strip stays where it is", async ({
  page,
  request,
}) => {
  const bookId = await seedFixture(request, NINE_CHAPTERS_BOOK);
  await resetProgress(request, bookId);
  await openStrip(page, bookId, NINE_CHAPTERS_BOOK);
  await goTo(page, 4);
  // Bring the chapter's picture to the middle of the screen.
  await page.evaluate(() => {
    const core = window.__beepubReaderNG.core;
    const s = core.strip;
    const doc = (core.getContents() as { index: number; doc: Document }[]).find(
      (c) => c.index === 4,
    )!.doc;
    const rect = doc.querySelector("img")!.getBoundingClientRect();
    const chapter = (
      s.chapters as { index: number; top: number; height: number }[]
    ).find((c) => c.index === 4)!;
    s.scroller.scrollLeft = -(
      chapter.top +
      (chapter.height - rect.right) -
      s.scroller.clientWidth / 2
    );
  });
  await page.waitForTimeout(500);
  const pt = await page.evaluate(() => {
    const doc = (
      window.__beepubReaderNG.core.getContents() as {
        index: number;
        doc: Document;
      }[]
    ).find((c) => c.index === 4)!.doc;
    const frame = (
      doc.defaultView!.frameElement as HTMLElement
    ).getBoundingClientRect();
    const r = doc.querySelector("img")!.getBoundingClientRect();
    return {
      x: frame.left + r.left + r.width / 2,
      y: frame.top + r.top + r.height / 2,
    };
  });
  const close = page.getByRole("button", { name: "Close", exact: true });
  const before = (await strip(page)).position;
  await page.mouse.move(pt.x, pt.y);
  await page.mouse.down();
  await page.waitForTimeout(700);
  await page.mouse.up();
  await expect(close).toBeVisible();
  expect((await strip(page)).position).toBe(before);
  await page.keyboard.press("Escape");
  await expect(close).toHaveCount(0);
});

test.describe("on a phone", () => {
  test.use({ ...iphone });

  test("a long press selects and its drag draws the selection out while the strip holds still; any other drag scrolls", async ({
    page,
    request,
    context,
  }) => {
    const bookId = await seedFixture(request, LONG_CHAPTERS_BOOK);
    await resetProgress(request, bookId);
    await clearHighlights(request, bookId);
    await openStrip(page, bookId, LONG_CHAPTERS_BOOK);
    await goTo(page, { index: 1, fraction: 0.2 });
    await page.waitForTimeout(400);
    const cdp = await context.newCDPSession(page);
    const touch = (type: string, pt?: { x: number; y: number }) =>
      cdp.send("Input.dispatchTouchEvent", {
        type: type as "touchStart",
        touchPoints: pt ? [pt] : [],
      });
    const overflow = () =>
      page.evaluate(
        () =>
          (window.__beepubReaderNG.core.strip.scroller as HTMLElement).style
            .overflowY,
      );
    const selection = () =>
      page.evaluate(() =>
        (window.__beepubReaderNG.core.getContents() as { doc: Document }[])
          .map((c) => {
            // (Under the phone's own user-select the selection's string
            // is empty; its range is what the reader made.)
            const sel = c.doc.getSelection();
            return sel?.rangeCount ? sel.getRangeAt(0).toString() : "";
          })
          .join("")
          .trim(),
      );
    const view = page.viewportSize()!;
    const mid = { x: view.width / 2, y: view.height / 2 };
    /** A point on the word nearest the middle of the screen. */
    const onWord = () =>
      page.evaluate(
        ([x, y]) => {
          for (const { doc } of window.__beepubReaderNG.core.getContents() as {
            doc: Document;
          }[]) {
            const frame = (
              doc.defaultView!.frameElement as HTMLElement
            ).getBoundingClientRect();
            if (y < frame.top || y > frame.bottom) continue;
            // (Not the caret under the point: under the phone's own
            // user-select that is not always the text there.)
            const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT);
            const range = doc.createRange();
            while (walker.nextNode()) {
              const node = walker.currentNode;
              const text = node.textContent ?? "";
              if (!text.trim()) continue;
              range.selectNodeContents(node);
              const box = range.getBoundingClientRect();
              if (
                frame.top + box.bottom < y - 40 ||
                frame.top + box.top > y + 40
              )
                continue;
              for (let at = 0; at < text.length; at++) {
                if (!/[a-z]/i.test(text[at])) continue;
                range.setStart(node, at);
                range.setEnd(node, at + 1);
                const r = range.getBoundingClientRect();
                const cy = frame.top + r.top + r.height / 2;
                const cx = frame.left + r.left + r.width / 2;
                if (Math.abs(cy - y) < 40 && Math.abs(cx - x) < 80)
                  return { x: cx, y: cy };
              }
            }
          }
          return null;
        },
        [mid.x, mid.y] as const,
      );

    // A drag: the strip follows the finger, nothing is selected.
    const start = (await strip(page)).position;
    await touch("touchStart", mid);
    for (let i = 1; i <= 6; i++) {
      await page.waitForTimeout(20);
      await touch("touchMove", { x: mid.x, y: mid.y - i * 30 });
    }
    await touch("touchEnd");
    await expect
      .poll(async () => (await strip(page)).position)
      .toBeGreaterThan(start + 100);
    expect(await selection()).toBe("");
    await expect(menu(page)).toBeHidden();
    // (Well after the fling has died away: a touch that follows one
    // closely is the browser's own, and never reaches the page.)
    await page.waitForTimeout(2500);

    // A long press: a word is selected, the menu is on it, and while the
    // finger stays down the strip does not scroll under a drag.
    const rest = (await strip(page)).position;
    const word0 = (await onWord())!;
    expect(word0).toBeTruthy();
    await touch("touchStart", word0);
    await expect.poll(overflow).toBe("hidden");
    const word = await selection();
    expect(word.length).toBeGreaterThan(0);
    for (let i = 1; i <= 5; i++) {
      await page.waitForTimeout(30);
      await touch("touchMove", { x: word0.x + i * 10, y: word0.y + i * 14 });
    }
    expect((await selection()).length).toBeGreaterThan(word.length);
    expect((await strip(page)).position).toBe(rest);
    await touch("touchEnd");
    expect(await overflow()).toBe("auto");
    await expect(menu(page)).toBeVisible();
    expect((await strip(page)).position).toBe(rest);

    // Saved from the menu, in the chapter it was made in.
    const saved = page.waitForResponse(
      (r) => r.request().method() === "POST" && r.url().includes("/highlights"),
    );
    await menu(page).getByTitle("Highlight").last().click();
    expect((await saved).ok()).toBeTruthy();
    const rows = await listHighlights(request, bookId);
    expect(rows).toHaveLength(1);
    expect(rows[0].section_index).toBe(1);
    await expect.poll(() => marksOf(page, 1)).toEqual([YELLOW]);
    await clearHighlights(request, bookId);
  });
});
