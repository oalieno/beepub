import { test, expect, type Page } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";
import {
  NOTES_BOOK,
  VERTICAL_LONG_BOOK,
  iphone,
  location,
  marks,
  openBook,
  seedFixture,
  touchTap,
} from "./ng-helpers";

/**
 * reader-ng G2 ⑤: the navigation chrome on the new engine — the table of
 * contents (nested entries, fragment targets, the entry the page is
 * under), in-book search with the flashed hit, footnote popups built from
 * the pristine section document, and the phone bottom bar a plain tap
 * toggles. The chrome itself is the current reader's components.
 */

test.use({ storageState: ADMIN_STATE });
test.setTimeout(60_000);

const chrome = (page: Page) => page.getByTestId("ng-chrome");

/** Activate an element of the rendered section by selector (a synthetic
 *  click bubbles to the document like a real one). */
function clickInSection(page: Page, selector: string) {
  return page.evaluate((sel) => {
    const doc: Document = window.__beepubReaderNG.core.getContents()[0].doc;
    const el = doc.querySelector(sel) as HTMLElement | null;
    if (!el) throw new Error(`no element ${sel} in the section`);
    el.click();
  }, selector);
}

const FLASH_FILL = "#fed7aa"; // HIGHLIGHT_COLORS.orange

async function hasFlash(page: Page) {
  return (await marks(page)).some((g) => g.fill === FLASH_FILL);
}

test("the TOC lists nested entries, jumps to fragments and tracks the page", async ({
  page,
}) => {
  const bookId = await seedFixture(page.request, NOTES_BOOK);
  await openBook(page, bookId, {}, NOTES_BOOK);

  await page.getByRole("button", { name: "Table of Contents" }).click();
  const dialog = page.getByRole("dialog", { name: "Table of Contents" });
  await expect(dialog).toBeVisible();
  // Nested entries render (any depth) under their parent.
  await expect(
    dialog.getByRole("button", { name: "Entry 2 — The Bell Buoy" }),
  ).toBeVisible();
  // Page 1 starts at the part heading, before Entry 1's anchor: the page
  // is under the part, not yet under its first entry.
  await expect(dialog.locator("[data-toc-active]")).toHaveText(
    "Part One: The Ledger",
  );
  await expect(chrome(page)).toContainText("Part One: The Ledger");

  await dialog.getByRole("button", { name: "Entry 2 — The Bell Buoy" }).click();
  await expect(dialog).toBeHidden();
  // A fragment target in the same file: still section 0, past its start.
  await expect
    .poll(async () => (await location(page)).fraction)
    .toBeGreaterThan(0);
  expect((await location(page)).index).toBe(0);
  // One page on, the page start is inside Entry 2 for sure (the anchor
  // may have landed mid-page): the chrome and the TOC both say so.
  await page.evaluate(() => window.__beepubReaderNG.core.next());
  await expect(chrome(page)).toContainText("Entry 2 — The Bell Buoy");
  await page.getByRole("button", { name: "Table of Contents" }).click();
  await expect(dialog.locator("[data-toc-active]")).toHaveText(
    "Entry 2 — The Bell Buoy",
  );

  await dialog.getByRole("button", { name: "Part Two: Notes" }).click();
  await expect.poll(async () => (await location(page)).index).toBe(1);
  await expect(chrome(page)).toContainText("Part Two: Notes");
});

test("search finds text across sections and flashes the chosen hit", async ({
  page,
}) => {
  const bookId = await seedFixture(page.request, NOTES_BOOK);
  await openBook(page, bookId, {}, NOTES_BOOK);

  await page.getByRole("button", { name: "Search in Book" }).click();
  const dialog = page.getByRole("dialog", { name: "Search in Book" });
  const input = dialog.getByRole("textbox");
  await expect(input).toBeFocused();

  // A frequent word: many hits, grouped under their TOC labels.
  await input.fill("lantern");
  await expect(dialog).toContainText(/\d+ results/);
  const count = parseInt(
    ((await dialog.textContent()) ?? "").match(/(\d+) results/)?.[1] ?? "0",
    10,
  );
  expect(count).toBeGreaterThan(10);
  await expect(dialog.getByText("Part One: The Ledger").first()).toBeVisible();

  // A unique word in the second section.
  await input.fill("quillstorm");
  await expect(dialog).toContainText("1 results");
  const hit = dialog.getByRole("button").filter({ hasText: "quillstorm" });
  await expect(hit).toContainText("Part Two: Notes");
  await hit.click();
  await expect(dialog).toBeHidden();
  await expect.poll(async () => (await location(page)).index).toBe(1);
  // The hit is flashed on the highlight layer, then cleared on its own.
  await expect.poll(() => hasFlash(page)).toBe(true);
  await expect.poll(() => hasFlash(page), { timeout: 6_000 }).toBe(false);
  // The section document itself was never touched by the flash.
  const injected = await page.evaluate(() => {
    const doc: Document = window.__beepubReaderNG.core.getContents()[0].doc;
    return doc.querySelectorAll("mark, [data-flash]").length;
  });
  expect(injected).toBe(0);
});

