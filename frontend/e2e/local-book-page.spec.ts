import path from "node:path";
import { fileURLToPath } from "node:url";
import { test, expect, type Page } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";
import {
  PLATES_BOOK,
  TOUCH_BOOK,
  seedFixture,
  simulateApp,
} from "./ng-helpers";

/**
 * The device-local book page: a shelf card opens it (Home's
 * continue-reading row opens the reader directly, in both modes); status
 * and notes are written offline into the device record, and — once the
 * book is linked to a server copy — notes sync both ways under their own
 * LWW stamp.
 *
 * The app is simulated as in reader-ng-local / download-queue
 * (`CapacitorCustomPlatform`; Preferences → localStorage, Filesystem →
 * IndexedDB).
 */

const FIXTURES = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  "fixtures",
);

/** Shelf card → the book page. Returns the local book id. */
async function openBookPage(page: Page, title: string): Promise<string> {
  await page.getByRole("button", { name: title }).first().click();
  await page.waitForURL(/\/local\/[^/]+$/);
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
  return /\/local\/([^/]+)$/.exec(page.url())![1];
}

/** Home, then the Books entry — client-side, as in the app. (A full load
 *  of /local on the web stack bounces through the server's login
 *  redirect, which local mode then sends to Home.) */
async function openShelf(page: Page) {
  await page.goto("/");
  await page.getByRole("link", { name: "Books", exact: true }).first().click();
  await page.waitForURL(/\/local$/);
}

async function importFixture(
  page: Page,
  file: string,
  title: string,
  mode: "local" | "server" = "local",
) {
  if (mode === "local") await openShelf(page);
  else await page.goto("/local");
  await page
    .locator('input[type="file"]')
    .setInputFiles(path.join(FIXTURES, file));
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
}

function deviceRecord(page: Page, id: string) {
  return page.evaluate((key) => {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : null;
  }, `CapacitorStorage.local-interaction:${id}`);
}

test.describe("local mode", () => {
  test.beforeEach(({ page }) =>
    simulateApp(page, { localMode: "1", "reader-gestures-seen": "1" }),
  );

  test("notes are written on the device and come back", async ({ page }) => {
    await importFixture(page, TOUCH_BOOK.file, TOUCH_BOOK.title);
    const id = await openBookPage(page, TOUCH_BOOK.title);
    await page.getByRole("button", { name: /Add a private note/ }).click();
    const box = page.getByPlaceholder("Write your notes here...");
    await box.fill("Read on the night train.");
    await expect
      .poll(async () => (await deviceRecord(page, id))?.notes)
      .toBe("Read on the night train.");
    expect((await deviceRecord(page, id)).notes_updated_at).toMatch(/^\d{4}-/);
    await page.getByRole("button", { name: "Done" }).click();

    await page.getByRole("link", { name: "Back" }).click();
    await page.waitForURL(/\/local$/);
    await openBookPage(page, TOUCH_BOOK.title);
    await expect(page.getByText("Read on the night train.")).toBeVisible();
  });

  test("the reading status is set on the device", async ({ page }) => {
    await importFixture(page, TOUCH_BOOK.file, TOUCH_BOOK.title);
    const id = await openBookPage(page, TOUCH_BOOK.title);
    await page.locator("[data-select-trigger]").first().click();
    await page.getByRole("option", { name: "Want to Read" }).click();
    await expect
      .poll(async () => (await deviceRecord(page, id))?.reading_status)
      .toBe("want_to_read");
    expect((await deviceRecord(page, id)).status_updated_at).toMatch(/^\d{4}-/);
  });

  test("Home lands first, and a book being read is one tap away there", async ({
    page,
  }) => {
    await importFixture(page, TOUCH_BOOK.file, TOUCH_BOOK.title);
    await page.getByRole("link", { name: "Home" }).first().click();
    await page.waitForURL(/\/$/);
    const row = page.getByTestId("continue-reading");
    // Never opened: recently added, but not in the row yet.
    await expect(
      page.getByRole("button", { name: TOUCH_BOOK.title }).first(),
    ).toBeVisible();
    await expect(row).toHaveCount(0);

    const id = await openBookPage(page, TOUCH_BOOK.title);
    await readOnePage(page, id);

    // The reader's back lands on the book page, the page's back on Home —
    // where the row now leads straight back into the book.
    await page.getByRole("button", { name: "Go back" }).click();
    await page.waitForURL(new RegExp(`/local/${id}$`));
    await page.getByRole("link", { name: "Back" }).click();
    await page.waitForURL(/\/$/);
    await row.getByRole("link", { name: new RegExp(TOUCH_BOOK.title) }).click();
    await page.waitForURL(new RegExp(`/books/${id}/read`));
  });
});

/** Open the reader from the book page and turn a page, so the device
 *  records a position. */
async function readOnePage(page: Page, id: string) {
  await page.getByRole("button", { name: "Start Reading" }).click();
  await page.waitForFunction(
    () => !!window.__beepubReaderNG?.core?.lastLocation,
    null,
    { timeout: 30_000 },
  );
  await page.evaluate(() => window.__beepubReaderNG.core.next());
  await expect
    .poll(
      () =>
        page.evaluate(
          (key) => !!localStorage.getItem(key),
          `CapacitorStorage.local-progress:${id}`,
        ),
      { timeout: 10_000 },
    )
    .toBe(true);
}

test.describe("linked to the server", () => {
  test.use({ storageState: ADMIN_STATE });
  test.beforeEach(({ page, baseURL }) =>
    simulateApp(page, {
      serverUrl: baseURL!.replace(/\/$/, ""),
      "reader-gestures-seen": "1",
    }),
  );

  test("notes sync both ways", async ({ page }) => {
    const serverId = await seedFixture(page.request, PLATES_BOOK);
    // A web edit that predates the device copy.
    expect(
      (
        await page.request.put(`/api/books/${serverId}/notes`, {
          data: { notes: "Written on the web." },
        })
      ).ok(),
    ).toBeTruthy();

    await page.goto(`/books/${serverId}`);
    await page
      .getByRole("button", { name: "Download to this device" })
      .first()
      .click();
    await expect(
      page.getByRole("button", { name: /In your local library/ }).first(),
    ).toBeVisible({ timeout: 30_000 });

    // Downloading links the copy and syncs it: the web notes fold in.
    await page.goto("/local");
    await openBookPage(page, PLATES_BOOK.title);
    await expect(page.getByText("Written on the web.")).toBeVisible();

    // A device edit is newer: it goes up.
    await page.getByRole("button", { name: "Edit" }).first().click();
    await page
      .getByPlaceholder("Write your notes here...")
      .fill("Rewritten on the device.");
    await expect
      .poll(
        async () =>
          (
            await (
              await page.request.get(`/api/books/${serverId}/interaction`)
            ).json()
          ).notes,
        { timeout: 15_000 },
      )
      .toBe("Rewritten on the device.");
  });

  test("Home's continue row includes books only on this device", async ({
    page,
  }) => {
    // Keep the import unlinked even if the server has the same file.
    await page.route("**/api/books/by-digest", (route) =>
      route.fulfill({ json: { matches: {} } }),
    );
    await importFixture(page, TOUCH_BOOK.file, TOUCH_BOOK.title, "server");
    const id = await openBookPage(page, TOUCH_BOOK.title);
    await readOnePage(page, id);

    await page.goto("/");
    await expect(
      page
        .getByTestId("continue-reading")
        .getByRole("link", { name: new RegExp(TOUCH_BOOK.title) }),
    ).toHaveAttribute("href", `/books/${id}/read`);
  });
});
