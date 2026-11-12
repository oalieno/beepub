import {
  test,
  expect,
  type APIRequestContext,
  type Page,
} from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { ADMIN_STATE } from "./helpers";
import { ANCHOR_BOOK, FIXTURES } from "./ng-helpers";

/**
 * The library table: rows load as the page scrolls (both ways), a click
 * picks a row instead of opening it, a new order keeps the picked book in
 * view, and the side panel edits or deletes several books at once.
 *
 * The scrolling tests serve a made-up list of 150 books through
 * page.route — the e2e library is far smaller than a page of 60. The
 * batch tests use real books in a library of their own.
 */

test.use({ storageState: ADMIN_STATE });

const SHELF = "Batch Edit Shelf";

async function shelfId(request: APIRequestContext): Promise<string> {
  const libraries = await (await request.get("/api/libraries")).json();
  const found = libraries.find((l: { name: string }) => l.name === SHELF);
  if (found) return found.id;
  const created = await request.post("/api/libraries", {
    data: { name: SHELF },
  });
  expect(created.ok()).toBeTruthy();
  return (await created.json()).id;
}

const COUNT = 150;
const pad = (n: number) => String(n).padStart(3, "0");
const bookId = (n: number) =>
  `00000000-0000-4000-8000-${pad(n).padStart(12, "0")}`;

function fakeBook(n: number) {
  const day = new Date(Date.UTC(2026, 0, 1) + n * 86_400_000).toISOString();
  return {
    id: bookId(n),
    title: null,
    epub_title: `卷 ${pad(n)}`,
    display_title: `卷 ${pad(n)}`,
    authors: null,
    epub_authors: ["虛構作者"],
    display_authors: ["虛構作者"],
    publisher: null,
    epub_publisher: null,
    series: null,
    series_index: null,
    epub_series: null,
    epub_series_index: null,
    display_series: null,
    display_series_index: null,
    display_tags: null,
    format: "epub",
    file_size: 1024 * 1024,
    cover_path: null,
    calibre_id: null,
    calibre_added_at: null,
    created_at: day,
    updated_at: day,
    reading_status: null,
    reading_percentage: null,
  };
}

/** The made-up list, paged and ordered as the server would, `around` too. */
async function serveFakeList(page: Page, libraryId: string) {
  const all = Array.from({ length: COUNT }, (_, i) => fakeBook(i + 1));
  await page.route(/\/api\/books\?/, (route) => {
    const url = new URL(route.request().url());
    if (url.searchParams.get("library") !== libraryId) return route.fallback();
    const sort = url.searchParams.get("sort");
    const order = url.searchParams.get("order");
    const list =
      sort === "display_title"
        ? [...all].sort((a, b) =>
            a.display_title.localeCompare(b.display_title),
          )
        : [...all].sort((a, b) => b.created_at.localeCompare(a.created_at));
    if (order === (sort === "display_title" ? "desc" : "asc")) list.reverse();
    const limit = Number(url.searchParams.get("limit") ?? 60);
    let offset = Number(url.searchParams.get("offset") ?? 0);
    let around_index: number | null = null;
    const around = url.searchParams.get("around");
    if (around) {
      const i = list.findIndex((b) => b.id === around);
      if (i >= 0) {
        around_index = i;
        offset = Math.max(0, i - 20);
      }
    }
    return route.fulfill({
      json: {
        items: list.slice(offset, offset + limit),
        total: list.length,
        offset,
        around_index,
      },
    });
  });
}

async function openShelf(
  page: Page,
  libraryId: string,
  view: "table" | "grid",
) {
  // Set before arriving: a reload would restore the page's snapshot.
  await page.goto("/libraries");
  await page.evaluate((v) => localStorage.setItem("library-view", v), view);
  await page.goto(`/libraries/${libraryId}`);
}

const rows = (page: Page) => page.locator("tr[data-book-row]");
// The table scrolls in its own pane; the page around it does not.
const pane = (page: Page) => page.getByTestId("table-pane");
const toPaneEnd = (page: Page) =>
  pane(page).evaluate((el) => (el.scrollTop = el.scrollHeight));
