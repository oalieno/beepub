import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test, expect } from "@playwright/test";
import { ADMIN_STATE, LIBRARY_NAME } from "./helpers";

const FIXTURE = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  "fixtures",
  "e2e-test-book.epub",
);

test.use({ storageState: ADMIN_STATE });

test("upload a book, open it, and read it", async ({ page }) => {
  await page.goto("/libraries");
  await page.getByRole("link", { name: LIBRARY_NAME }).first().click();
  await expect(page).toHaveURL(/\/libraries\/[0-9a-f-]+$/);

  await page.getByRole("button", { name: "Add books" }).first().click();
  await page.getByRole("menuitem", { name: "Upload Books" }).click();
  await page.locator('input[type="file"]').setInputFiles(FIXTURE);
  // Files are listed before anything is sent: a chance to catch a wrong one.
  await expect(page.getByRole("dialog").getByText(/\.epub$/)).toBeVisible();
  await page.getByRole("button", { name: "Upload 1 file(s)" }).click();
  await expect(page.getByText("Uploaded 1 book(s)")).toBeVisible({
    timeout: 15_000,
  });

  await page.getByText("E2E Test Book").first().click();
  await expect(page).toHaveURL(/\/books\/[0-9a-f-]+$/);
  await expect(page.getByText("E2E Author").first()).toBeVisible();

  await page
    .getByRole("button", { name: /Start Reading|Continue Reading/ })
    .click();
  await expect(page).toHaveURL(/\/read$/);

  // The chapter renders inside the reader's iframe, which lives in a
  // closed shadow root: read its text through the debug handle.
  await expect
    .poll(
      () =>
        page.evaluate(() => {
          const doc: Document | undefined =
            window.__beepubReaderNG?.core?.getContents()[0]?.doc;
          return (
            doc?.body?.textContent?.includes("The starship librarian") ?? false
          );
        }),
      { timeout: 30_000 },
    )
    .toBe(true);
});

test("add a physical book and find it via the format filter", async ({
  page,
}) => {
  await page.goto("/libraries");
  await page.getByRole("link", { name: LIBRARY_NAME }).first().click();
  await expect(page).toHaveURL(/\/libraries\/[0-9a-f-]+$/);

  await page.getByRole("button", { name: "Add books" }).first().click();
  await page.getByRole("menuitem", { name: "Add a physical book" }).click();
  await page.locator("#physical-title").fill("Bound Paper Copy E2E");
  await page.locator("#physical-authors").fill("Shelf Author");
  await page.getByRole("button", { name: "Add a physical book" }).click();
  await expect(page.getByText("Physical book added")).toBeVisible();

  await page.getByText("Bound Paper Copy E2E").first().click();
  await expect(page).toHaveURL(/\/books\/[0-9a-f-]+$/);
  await expect(page.getByText("Physical book").first()).toBeVisible();
  // No cover file, so the generated cover stands in. This title hashes
  // above 2^31, where a signed shift once left the pattern unpainted.
  await expect
    .poll(() =>
      page
        .locator(".book-shadow")
        .first()
        .evaluate((el) => {
          const cs = getComputedStyle(el);
          return (
            cs.backgroundImage !== "none" ||
            cs.backgroundColor !== "rgba(0, 0, 0, 0)"
          );
        }),
    )
    .toBe(true);
  // No reader and no download for a paper copy.
  await expect(
    page.getByRole("button", { name: /Start Reading|Continue Reading/ }),
  ).toHaveCount(0);

  // The chip filters the library down to physical books.
  await page.getByRole("button", { name: "Physical book" }).first().click();
  await expect(page).toHaveURL(/\/libraries\/[0-9a-f-]+\?format=physical/);
  await expect(page.getByText("Bound Paper Copy E2E").first()).toBeVisible();
  await expect(page.getByText("E2E Test Book")).toHaveCount(0);
});

test("admin moves a book to another library", async ({ page }) => {
  // Prepare a target library and a dedicated book through the API.
  const libraries: { id: string; name: string }[] = await (
    await page.request.get("/api/libraries")
  ).json();
  let target = libraries.find((l) => l.name === "E2E Target Library");
  if (!target) {
    target = await (
      await page.request.post("/api/libraries", {
        data: { name: "E2E Target Library" },
      })
    ).json();
  }
  const uploaded = await page.request.post("/api/books", {
    multipart: {
      file: {
        name: "movable.epub",
        mimeType: "application/epub+zip",
        buffer: fs.readFileSync(FIXTURE),
      },
      library_id: libraries.find((l) => l.name === LIBRARY_NAME)!.id,
    },
  });
  expect(uploaded.ok()).toBeTruthy();
  const book = await uploaded.json();

  await page.goto(`/books/${book.id}`);
  await page
    .getByRole("button", { name: "More actions" })
    .filter({ visible: true })
    .click();
  await page.getByRole("menuitem", { name: "Move to library" }).click();
  await page.getByRole("button", { name: "E2E Target Library" }).click();
  await expect(page.getByText("Book moved")).toBeVisible();

  const listing = await (
    await page.request.get(`/api/libraries/${target!.id}/books`)
  ).json();
  expect(listing.items.map((b: { id: string }) => b.id)).toContain(book.id);
});

test("the back button works while a book is still loading", async ({
  page,
}) => {
  // A book request that never answers: the skeleton stays up.
  await page.route(/\/api\/books\/[0-9a-f-]+$/, () => {});
  await page.goto("/books/00000000-0000-4000-8000-000000000000");
  await expect(page.getByRole("status", { name: "Loading" })).toBeVisible();
  const back = page.getByRole("link", { name: "Back" });
  await expect(back).toBeVisible();
  await back.click();
  await expect(page).not.toHaveURL(/\/books\//);
});
