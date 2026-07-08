import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test, expect } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";

const FIXTURE = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  "fixtures",
  "e2e-vertical-book.epub",
);

test.use({ storageState: ADMIN_STATE });

// Correct vertical-rl (直排) rendering is the reason this reader exists —
// regressions here must fail CI, not wait for a bug report.
test("vertical book renders vertical-rl in the reader", async ({ page }) => {
  // Seed through the API (page.request shares the session cookie).
  const libraries = await (await page.request.get("/api/libraries")).json();
  const uploaded = await page.request.post("/api/books", {
    multipart: {
      file: {
        name: "vertical.epub",
        mimeType: "application/epub+zip",
        buffer: fs.readFileSync(FIXTURE),
      },
      library_id: libraries[0].id,
    },
  });
  expect(uploaded.ok()).toBeTruthy();
  const book = await uploaded.json();

  await page.goto(`/books/${book.id}/read`);
  const frame = page.frameLocator("iframe").first();
  await expect(frame.getByText("話說天下大勢").first()).toBeVisible({
    timeout: 30_000,
  });

  const writingMode = await page
    .locator("iframe")
    .first()
    .evaluate((el) => {
      const doc = (el as HTMLIFrameElement).contentDocument;
      if (!doc) return "no-document";
      return getComputedStyle(doc.documentElement).writingMode;
    });
  expect(writingMode).toBe("vertical-rl");
});