const row = (page: Page, n: number) =>
  page.locator(`tr[data-book-row="${bookId(n)}"]`);

test("rows load as the page scrolls, in the table and the grid", async ({
  page,
}) => {
  const libraryId = await shelfId(page.request);
  await serveFakeList(page, libraryId);
  await openShelf(page, libraryId, "table");
  await expect(rows(page)).toHaveCount(60);
  await expect(page.getByRole("button", { name: "Load more" })).toHaveCount(0);

  await toPaneEnd(page);
  await expect(rows(page)).toHaveCount(120);
  // Left there, with the edge still on screen: one load, then it waits for
  // the next scroll (the edge must not drag the page down after it).
  await page.waitForTimeout(1500);
  await expect(rows(page)).toHaveCount(120);
  await toPaneEnd(page);
  await expect(rows(page)).toHaveCount(COUNT);
  await expect(page.getByText("Loading...")).toHaveCount(0);

  await openShelf(page, libraryId, "grid");
  const cards = page.locator(".book-grid > *");
  await expect(cards).toHaveCount(60);
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await expect(cards).toHaveCount(120);
});

test("a click picks a row, and a new order keeps it in view", async ({
  page,
}) => {
  const libraryId = await shelfId(page.request);
  await serveFakeList(page, libraryId);
  await openShelf(page, libraryId, "table");

  // Newest first: 卷 140 is on the first page. Clicking its row (not the
  // title) picks it and opens the panel — the page stays.
  await row(page, 140).locator("td").nth(1).click();
  await expect(row(page, 140)).toHaveAttribute("aria-selected", "true");
  await expect(page).toHaveURL(new RegExp(`/libraries/${libraryId}`));
  const panel = page.getByTestId("selection-panel");
  await expect(panel.getByRole("heading", { name: "卷 140" })).toBeVisible();

  // Rows not picked keep their ↗ out of sight until hovered.
  await expect(row(page, 139).getByRole("link", { name: "Open" })).toHaveCSS(
    "opacity",
    "0",
  );

  // Each row has a ⋯ menu, shown on hover; opening it picks nothing.
  const menu = row(page, 139).getByRole("button", { name: "More actions" });
  await expect(menu).toHaveCSS("opacity", "0");
  await row(page, 139).hover();
  await expect(menu).toHaveCSS("opacity", "1");
  await menu.click();
  await expect(page.getByRole("menuitem", { name: "Open" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(row(page, 140)).toHaveAttribute("aria-selected", "true");
  await expect(row(page, 139)).toHaveAttribute("aria-selected", "false");

  // By title, 卷 140 is the 140th: the list opens around it, still picked,
  // and the rows above it load in without moving it. The header stays on
  // screen, so the order changes from down the list too.
  await pane(page).evaluate((el) => el.scrollBy(0, 1200));
  const header = page.getByRole("button", { name: "Title", exact: true });
  await expect(header).toBeInViewport();
  await header.click();
  await expect(row(page, 140)).toHaveAttribute("aria-selected", "true");
  await expect(row(page, 119)).toHaveCount(0);
  const fromThird = () =>
    row(page, 140).evaluate((el) => {
      const box = el.closest("[data-testid=table-pane]")!;
      const top = box.getBoundingClientRect().top;
      return el.getBoundingClientRect().top - top - box.clientHeight / 3;
    });
  // About a third of the way down the screen.
  await expect.poll(async () => Math.abs(await fromThird())).toBeLessThan(12);

  // Scrolling up reaches the top edge: the 60 before load in above, and
  // the row stays where it was on the screen.
  await pane(page).evaluate((el) => el.scrollBy(0, -400));
  const before = await fromThird();
  await expect(row(page, 60)).toBeAttached();
  await expect(row(page, 1)).toHaveCount(0);
  expect(Math.abs((await fromThird()) - before)).toBeLessThan(2);

  // Shift+click takes the run; Escape lets go of all of it.
  await row(page, 145)
    .locator("td")
    .nth(1)
    .click({ modifiers: ["Shift"] });
  await expect(page.getByText("6 selected").first()).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator('tr[aria-selected="true"]')).toHaveCount(0);
  await expect(panel).toHaveCount(0);

  // A double-click edits the cell it lands on; Escape backs out.
  await row(page, 141).locator("td").nth(1).dblclick();
  const authors = row(page, 141).getByLabel("Authors");
  await expect(authors).toBeFocused();
  await authors.press("Escape");
  await expect(authors).toHaveCount(0);
  await expect(row(page, 141)).toHaveAttribute("aria-selected", "true");
  // Enter opens the picked book, as in Calibre.
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(`/books/${bookId(141)}`);
});

test("back from a book, the table is where it was, the row still picked", async ({
  page,
}) => {
  const libraryId = await shelfId(page.request);
  await serveFakeList(page, libraryId);
  await openShelf(page, libraryId, "table");
  await pane(page).evaluate((el) => el.scrollBy(0, 900));
  await row(page, 120).locator("td").nth(1).click();
  const before = await pane(page).evaluate((el) => el.scrollTop);
  expect(before).toBeGreaterThan(800);

  // The picked row shows its ↗, the way into the book.
  await row(page, 120).getByRole("link", { name: "Open" }).click();
  await expect(page).toHaveURL(`/books/${bookId(120)}`);
  await page.goBack();
  await expect(row(page, 120)).toHaveAttribute("aria-selected", "true");
  await expect
    .poll(() => pane(page).evaluate((el) => el.scrollTop))
    .toBe(before);
  await expect(
    page
      .getByTestId("selection-panel")
      .getByRole("heading", { name: "卷 120" }),
  ).toBeVisible();
});

test.describe("batch", () => {
  const created: string[] = [];

  test.afterEach(async ({ request }) => {
    for (const id of created.splice(0))
      await request.delete(`/api/books/${id}`);
  });

  async function seed(request: APIRequestContext, libraryId: string) {
    // The e2e database persists: clear what an earlier run left.
    const params = new URLSearchParams({ library: libraryId, limit: "200" });
    const left = await (await request.get(`/api/books?${params}`)).json();
    for (const book of left.items)
      await request.delete(`/api/books/${book.id}`);
    const ids: string[] = [];
    for (const title of ["燈下書簡 1", "燈下書簡 2", "燈下書簡 3"]) {
      const response = await request.post("/api/books/physical", {
        data: { library_id: libraryId, title, publisher: "潮聲書房" },
      });
      expect(response.ok()).toBeTruthy();
      ids.push((await response.json()).id);
    }
    created.push(...ids);
    return ids;
  }

  test("several books get a series, numbered from their titles", async ({
    page,
  }) => {
    const libraryId = await shelfId(page.request);
    const ids = await seed(page.request, libraryId);
    await openShelf(page, libraryId, "table");
    await page.getByRole("button", { name: "Title", exact: true }).click();
    await expect(rows(page)).toHaveCount(3);

    const byTitle = (title: string) =>
      page.locator("tr[data-book-row]", { hasText: title });
    await byTitle("燈下書簡 1").locator("td").nth(1).click();
    await byTitle("燈下書簡 3")
      .locator("td")
      .nth(1)
      .click({
        modifiers: ["Shift"],
      });
    const panel = page.getByTestId("selection-panel");
    await expect(
      panel.getByRole("heading", { name: "3 selected" }),
    ).toBeVisible();
    // They share a publisher, so it shows; the series field starts empty.
    await expect(panel.getByLabel("Publisher")).toHaveValue("潮聲書房");

    await panel.getByLabel("Series").fill("燈下書簡");
    await expect(panel.getByText("Will change")).toBeVisible();
    await expect(
      panel.getByTestId("numbering-preview").locator("li"),
    ).toHaveText([/^1\s*燈下書簡 1$/, /^2\s*燈下書簡 2$/, /^3\s*燈下書簡 3$/]);
    // Changes not applied hold the order where it is.
    await expect(
      page.getByRole("button", { name: "Title", exact: true }),
    ).toBeDisabled();

    await panel.getByRole("button", { name: "Apply to 3" }).click();
    await expect(panel.getByText("Updated 3")).toBeVisible();
    await expect(byTitle("燈下書簡 2")).toContainText("燈下書簡 #2");
    for (const [i, id] of ids.entries()) {
      const book = await (await page.request.get(`/api/books/${id}`)).json();
      expect(book.display_series).toBe("燈下書簡");
      expect(book.display_series_index).toBe(i + 1);
    }

    // And they go together, after a second, explicit yes.
    await panel.getByRole("button", { name: "Delete 3…" }).click();
    await panel.getByRole("button", { name: "Delete 3", exact: true }).click();
    await expect(rows(page)).toHaveCount(0);
    for (const id of ids) {
      expect((await page.request.get(`/api/books/${id}`)).status()).toBe(404);
    }
    created.splice(0);
  });
});

test.describe("in place", () => {
  test("a row edits in place, from F2 or its ⋯ menu", async ({ page }) => {
    const libraryId = await shelfId(page.request);
    const params = new URLSearchParams({ library: libraryId, limit: "200" });
    const left = await (await page.request.get(`/api/books?${params}`)).json();
    for (const book of left.items)
      await page.request.delete(`/api/books/${book.id}`);
    const created = await page.request.post("/api/books/physical", {
      data: { library_id: libraryId, title: "從零開始的小咒語！ 1" },
    });
    const id = (await created.json()).id;
    try {
      await openShelf(page, libraryId, "table");
      await rows(page).first().locator("td").nth(1).click();
      const title = rows(page).first().getByLabel("Title");

      // F2 on the picked row: its title becomes a field, the caret at the end.
      await page.keyboard.press("F2");
      await expect(title).toBeFocused();
      await title.press("Backspace");
      await title.press("Backspace");
      await title.pressSequentially("1");
      await title.press("Enter");
      await expect(title).toHaveCount(0);
      await expect(rows(page).first()).toContainText("從零開始的小咒語！1");
      let book = await (await page.request.get(`/api/books/${id}`)).json();
      expect(book.display_title).toBe("從零開始的小咒語！1");
      expect(book.field_sources).toEqual({ title: "manual" });

      // The reading status is a field of the row too.
      await page.keyboard.press("F2");
      await rows(page).first().getByLabel("Status").click();
      await page.getByRole("option", { name: "Want to Read" }).click();
      await rows(page).first().getByLabel("Title").press("Enter");
      await expect(title).toHaveCount(0);
      await expect(rows(page).first()).toContainText("Want to Read");

      // The same from the row's ⋯ menu; Escape backs out, nothing saved.
      await rows(page)
        .first()
        .getByRole("button", { name: "More actions" })
        .click();
      await page.getByRole("menuitem", { name: "Edit in place" }).click();
      await expect(title).toBeFocused();
      await title.pressSequentially("X");
      await page.keyboard.press("Escape");
      await expect(title).toHaveCount(0);
      book = await (await page.request.get(`/api/books/${id}`)).json();
      expect(book.display_title).toBe("從零開始的小咒語！1");

      // And it goes from its row's ⋯ menu, after a yes.
      await rows(page)
        .first()
        .getByRole("button", { name: "More actions" })
        .click();
      await page.getByRole("menuitem", { name: "Delete book" }).click();
      await page.getByRole("button", { name: "Delete", exact: true }).click();
      await expect(rows(page)).toHaveCount(0);
      expect((await page.request.get(`/api/books/${id}`)).status()).toBe(404);
    } finally {
      await page.request.delete(`/api/books/${id}`);
    }
  });
});

test("a row's ⋯ menu has the book page's actions", async ({ page }) => {
  const libraryId = await shelfId(page.request);
  const created = await page.request.post("/api/books/physical", {
    data: { library_id: libraryId, title: "Row Menu Almanac" },
  });
  const id = (await created.json()).id;
  const shelf = await (
    await page.request.post("/api/bookshelves", {
      data: { name: "Row Menu Shelf" },
    })
  ).json();
  try {
    await openShelf(page, libraryId, "table");
    const row = page.locator(`tr[data-book-row="${id}"]`);
    const menu = row.getByRole("button", { name: "More actions" });

    // The table's own items first, then the book page's.
    await menu.click();
    for (const name of [
      "Open",
      "Edit in place",
      "Add to favorites",
      "Add to shelf",
      "Notes",
      "Report issue",
      "Edit metadata",
      "Move to library",
      "Link to Another Book",
      "Delete book",
    ])
      await expect(page.getByRole("menuitem", { name })).toBeVisible();
    // A favourite from the row: the row knows it, the menu then offers
    // the other way. Opening the menu picks nothing.
    await page.getByRole("menuitem", { name: "Add to favorites" }).click();
    await expect
      .poll(
        async () =>
          (
            await (
              await page.request.get(`/api/books/${id}/interaction`)
            ).json()
          ).is_favorite,
      )
      .toBe(true);
    await menu.click();
    await expect(
      page.getByRole("menuitem", { name: "Remove from favorites" }),
    ).toBeVisible();
    await expect(row).toHaveAttribute("aria-selected", "false");

    // The shelf picker outlives the menu that opened it.
    await page.getByRole("menuitem", { name: "Add to shelf" }).click();
    const picker = page.getByRole("dialog", { name: "Add to Bookshelf" });
    await picker.getByRole("button", { name: "Row Menu Shelf" }).click();
    await expect(picker).toHaveCount(0);
    const items = await (
      await page.request.get(`/api/bookshelves/${shelf.id}/items`)
    ).json();
    expect(items.map((i: { book?: { id: string } }) => i.book?.id)).toEqual([
      id,
    ]);

    // Notes: the book's page, its editor open.
    await menu.click();
    await page.getByRole("menuitem", { name: "Notes" }).click();
    await expect(page).toHaveURL(new RegExp(`/books/${id}#notes$`));
    await expect(
      page.getByPlaceholder("Write your notes here..."),
    ).toBeFocused();
  } finally {
    await page.request.delete(`/api/bookshelves/${shelf.id}`);
    await page.request.delete(`/api/books/${id}`);
  }
});

test("the edit page opens on the book's own values, to edit in place", async ({
  page,
}) => {
  const libraryId = await shelfId(page.request);
  const uploaded = await page.request.post("/api/books", {
    multipart: {
      file: {
        name: "edit-in-place.epub",
        mimeType: "application/epub+zip",
        buffer: fs.readFileSync(path.join(FIXTURES, ANCHOR_BOOK.file)),
      },
      library_id: libraryId,
    },
  });
  expect(uploaded.ok()).toBeTruthy();
  const id = (await uploaded.json()).id;
  try {
    await page.goto(`/books/${id}/edit`);
    const title = page.locator("#edit-title");
    // The file's title is there to shorten, not only a placeholder.
    await expect(title).toHaveValue(ANCHOR_BOOK.title);
    await title.press("End");
    for (let i = 0; i < " Ledger".length; i++) await title.press("Backspace");
    await page.getByRole("button", { name: "Save" }).click();
    await expect(page).toHaveURL(`/books/${id}`);

    let book = await (await page.request.get(`/api/books/${id}`)).json();
    expect(book.title).toBe("Anchor Drift");
    expect(book.field_sources).toEqual({ title: "manual" });
    // Fields left as they were stay the book's own.
    expect(book.authors).toBeNull();

    // Emptied, it goes back to the file's.
    await page.goto(`/books/${id}/edit`);
    await expect(title).toHaveValue("Anchor Drift");
    await title.fill("");
    await expect(title).toHaveAttribute("placeholder", ANCHOR_BOOK.title);
    await page.getByRole("button", { name: "Save" }).click();
    await expect(page).toHaveURL(`/books/${id}`);
    book = await (await page.request.get(`/api/books/${id}`)).json();
    expect(book.title).toBeNull();
    expect(book.display_title).toBe(ANCHOR_BOOK.title);
  } finally {
    await page.request.delete(`/api/books/${id}`);
  }
});
