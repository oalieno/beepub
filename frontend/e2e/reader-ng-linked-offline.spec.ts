import { test, expect, type APIRequestContext } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";
import {
  iphone,
  location,
  marks,
  openBook,
  pointOnWord,
  resetProgress,
  seedBook,
  simulateApp,
  touchTap,
} from "./ng-helpers";

/**
 * A server book read through its downloaded copy, with the connection
 * gone: the book opens, and a highlight made there lands on the device
 * and reaches the server once the connection is back.
 *
 * The app is simulated as in local-book-page (`CapacitorCustomPlatform`;
 * Preferences → localStorage, Filesystem → IndexedDB), in server mode.
 */

test.use({ storageState: ADMIN_STATE, ...iphone });

interface Row {
  id: string;
  text: string;
}

async function listHighlights(
  request: APIRequestContext,
  bookId: string,
): Promise<Row[]> {
  return (await request.get(`/api/books/${bookId}/highlights`)).json();
}

test.beforeEach(({ page, baseURL }) =>
  simulateApp(page, { serverUrl: baseURL!.replace(/\/$/, "") }),
);

test("a highlight made offline on a downloaded book syncs up later", async ({
  page,
  context,
}) => {
  const bookId = await seedBook(page.request);
  for (const h of await listHighlights(page.request, bookId)) {
    if (h.text === "librarian")
      await page.request.delete(`/api/books/${bookId}/highlights/${h.id}`);
  }

  await page.goto(`/books/${bookId}`);
  await page
    .getByRole("button", { name: "Download to this device" })
    .first()
    .click();
  await expect(
    page.getByRole("button", { name: /Downloaded to this device/ }).first(),
  ).toBeVisible({ timeout: 30_000 });

  await openBook(page, bookId);
  await expect.poll(() => marks(page)).toHaveLength(0);

  // The connection dies mid-session.
  await page.route("**/api/**", (route) => route.abort());
  const pt = await pointOnWord(page, "librarian", 0);
  const cdp = await context.newCDPSession(page);
  await touchTap(cdp, pt!, 900);
  const menu = page.getByTestId("highlight-menu");
  await menu.getByTitle("Highlight", { exact: true }).click();
  await expect.poll(() => marks(page)).toHaveLength(1);
  expect(
    await page.evaluate(() =>
      Object.keys(localStorage)
        .filter((k) => k.startsWith("CapacitorStorage.local-highlights:"))
        .flatMap((k) => JSON.parse(localStorage.getItem(k)!) as Row[])
        .map((h) => h.text),
    ),
  ).toContain("librarian");
  expect(
    (await listHighlights(page.request, bookId)).map((h) => h.text),
  ).not.toContain("librarian");

  // Back online: the next open pushes the device record first.
  await page.unroute("**/api/**");
  await page.evaluate(() => delete window.__beepubReaderNG);
  await openBook(page, bookId);
  await expect
    .poll(
      async () =>
        (await listHighlights(page.request, bookId)).map((h) => h.text),
      { timeout: 15_000 },
    )
    .toContain("librarian");
  await expect.poll(() => marks(page)).toHaveLength(1);
});

test("reconnecting pushes an offline highlight without reopening the book", async ({
  page,
  context,
}) => {
  const bookId = await seedBook(page.request);
  for (const h of await listHighlights(page.request, bookId)) {
    if (h.text === "librarian")
      await page.request.delete(`/api/books/${bookId}/highlights/${h.id}`);
  }
  await page.goto(`/books/${bookId}`);
  await page
    .getByRole("button", { name: "Download to this device" })
    .first()
    .click();
  await expect(
    page.getByRole("button", { name: /Downloaded to this device/ }).first(),
  ).toBeVisible({ timeout: 30_000 });
  // Launch-time sync already ran: a reconnect right after must still push.
  await openBook(page, bookId);

  await context.setOffline(true);
  const pt = await pointOnWord(page, "librarian", 0);
  const cdp = await context.newCDPSession(page);
  await touchTap(cdp, pt!, 900);
  await page
    .getByTestId("highlight-menu")
    .getByTitle("Highlight", { exact: true })
    .click();
  await expect.poll(() => marks(page)).toHaveLength(1);

  await context.setOffline(false);
  await expect
    .poll(
      async () =>
        (await listHighlights(page.request, bookId)).map((h) => h.text),
      { timeout: 30_000 },
    )
    .toContain("librarian");
});

