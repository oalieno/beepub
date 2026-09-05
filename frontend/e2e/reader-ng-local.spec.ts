import path from "node:path";
import { fileURLToPath } from "node:url";
import { test, expect, type Page } from "@playwright/test";
import { TOUCH_BOOK, VERTICAL_BOOK, type Fixture } from "./ng-helpers";

/**
 * reader-ng on a device-local book (G2 ④): the whole-file payload goes
 * through the jszip loader instead of the server streamer, and reading
 * state lands in the device records.
 *
 * The local library is native-only, so the spec runs the web build as a
 * simulated native platform: Capacitor reads `CapacitorCustomPlatform`
 * before anything else, and plugins without a native bridge fall back to
 * their web implementations (Filesystem → IndexedDB, Preferences →
 * localStorage). Local mode on top means no server is involved at all —
 * the spec carries no session and asserts that no book API is called.
 */

const FIXTURES = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  "fixtures",
);

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    (
      window as unknown as { CapacitorCustomPlatform: { name: string } }
    ).CapacitorCustomPlatform = { name: "ios" };
    localStorage.setItem("localMode", "1");
    localStorage.setItem("reader-gestures-seen", "1");
    // The stack is plain http, so the page is not a secure context and
    // lacks crypto.randomUUID (the import mints ids with it). The app
    // itself always runs in one (capacitor:// / https).
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
  });
});

/** Open the shelf card's menu entry for the new reader (client-side
 *  navigation, as in the app — a full load of a reader URL on the web
 *  stack bounces through the server-side login redirect first). */
async function openFromShelf(
  page: Page,
  fixture: Fixture = TOUCH_BOOK,
): Promise<string> {
  // The card itself is a role=button whose name includes the trigger's
  // label, so match exactly.
  await page.getByRole("button", { name: "More actions", exact: true }).click();
  await page
    .getByRole("menuitem", { name: "Open in the new reader (experimental)" })
    .click();
  await page.waitForURL(/\/books\/[^/]+\/read-ng/);
  await page.waitForFunction(
    () => !!window.__beepubReaderNG?.core?.lastLocation,
    null,
    { timeout: 30_000 },
  );
  await expect
    .poll(() =>
      page.evaluate((text) => {
        const doc: Document = window.__beepubReaderNG.core.getContents()[0].doc;
        return doc.body?.textContent?.includes(text) ?? false;
      }, fixture.readyText),
    )
    .toBe(true);
  return /\/books\/([^/]+)\/read-ng/.exec(page.url())![1];
}

async function importFixture(page: Page, fixture: Fixture) {
  await page.goto("/local");
  await page
    .locator('input[type="file"]')
    .setInputFiles(path.join(FIXTURES, fixture.file));
  await expect(
    page.getByRole("heading", { name: fixture.title }),
  ).toBeVisible();
}

function readLocation(page: Page) {
  return page.evaluate(() => {
    const l = window.__beepubReaderNG.core.lastLocation;
    return { index: l.index as number, fraction: l.fraction as number };
  });
}

test("an imported book opens through the zip loader and keeps its place on the device", async ({
  page,
}) => {
  const bookApiCalls: string[] = [];
  page.on("request", (r) => {
    const { pathname } = new URL(r.url());
    if (pathname.startsWith("/api/books")) bookApiCalls.push(pathname);
  });

  await importFixture(page, TOUCH_BOOK);
  const bookId = await openFromShelf(page);
  expect(await readLocation(page)).toEqual({ index: 0, fraction: 0 });
  // The toolbar's back control (a local book returns to its shelf).
  const back = page.getByRole("button", { name: "Go back" });
  await expect(back).toBeVisible();

  // Turn a page and let the debounced save land in the device record.
  await page.evaluate(() => window.__beepubReaderNG.core.next());
  await expect
    .poll(async () => (await readLocation(page)).fraction)
    .toBeGreaterThan(0);
  const moved = await readLocation(page);
  const progressKey = `CapacitorStorage.local-progress:${bookId}`;
  await expect
    .poll(
      () =>
        page.evaluate((key) => {
          const raw = localStorage.getItem(key);
          return raw ? (JSON.parse(raw).cfi as string) : null;
        }, progressKey),
      { timeout: 10_000 },
    )
    .toMatch(/^epubcfi\(/);

  // Back to the shelf and in again: the saved position is restored.
  await back.click();
  await page.waitForURL(/\/local$/);
  expect(await openFromShelf(page)).toBe(bookId);
  const restored = await readLocation(page);
  expect(restored.index).toBe(moved.index);
  expect(restored.fraction).toBeGreaterThan(0);

  expect(bookApiCalls).toEqual([]);
});

test("stylesheets and resources come out of the archive", async ({ page }) => {
  await importFixture(page, VERTICAL_BOOK);
  await openFromShelf(page, VERTICAL_BOOK);
  // The fixture's writing mode lives in its stylesheet: vertical text
  // proves the CSS was found in the zip and applied. The parser serves
  // every resource from a blob: URL it built from the loader's bytes.
  expect(
    await page.evaluate(() => {
      const core = window.__beepubReaderNG.core;
      const doc: Document = core.getContents()[0].doc;
      const link = doc.querySelector<HTMLLinkElement>("link[rel=stylesheet]");
      return {
        vertical: core.vertical as boolean,
        stylesheet: link?.href.split(":")[0] ?? null,
        writingMode: getComputedStyle(doc.documentElement).writingMode,
      };
    }),
  ).toEqual({ vertical: true, stylesheet: "blob", writingMode: "vertical-rl" });
});
