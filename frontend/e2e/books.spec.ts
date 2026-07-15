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

  await page.getByRole("button", { name: "Upload Books" }).click();
  await page.locator('input[type="file"]').setInputFiles(FIXTURE);
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

  // The chapter renders inside the epub.js iframe.
  await expect(
    page
      .frameLocator("iframe")
      .first()
      .getByText("The starship librarian")
      .first(),
  ).toBeVisible({ timeout: 30_000 });
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
