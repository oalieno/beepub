import { test, expect, type Page } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";
import { seedBook } from "./ng-helpers";

/**
 * The book page, after it has loaded, is refreshed when a background
 * sync has merged reading done on the device into the server's rows
 * (`readingSyncStamp`, bumped at the end of a sync pass — typically a few
 * seconds after the app starts). That refresh is silent: the page that
 * is on screen stays on screen. It used to go back to the loading
 * skeleton, throwing away the scroll position with it.
 *
 * A pass only runs in the app with linked books on the device, so the
 * stamp is bumped through its debug handle.
 */

test.use({ storageState: ADMIN_STATE });

function bumpSyncStamp(page: Page) {
  return page.evaluate(() => {
    const { stamp } = (
      window as unknown as {
        __beepubReadingSync: {
          stamp: { update(fn: (n: number) => number): void };
        };
      }
    ).__beepubReadingSync;
    stamp.update((n) => n + 1);
  });
}

/** From now on, note any appearance of the skeleton. */
async function watchSkeleton(page: Page) {
  await page.evaluate(() => {
    const w = window as unknown as { __sawSkeleton: boolean };
    w.__sawSkeleton = false;
    const look = () => {
      if (document.querySelector('[data-testid="book-detail-skeleton"]'))
        w.__sawSkeleton = true;
    };
    new MutationObserver(look).observe(document.body, {
      childList: true,
      subtree: true,
    });
  });
  return () =>
    page.evaluate(
      () => (window as unknown as { __sawSkeleton: boolean }).__sawSkeleton,
    );
}

test("a sync that finishes while the book page is open refreshes it without the skeleton, and a refresh that fails says nothing", async ({
  page,
}) => {
  const bookId = await seedBook(page.request);
  const setFavorite = (is_favorite: boolean) =>
    page.request.put(`/api/books/${bookId}/favorite`, {
      data: { is_favorite },
    });
  expect((await setFavorite(false)).ok()).toBeTruthy();

  try {
    // The skeleton is what a first load shows (the probe below can see
    // it): hold the book back long enough to look.
    let release: () => void = () => {};
    const held = new Promise<void>((resolve) => (release = resolve));
    await page.route(`**/api/books/${bookId}`, async (route) => {
      await held;
      await route.continue();
    });
    await page.goto(`/books/${bookId}`);
    const skeleton = page.getByTestId("book-detail-skeleton");
    await expect(skeleton).toBeVisible();
    release();
    await expect(skeleton).toHaveCount(0);
    const title = page.getByRole("heading", { level: 1 }).first();
    await expect(title).toBeVisible();
    await page.unroute(`**/api/books/${bookId}`);

    const more = page.getByRole("button", { name: "More actions" }).first();
    await more.click();
    await expect(
      page.getByRole("menuitem", { name: "Add to favorites" }),
    ).toBeVisible();
    await page.keyboard.press("Escape");

    // Somewhere down the page, as a reader would be.
    await page.setViewportSize({ width: 1280, height: 500 });
    await page.evaluate(() => window.scrollTo(0, 240));
    const scrolled = await page.evaluate(() => window.scrollY);
    expect(scrolled).toBeGreaterThan(0);

    // The server's row changes behind the page (what a sync does) …
    expect((await setFavorite(true)).ok()).toBeTruthy();
    const sawSkeleton = await watchSkeleton(page);
    const requests: string[] = [];
    page.on("request", (r) => {
      if (r.url().includes(`/api/books/${bookId}`))
        requests.push(new URL(r.url()).pathname);
    });
    const refetched = page.waitForResponse((r) =>
      r.url().endsWith(`/api/books/${bookId}/interaction`),
    );
    await bumpSyncStamp(page);
    await refetched;
    await page.waitForTimeout(600);

    // … and the page takes it in where it stands.
    expect(await sawSkeleton()).toBe(false);
    expect(await page.evaluate(() => window.scrollY)).toBe(scrolled);
    await expect(title).toBeVisible();
    // Only what a sync changes is asked for again, not the whole page.
    expect(requests.sort()).toEqual([
      `/api/books/${bookId}/highlights`,
      `/api/books/${bookId}/interaction`,
    ]);
    await more.click();
    await expect(
      page.getByRole("menuitem", { name: "Remove from favorites" }),
    ).toBeVisible();
    await page.keyboard.press("Escape");

    // A refresh that cannot reach the server: nothing shows, nothing is
    // lost.
    await page.route("**/api/books/**", (route) => route.abort());
    const failed = page.waitForEvent("requestfailed", (r) =>
      r.url().endsWith("/interaction"),
    );
    await bumpSyncStamp(page);
    await failed;
    await page.waitForTimeout(600);
    expect(await sawSkeleton()).toBe(false);
    await expect(page.locator(".toast-position [role=status]")).toHaveCount(0);
    await expect(title).toBeVisible();
    await page.unroute("**/api/books/**");
    await more.click();
    await expect(
      page.getByRole("menuitem", { name: "Remove from favorites" }),
    ).toBeVisible();
  } finally {
    await setFavorite(false);
  }
});
