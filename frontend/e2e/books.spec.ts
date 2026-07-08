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
  await page.getByRole("button", { name: LIBRARY_NAME }).first().click();

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
