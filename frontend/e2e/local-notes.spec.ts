import path from "node:path";
import { fileURLToPath } from "node:url";
import { test, expect, type Page } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";
import { PLATES_BOOK, TOUCH_BOOK, seedFixture } from "./ng-helpers";

/**
 * Book notes on a device-local book: written offline into the device
 * record, and — once the book is linked to a server copy — synced both
 * ways under their own LWW stamp.
 *
 * The app is simulated as in reader-ng-local / download-queue
 * (`CapacitorCustomPlatform`; Preferences → localStorage, Filesystem →
 * IndexedDB).
 */

const FIXTURES = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  "fixtures",
);

function simulateApp(page: Page, settings: Record<string, string>) {
  return page.addInitScript((settings) => {
    (
      window as unknown as { CapacitorCustomPlatform: { name: string } }
    ).CapacitorCustomPlatform = { name: "ios" };
    for (const [k, v] of Object.entries(settings)) localStorage.setItem(k, v);
    // Plain-http stack: no secure context, no crypto.randomUUID.
    if (typeof crypto.randomUUID !== "function") {
      crypto.randomUUID = () => {
        const b = crypto.getRandomValues(new Uint8Array(16));
        b[6] = (b[6] & 0x0f) | 0x40;
        b[8] = (b[8] & 0x3f) | 0x80;
        const h = Array.from(b, (x) => x.toString(16).padStart(2, "0")).join(
          "",
        );
        return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}` as ReturnType<
          typeof crypto.randomUUID
        >;
      };
    }
  }, settings);
}

/** Shelf card → its menu → Notes. Returns the local book id. */
async function openNotes(page: Page, title: string): Promise<string> {
  await page
    .getByRole("button", { name: title })
    .first()
    .getByRole("button", { name: "More actions" })
    .click();
  await page.getByRole("menuitem", { name: "Notes" }).click();
  await page.waitForURL(/\/local\/[^/]+\/notes$/);
  return /\/local\/([^/]+)\/notes/.exec(page.url())![1];
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
    await page.goto("/local");
    await page
      .locator('input[type="file"]')
      .setInputFiles(path.join(FIXTURES, TOUCH_BOOK.file));
    await expect(
      page.getByRole("heading", { name: TOUCH_BOOK.title }),
    ).toBeVisible();

    const id = await openNotes(page, TOUCH_BOOK.title);
    // Nothing written yet: straight into the editor.
    const box = page.getByPlaceholder("Write your notes here...");
    await box.fill("Read on the night train.");
    await expect
      .poll(async () => (await deviceRecord(page, id))?.notes)
      .toBe("Read on the night train.");
    expect((await deviceRecord(page, id)).notes_updated_at).toMatch(/^\d{4}-/);
    await page.getByRole("button", { name: "Done" }).click();

    await page.getByRole("link", { name: "Back" }).click();
    await page.waitForURL(/\/local$/);
    await openNotes(page, TOUCH_BOOK.title);
    await expect(page.getByText("Read on the night train.")).toBeVisible();
  });
});

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
    await openNotes(page, PLATES_BOOK.title);
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
});