test("search segments CJK text in a vertical book", async ({ page }) => {
  // (Not the short vertical fixture: its cover image outweighs its text,
  // so the server files it as an image book, which has no search.)
  const bookId = await seedFixture(page.request, VERTICAL_LONG_BOOK);
  // The sans stack is the CJK face the e2e hosts have (see reader-ng.spec).
  await openBook(page, bookId, { font: "sans" }, VERTICAL_LONG_BOOK);

  await page.getByRole("button", { name: "Search in Book" }).click();
  const dialog = page.getByRole("dialog", { name: "Search in Book" });
  await dialog.getByRole("textbox").fill("天下");
  await expect(dialog).toContainText(/\d+ results/);
  await expect(
    dialog.getByRole("button").filter({ hasText: "天下" }).first(),
  ).toBeVisible();
});

test("footnote links open a popup, note references across files too, bare markers navigate", async ({
  page,
}) => {
  const bookId = await seedFixture(page.request, NOTES_BOOK);
  await openBook(page, bookId, {}, NOTES_BOOK);
  const popup = page.locator(".footnote-content");

  // A declared note reference whose target lives in another file: the
  // note comes to the reader, the reader stays put.
  await clickInSection(page, "#enref1");
  await expect(popup).toBeVisible();
  await expect(popup).toContainText("oil-fed");
  expect((await location(page)).index).toBe(0);
  await page.keyboard.press("Escape");
  await expect(popup).toBeHidden();

  // A plain cross-file link navigates.
  await clickInSection(page, "#notes-link");
  await expect.poll(async () => (await location(page)).index).toBe(1);

  // A same-file fragment link with a real target: a popup.
  await clickInSection(page, "#fnref1");
  await expect(popup).toBeVisible();
  await expect(popup).toContainText("brown paper");
  // A paging key puts the note away instead of turning under it.
  const before = await location(page);
  await page.keyboard.press("ArrowRight");
  await expect(popup).toBeHidden();
  expect(await location(page)).toEqual(before);

  // The backlink inside the note is a bare marker: it navigates back to
  // the reference, closing the popup.
  await clickInSection(page, "#fnref1");
  await expect(popup).toBeVisible();
  await popup.getByRole("link").click();
  await expect(popup).toBeHidden();
  expect((await location(page)).index).toBe(1);
});

test.describe("phone", () => {
  test.use(iphone);

  test("a plain tap toggles the bottom bar, whose TOC entry opens the sidebar", async ({
    page,
    context,
  }) => {
    const bookId = await seedFixture(page.request, NOTES_BOOK);
    await openBook(page, bookId, {}, NOTES_BOOK);
    const cdp = await context.newCDPSession(page);
    const bar = page.getByRole("toolbar", { name: "Reading controls" });
    await expect(bar).toBeHidden();

    await touchTap(cdp, { x: 195, y: 420 }, 60);
    await expect(bar).toBeVisible();
    await bar.getByRole("button", { name: "Table of Contents" }).click();
    const dialog = page.getByRole("dialog", { name: "Table of Contents" });
    await expect(dialog).toBeVisible();
    // Opening a sidebar folds the bar.
    await expect(bar).toBeHidden();
    await dialog.getByRole("button", { name: "Close" }).click();
    await expect(dialog).toBeHidden();

    await touchTap(cdp, { x: 195, y: 420 }, 60);
    await expect(bar).toBeVisible();
    await touchTap(cdp, { x: 195, y: 420 }, 60);
    await expect(bar).toBeHidden();
  });
});
