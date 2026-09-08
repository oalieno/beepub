import {
  test,
  expect,
  type APIRequestContext,
  type Page,
} from "@playwright/test";
import { ADMIN_STATE } from "./helpers";
import {
  SIMPLIFIED_TXT_BOOK,
  SIMPLIFIED_TXT_BOOK_2,
  openBook,
  seedFixture,
} from "./ng-helpers";

/**
 * Simplified-to-Traditional conversion of TXT uploads: a per-user
 * preference converts Simplified Chinese TXT files at ingest, and a TXT
 * book uploaded unconverted can be rebuilt from its source later.
 */

test.use({ storageState: ADMIN_STATE });
test.setTimeout(60_000);

function sectionText(page: Page) {
  return page.evaluate(
    () =>
      (window.__beepubReaderNG.core.getContents()[0].doc as Document).body
        ?.textContent ?? "",
  );
}

async function setPreference(
  request: APIRequestContext,
  mode: "s2tw" | "s2twp" | null,
) {
  const res = await request.put("/api/auth/preferences", {
    data: { upload_zh_conversion: mode },
  });
  expect(res.ok()).toBeTruthy();
}

test.afterEach(async ({ request }) => {
  await setPreference(request, null);
});

test("the profile switch converts a Simplified TXT at upload", async ({
  page,
}) => {
  await page.goto("/profile");
  await page.getByRole("button", { name: "Simplified to Traditional" }).click();
  const chars = page.getByRole("switch", {
    name: "Convert Simplified Chinese TXT uploads to Traditional",
  });
  const phrases = page.getByRole("switch", {
    name: "Also convert Mainland phrases to Taiwan usage",
  });
  await expect(phrases).toBeDisabled();
  await chars.click();
  await expect(phrases).toBeEnabled();
  await phrases.click();
  await expect
    .poll(
      async () =>
        (await (await page.request.get("/api/auth/me")).json())
          .upload_zh_conversion,
    )
    .toBe("s2twp");

  const bookId = await seedFixture(page.request, SIMPLIFIED_TXT_BOOK);
  const book = await (await page.request.get(`/api/books/${bookId}`)).json();
  expect(book.epub_language).toBe("zh-TW");
  expect(book.epub_title).toBe("霧港夜航");
  expect(book.epub_authors).toEqual(["陳默"]);

  await openBook(page, bookId, {}, SIMPLIFIED_TXT_BOOK);
  // The synopsis opens the book; chapter one is the next section.
  expect(await sectionText(page)).toContain("沒有燈的船在霧裡等潮");
  await page.evaluate(() => window.__beepubReaderNG.core.goTo(1));
  await expect.poll(() => sectionText(page)).toContain("纜繩解開的時候");
  // Phrase mode: 软件工程师 → 軟體工程師.
  expect(await sectionText(page)).toContain("軟體工程師");
  expect(await sectionText(page)).not.toContain("缆绳");
});

test("a TXT book uploaded unconverted is rebuilt from the detail page", async ({
  page,
}) => {
  const bookId = await seedFixture(page.request, SIMPLIFIED_TXT_BOOK_2);
  const before = await (await page.request.get(`/api/books/${bookId}`)).json();
  expect(before.epub_language).toBe("zh-CN");

  await page.goto(`/books/${bookId}`);
  await page.getByTitle("More actions").click();
  await page
    .getByRole("menuitem", { name: "Convert to Traditional Chinese" })
    .click();
  await expect(
    page.getByText("Converted to Traditional Chinese"),
  ).toBeVisible();

  const after = await (await page.request.get(`/api/books/${bookId}`)).json();
  expect(after.epub_language).toBe("zh-TW");
  expect(after.epub_title).toBe("燈塔守夜人");
  // The action is gone once the book is Traditional.
  await page.getByTitle("More actions").click();
  await expect(
    page.getByRole("menuitem", { name: "Convert to Traditional Chinese" }),
  ).toHaveCount(0);

  // Leave no converted copy behind: the next run seeds the Simplified one.
  await page.request.delete(`/api/books/${bookId}`);
});