test("a device record holding page counts with nulls in them is sent without them, and put right on the device", async ({
  page,
}) => {
  const bookId = await seedBook(page.request);
  await page.goto(`/books/${bookId}`);
  await page
    .getByRole("button", { name: "Download to this device" })
    .first()
    .click();
  await expect(
    page.getByRole("button", { name: /Downloaded to this device/ }).first(),
  ).toBeVisible({ timeout: 30_000 });

  try {
    // A page turn puts the position on the device.
    await openBook(page, bookId);
    await page.evaluate(() => window.__beepubReaderNG.core.next());
    const progressKey = () =>
      page.evaluate(
        () =>
          Object.keys(localStorage).find((k) =>
            k.startsWith("CapacitorStorage.local-progress:"),
          ) ?? null,
      );
    await expect.poll(progressKey, { timeout: 10_000 }).not.toBeNull();
    const key = (await progressKey())!;
    // Away from the reader, so that its parting save is behind us.
    await page.goto(`/books/${bookId}`);
    await page.waitForLoadState("networkidle");

    // The record as a build before 2026-10-05 left it after a jump over
    // chapters never opened: holes, which JSON wrote as nulls. Newer than
    // anything the server has, so it is what a sync sends — every time,
    // for as long as the book is not read again.
    const stamp = new Date(Date.now() + 60_000).toISOString();
    const pushed = page.waitForRequest(
      (r) =>
        r.method() === "POST" &&
        new URL(r.url()).pathname === `/api/books/${bookId}/sync` &&
        r.postDataJSON()?.progress?.last_read_at === stamp,
      { timeout: 30_000 },
    );
    await page.evaluate(
      ([key, stamp]) => {
        const record = JSON.parse(localStorage.getItem(key)!);
        record.section_page_counts = [4, null, null, 2, null];
        record.last_read_at = record.updated_at = stamp;
        localStorage.setItem(key, JSON.stringify(record));
      },
      [key, stamp],
    );

    // Opening the book pushes the device record first.
    await page.evaluate(() => delete window.__beepubReaderNG);
    await openBook(page, bookId, { restore: "1" });
    const body = (await pushed).postDataJSON();
    expect(body.progress.section_page_counts).toEqual([4, 0, 0, 2, 0]);
    const counts = await page.evaluate(
      (key) =>
        JSON.parse(localStorage.getItem(key)!).section_page_counts as unknown[],
      key,
    );
    expect(counts.length).toBeGreaterThan(0);
    expect(counts.every((n) => typeof n === "number")).toBe(true);
    // The server took it: the position on record is the device's.
    await expect
      .poll(async () =>
        Date.parse(
          (
            await (
              await page.request.get(`/api/books/${bookId}/progress`)
            ).json()
          ).last_read_at,
        ),
      )
      .toBe(Date.parse(stamp));
  } finally {
    await resetProgress(page.request, bookId);
  }
});

/**
 * The server refuses the device's records (what a 422 did to a book
 * read on the train): the reader must not open at the server's older
 * position — it would save it with a fresh timestamp, over the reading
 * that never got uploaded. It opens where the device was read last, the
 * device record stays, and the next sync that is let through pushes it.
 */
