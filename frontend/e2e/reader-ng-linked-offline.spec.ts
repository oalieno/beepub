import { test, expect, type APIRequestContext } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";
import {
  iphone,
  marks,
  openBook,
  pointOnWord,
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
