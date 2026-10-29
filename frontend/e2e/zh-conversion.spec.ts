import {
  test,
  expect,
  type APIRequestContext,
  type Page,
} from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { ADMIN_STATE, LIBRARY_NAME, transferPanel } from "./helpers";
import {
  FIXTURES,
  SIMPLIFIED_TXT_BOOK,
  SIMPLIFIED_TXT_BOOK_2,
  openBook,
} from "./ng-helpers";

/**
 * Simplified-to-Traditional conversion. Never done unasked: an upload
 * that brings Simplified books ends with a question, every time; a book
 * already in the library is converted from its page, its highlights
 * carried along.
 */

test.use({ storageState: ADMIN_STATE });
test.setTimeout(90_000);

function sectionText(page: Page) {
  return page.evaluate(
    () =>
      (window.__beepubReaderNG.core.getContents()[0].doc as Document).body
        ?.textContent ?? "",
  );
}

async function libraryId(request: APIRequestContext): Promise<string> {
  const libraries = await (await request.get("/api/libraries")).json();
  return libraries.find((l: { name: string }) => l.name === LIBRARY_NAME).id;
}

/** This run's books, gone again afterwards: the e2e database persists. */
const created: string[] = [];

async function newestBook(request: APIRequestContext, title: string) {
  const params = new URLSearchParams({
    library: await libraryId(request),
    search: title,
    sort: "created_at",
    order: "desc",
    limit: "1",
  });
  const books = await (await request.get(`/api/books?${params}`)).json();
  const book = books.items[0];
  created.push(book.id);
  return book;
}

async function uploadThroughDialog(page: Page, ...files: string[]) {
  await page.goto("/libraries");
  await page.getByRole("link", { name: LIBRARY_NAME }).first().click();
  await expect(page).toHaveURL(/\/libraries\/[0-9a-f-]+$/);
  await page.getByRole("button", { name: "Add books" }).first().click();
  await page.getByRole("menuitem", { name: "Upload Books" }).click();
  await page
    .locator('input[type="file"]')
    .setInputFiles(files.map((file) => path.join(FIXTURES, file)));
  await page
    .getByRole("button", { name: `Upload ${files.length} file(s)` })
    .click();
}

test.afterEach(async ({ request }) => {
  for (const id of created.splice(0)) await request.delete(`/api/books/${id}`);
});

test("an upload with Simplified books asks once, then converts them", async ({
  page,
}) => {
  await uploadThroughDialog(
    page,
    SIMPLIFIED_TXT_BOOK.file,
    SIMPLIFIED_TXT_BOOK_2.file,
  );
  // The upload dialog no longer carries a conversion switch: it asks after,
  // once for the batch.
  const prompt = page.getByRole("dialog", {
    name: "Convert to Traditional Chinese?",
  });
  await expect(prompt).toBeVisible({ timeout: 15_000 });
  await expect(
    prompt.getByText(
      "“雾港夜航” and the others just uploaded — 2 books — read as Simplified Chinese.",
    ),
  ).toBeVisible();

  // Either book can be previewed; only rewritten wording is marked.
  const after = prompt.getByTestId("zh-preview-after");
  await expect(after).toContainText("軟件工程師");
  await prompt.getByRole("switch", { name: /Also use Taiwan wording/ }).click();
  await expect(after).toContainText("軟體工程師");
  await expect(after.locator(".zh-mark")).toHaveText(["軟體"]);
  await prompt.getByRole("button", { name: "Book to preview" }).click();
  await page.getByRole("option", { name: "灯塔守夜人" }).click();
  await expect(after).toHaveText("守夜人把網路斷了，只留一盞燈。");

  await prompt.getByRole("button", { name: "Convert 2" }).click();
  await expect(prompt).toHaveCount(0);
  await expect(
    transferPanel(page).getByText("Converted to Traditional", { exact: true }),
  ).toHaveCount(2, { timeout: 15_000 });
  expect((await newestBook(page.request, "燈塔守夜人")).epub_language).toBe(
    "zh-TW",
  );
  const book = await newestBook(page.request, "霧港夜航");
  expect(book.epub_language).toBe("zh-TW");
  expect(book.epub_authors).toEqual(["陳默"]);
  await openBook(page, book.id, {}, SIMPLIFIED_TXT_BOOK);
  expect(await sectionText(page)).toContain("沒有燈的船在霧裡等潮");
  await page.evaluate(() => window.__beepubReaderNG.core.goTo(1));
  await expect.poll(() => sectionText(page)).toContain("纜繩解開的時候");
  // Phrase mode: 软件工程师 → 軟體工程師.
  expect(await sectionText(page)).toContain("軟體工程師");
});