for (const status of [422, 500]) {
  test(`a push the server refuses (${status}) does not cost the position: the book opens where the device left it, and it is pushed once the server takes it`, async ({
    page,
  }) => {
    test.setTimeout(120_000);
    const bookId = await seedBook(page.request);
    const serverProgress = async () =>
      (await page.request.get(`/api/books/${bookId}/progress`)).json();
    const refuse = (url: URL) =>
      new RegExp(`/api/books/${bookId}/(sync|progress)$`).test(url.pathname);
    try {
      await page.goto(`/books/${bookId}`);
      await page
        .getByRole("button", { name: "Download to this device" })
        .first()
        .click();
      await expect(
        page.getByRole("button", { name: /Downloaded to this device/ }).first(),
      ).toBeVisible({ timeout: 30_000 });

      // Read on: a few pages in, the position lands on the device.
      await openBook(page, bookId);
      const start = await location(page);
      for (let i = 0; i < 3; i++) {
        await page.evaluate(() => window.__beepubReaderNG.core.next());
        await page.waitForTimeout(300);
      }
      const read = await location(page);
      expect([read.index, read.fraction]).not.toEqual([
        start.index,
        start.fraction,
      ]);
      const progressKey = () =>
        page.evaluate(
          () =>
            Object.keys(localStorage).find((k) =>
              k.startsWith("CapacitorStorage.local-progress:"),
            ) ?? null,
        );
      await expect.poll(progressKey, { timeout: 10_000 }).not.toBeNull();
      const key = (await progressKey())!;
      const deviceRecord = () =>
        page.evaluate(
          (key) =>
            JSON.parse(localStorage.getItem(key)!) as {
              cfi: string;
              section_index: number;
              last_read_at: string;
            },
          key,
        );
      await expect
        .poll(async () => (await serverProgress()).cfi, { timeout: 10_000 })
        .toBe((await deviceRecord()).cfi);
      // Away from the reader, so that its parting save is behind us.
      await page.goto(`/books/${bookId}`);
      await page.waitForLoadState("networkidle");
      const planted = await deviceRecord();

      // From here the server takes nothing from this device, and what it
      // has is an older position: the first page.
      await page.route(
        (url) => refuse(url),
        (route) =>
          route.request().method() === "GET"
            ? route.continue()
            : route.fulfill({
                status,
                contentType: "application/json",
                body: JSON.stringify({ detail: "refused" }),
              }),
      );
      await resetProgress(page.request, bookId);
      const older = await serverProgress();
      expect(older.cfi).not.toBe(planted.cfi);
      // The device record is the newer of the two.
      const stamp = new Date(Date.now() + 60_000).toISOString();
      await page.evaluate(
        ([key, stamp]) => {
          const record = JSON.parse(localStorage.getItem(key)!);
          record.last_read_at = record.updated_at = stamp;
          localStorage.setItem(key, JSON.stringify(record));
        },
        [key, stamp],
      );

      const refused = page.waitForResponse(
        (r) =>
          r.request().method() === "POST" &&
          new URL(r.url()).pathname === `/api/books/${bookId}/sync` &&
          r.status() === status,
        { timeout: 30_000 },
      );
      await page.evaluate(() => delete window.__beepubReaderNG);
      await openBook(page, bookId, { restore: "1" });
      await refused;
      // Where the device was read last, not the server's first page.
      const opened = await location(page);
      expect(opened.index).toBe(read.index);
      expect(opened.fraction).toBeCloseTo(read.fraction, 2);
      await page.waitForTimeout(3000); // (past the reader's debounced save)
      const kept = await deviceRecord();
      expect(kept.cfi).toBe(planted.cfi);
      expect(kept.section_index).toBe(planted.section_index);
      expect(Date.parse(kept.last_read_at)).toBeGreaterThan(
        Date.parse(older.last_read_at),
      );
      // The server still has what it had.
      expect((await serverProgress()).cfi).toBe(older.cfi);

      // Away again while the server still refuses, then it is let
      // through: the next open pushes the device record first.
      await page.goto(`/books/${bookId}`);
      await page.waitForLoadState("networkidle");
      expect((await serverProgress()).cfi).toBe(older.cfi);
      expect((await deviceRecord()).cfi).toBe(planted.cfi);
      await page.unrouteAll({ behavior: "wait" });
      await page.evaluate(() => delete window.__beepubReaderNG);
      await openBook(page, bookId, { restore: "1" });
      await expect
        .poll(async () => (await serverProgress()).cfi, { timeout: 20_000 })
        .toBe(planted.cfi);
      expect((await location(page)).index).toBe(read.index);
    } finally {
      await page.unrouteAll({ behavior: "ignoreErrors" });
      await resetProgress(page.request, bookId);
    }
  });
}
