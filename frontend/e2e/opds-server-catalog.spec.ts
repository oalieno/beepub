import { test, expect, type APIRequestContext } from "@playwright/test";
import { ADMIN, ADMIN_STATE } from "./helpers";
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
  // Same file, same digest: linked to the existing book, not a copy.
  await expect(
    page.getByText(`"${BOOK.title}" is already on the server`),
  ).toBeVisible({ timeout: 30_000 });
  await page
    .getByTitle("Already on the server — open the book")
    .first()
    .click();
  await expect(page).toHaveURL(/\/books\/[0-9a-f-]+$/);
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
