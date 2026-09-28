import { test, expect, type APIRequestContext } from "@playwright/test";
import { ADMIN, ADMIN_STATE, transferPanel } from "./helpers";
import { seedFixture, type Fixture } from "./ng-helpers";

/**
 * The server library's OPDS catalogs, on the web. The "remote" catalog is
 * this stack's own OPDS feed, which the backend reaches over the docker
 * network at http://nginx/opds/ — plain http, Basic auth, on a private
 * address: the home-network case the feature is for.
 */

test.use({ storageState: ADMIN_STATE });

const NAME = "E2E Loopback Catalog";
// A fixture whose feed entry carries a cover.
const BOOK: Fixture = {
  file: "e2e-test-book.epub",
  title: "E2E Test Book",
  readyText: "",
};

async function resetCatalog(request: APIRequestContext): Promise<string> {
  const catalogs: { id: string; name: string }[] = await (
    await request.get("/api/opds-catalogs")
  ).json();
  for (const c of catalogs.filter((c) => c.name === NAME))
    await request.delete(`/api/opds-catalogs/${c.id}`);
  const created = await request.post("/api/opds-catalogs", {
    data: {
      name: NAME,
      url: "http://nginx/opds/",
      username: ADMIN.username,
      password: ADMIN.password,
    },
  });
  expect(created.ok()).toBeTruthy();
  return (await created.json()).id;
}

function blockPrivate(request: APIRequestContext, on: boolean) {
  return request.put("/api/admin/settings", {
    data: { opds_block_private_network: on ? "true" : "false" },
  });
}

test.afterEach(({ request }) => blockPrivate(request, false));

test("browse a server catalog and import a book the server already has", async ({
  page,
}) => {
  await seedFixture(page.request, BOOK);
  const catalogId = await resetCatalog(page.request);

  await page.goto("/catalogs");
  await page.getByText(NAME).click();
  await expect(page).toHaveURL(`/catalogs/${catalogId}`);

  const search = page.getByPlaceholder("Search this catalog");
  await search.fill(BOOK.title);
  await search.press("Enter");
  // The cover comes through the server, credentials and all.
  const cover = page.getByAltText(BOOK.title).first();
  await expect(cover).toBeVisible();
  await expect
    .poll(() => cover.evaluate((img: HTMLImageElement) => img.naturalWidth))
    .toBeGreaterThan(1);

  await expect(page.getByLabel("Import into")).toContainText(/.+/);
  await page.getByTitle("Import into the library").first().click();
  // Same file, same digest: linked to the existing book, not a copy — and
  // the card says so, not only a toast at the screen's edge.
  const outcome = page.getByRole("link", {
    name: "Already in your libraries — open",
  });
  await expect(outcome.first()).toBeVisible({ timeout: 30_000 });
  // The transfer panel keeps the outcome after leaving the catalog, and
  // its row opens the book.
  const row = transferPanel(page).getByRole("listitem").filter({
    hasText: BOOK.title,
  });
  await expect(row.getByText("Already there")).toBeVisible();
  // In-app navigation: a reload would start a fresh app, panel and all.
  await page.getByRole("link", { name: "Shelves" }).first().click();
  await expect(page).toHaveURL(/\/bookshelves/);
  await expect(row.getByText("Already there")).toBeVisible();
  await row.getByRole("button", { name: BOOK.title }).first().click();
  await expect(page).toHaveURL(/\/books\/[0-9a-f-]+$/);
  // The reader never shows it.
  await page
    .getByRole("button", { name: /Start Reading|Continue Reading/ })
    .first()
    .click();
  await expect(page).toHaveURL(/\/read$/);
  await expect(transferPanel(page)).toHaveCount(0);
});

test("a full page of covers from the server's own catalog loads", async ({
  page,
}) => {
  // Every cover is a proxied request back into this server, whose OPDS
  // auth needs a database connection too: holding one per waiting proxy
  // request used to drain the pool and time everything out.
  const catalogId = await resetCatalog(page.request);
  await page.goto(`/catalogs/${catalogId}`);
  await page.getByText("All books").click();
  // Feeds on the catalog's own host are named by path.
  await expect(page).toHaveURL(
    `/catalogs/${catalogId}?feed=${encodeURIComponent("/opds/all")}`,
  );
  // Every cover on the page loads (however many books the database has).
  await expect
    .poll(
      () =>
        page.evaluate(() => {
          const imgs = [...document.querySelectorAll("main img")];
          return (
            imgs.length > 0 &&
            imgs.every((img) => (img as HTMLImageElement).naturalWidth > 1)
          );
        }),
      { timeout: 30_000 },
    )
    .toBe(true);
  // A reload lands on the same page.
  await page.reload();
  await expect(page.getByRole("heading", { level: 3 }).first()).toBeVisible();
});

test("a dialog taller than the space left by the keyboard stays on screen", async ({
  page,
}) => {
  // A phone with the keyboard up: the app's viewport shrinks to this.
  await page.setViewportSize({ width: 390, height: 420 });
  await page.goto("/catalogs");
  await page.getByRole("button", { name: "Add catalog" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  // Polled: the open animation scales it in.
  await expect
    .poll(async () => {
      const box = (await dialog.boundingBox())!;
      return [box.y >= 0, box.y + box.height <= 420];
    })
    .toEqual([true, true]);
  await expect(page.getByRole("button", { name: "Close" })).toBeInViewport();
});

test("an admin can block catalogs on the private network", async ({ page }) => {
  const catalogId = await resetCatalog(page.request);
  expect((await blockPrivate(page.request, true)).ok()).toBeTruthy();
  await page.goto(`/catalogs/${catalogId}`);
  await expect(
    page.getByText("This address is on the server's private network"),
  ).toBeVisible();
});