test("declining leaves the book as it is, and the next upload asks again", async ({
  page,
}) => {
  const prompt = page.getByRole("dialog", {
    name: "Convert to Traditional Chinese?",
  });
  for (const round of [1, 2]) {
    await uploadThroughDialog(page, SIMPLIFIED_TXT_BOOK_2.file);
    await expect(prompt).toBeVisible({ timeout: 15_000 });
    // Nothing offers to skip the question from now on.
    await expect(prompt.getByRole("checkbox")).toHaveCount(0);
    await prompt.getByRole("button", { name: "Cancel" }).click();
    await expect(prompt).toHaveCount(0);
    const book = await newestBook(page.request, "灯塔守夜人");
    expect(book.epub_language, `round ${round}`).toBe("zh-CN");
  }
  // And settings carry no conversion setting.
  await page.goto("/profile");
  await expect(
    page.getByRole("button", { name: /Simplified to Traditional/ }),
  ).toHaveCount(0);
});

test("a book is converted from its page, its highlights carried along", async ({
  page,
}) => {
  const uploaded = await page.request.post("/api/books", {
    multipart: {
      file: {
        name: SIMPLIFIED_TXT_BOOK_2.file,
        mimeType: "text/plain",
        buffer: fs.readFileSync(
          path.join(FIXTURES, SIMPLIFIED_TXT_BOOK_2.file),
        ),
      },
      library_id: await libraryId(page.request),
    },
  });
  expect(uploaded.ok()).toBeTruthy();
  const bookId = (await uploaded.json()).id;
  created.push(bookId);

  // A highlight that starts halfway into 网络. Alone, 络 would become 絡;
  // in the book, 网络 becomes 網路 — the quote must read 路. Its anchor
  // is stale on purpose: the reader re-finds it by the converted quote.
  const stale = "epubcfi(/6/2!/4/2,/1:0,/1:1)";
  const highlight = await (
    await page.request.post(`/api/books/${bookId}/highlights`, {
      data: {
        cfi_range: stale,
        text: "络断了",
        prefix: "守夜人把网",
        suffix: "，只留一盏灯。",
        color: "yellow",
      },
    })
  ).json();

  await page.goto(`/books/${bookId}`);
  await page.getByTitle("More actions").click();
  await page
    .getByRole("menuitem", { name: "Convert to Traditional Chinese" })
    .click();
  const dialog = page.getByRole("dialog", {
    name: "Convert to Traditional Chinese",
  });
  await expect(dialog.getByText("Highlights in this book: 1.")).toBeVisible();
  // The sample is a sentence the wording option changes, so the switch
  // shows its effect: 网络 is 網絡 by character, 網路 by wording.
  const after = dialog.getByTestId("zh-preview-after");
  await expect(after).toHaveText("守夜人把網絡斷了，只留一盞燈。");
  await expect(dialog.getByRole("button", { name: "Cancel" })).toBeVisible();
  await dialog.getByRole("switch", { name: /Also use Taiwan wording/ }).click();
  await expect(after).toHaveText("守夜人把網路斷了，只留一盞燈。");
  await expect(dialog.getByText("Marked: wording changed")).toBeVisible();
  await dialog.getByRole("button", { name: "Convert" }).click();
  await expect(page.getByText("Converted to Traditional Chinese")).toBeVisible({
    timeout: 15_000,
  });

  const book = await (await page.request.get(`/api/books/${bookId}`)).json();
  expect(book.epub_language).toBe("zh-TW");
  const rows = await (
    await page.request.get(`/api/books/${bookId}/highlights`)
  ).json();
  const row = rows.find((h: { id: string }) => h.id === highlight.id);
  expect(row.text).toBe("路斷了");
  expect(row.prefix.endsWith("守夜人把網")).toBe(true);
  // Once Traditional, the action is gone.
  await page.getByTitle("More actions").click();
  await expect(
    page.getByRole("menuitem", { name: "Convert to Traditional Chinese" }),
  ).toHaveCount(0);
  await page.keyboard.press("Escape");

  // The reader re-anchors it on the converted text.
  await openBook(
    page,
    bookId,
    {},
    { ...SIMPLIFIED_TXT_BOOK_2, readyText: "守夜人" },
  );
  await expect
    .poll(
      async () =>
        (
          await (
            await page.request.get(`/api/books/${bookId}/highlights`)
          ).json()
        ).find((h: { id: string }) => h.id === highlight.id)?.cfi_range,
      { timeout: 15_000 },
    )
    .not.toBe(stale);
});
