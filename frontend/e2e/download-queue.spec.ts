import { test, expect, type Page, type Route } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";
import {
  ANCHOR_BOOK,
  CHAPTERS_BOOK,
  NOTES_BOOK,
  seedFixture,
} from "./ng-helpers";

/**
 * "Download to this device" runs through one app-wide queue, keyed by
 * book: the book page is reused when the reader moves to the next volume,
 * and each volume must show its own state — never the previous one's
 * progress, never its finish.
 *
 * The app is simulated (Capacitor reads `CapacitorCustomPlatform`; the
 * Filesystem plugin falls back to fetch + IndexedDB), in server mode
 * against the stack. Each file request is held until the test lets it
 * go, so "still downloading" is a state the test controls.
 */

test.use({ storageState: ADMIN_STATE });

test.beforeEach(async ({ page, baseURL }) => {
  await page.addInitScript((origin) => {
    (
      window as unknown as { CapacitorCustomPlatform: { name: string } }
    ).CapacitorCustomPlatform = { name: "ios" };
    localStorage.setItem("serverUrl", origin);
    // The stack is plain http: no secure context, no crypto.randomUUID
    // (the local import mints ids with it). The app always has one.
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
  }, baseURL!.replace(/\/$/, ""));
});

/** Hold each book's file request until `release(id)`. */
async function holdFiles(page: Page, ids: string[]) {
  const gates = new Map<string, () => void>();
  const opened = new Map(
    ids.map((id) => [id, new Promise<void>((r) => gates.set(id, r))]),
  );
  for (const id of ids) {
    await page.route(`**/api/books/${id}/file`, async (route: Route) => {
      await opened.get(id);
      await route.continue();
    });
  }
  return (id: string) => gates.get(id)!();
}

const downloadButton = (page: Page) =>
  page.getByRole("button", { name: "Download to this device" }).first();
const stateOf = (page: Page) =>
  page.locator("[data-download-state]").first();
const onDevice = (page: Page) =>
  page
    .getByRole("button", { name: /In your local library/ })
    .first();

/** Make `from` and `to` adjacent volumes of one series. */
function neighbors(page: Page, id: string, near: { previous?: string; next?: string },
) {
  const brief = (bid: string | undefined, title: string, index: number) =>
    bid
      ? { id: bid, title, authors: null, cover_path: null, series_index: index }
      : null;
  // The sidebar shows the volume arrows only for a book in a series.
  void page.route(`**/api/books/${id}`, async (route) => {
    const res = await route.fetch();
    route.fulfill({
      response: res,
      json: {
        ...(await res.json()),
        display_series: "E2E Lantern Series",
        display_series_index: near.next ? 1 : 2,
      },
    });
  });
  return page.route(`**/api/books/${id}/series-neighbors`, (route) =>
    route.fulfill({
      json: {
        series_name: "E2E Lantern Series",
        current_index: near.next ? 1 : 2,
        previous: brief(near.previous, "Volume One", 1),
        next: brief(near.next, "Volume Two", 2),
        progress: null,
      },
    }),
  );
}

test("each volume keeps its own download state across page reuse", async ({
  page,
}) => {
  const a = await seedFixture(page.request, ANCHOR_BOOK);
  const b = await seedFixture(page.request, NOTES_BOOK);
  // Adjacent volumes: the page moves between them without remounting.
  await neighbors(page, a, { next: b });
  await neighbors(page, b, { previous: a });
  const release = await holdFiles(page, [a, b]);

  await page.goto(`/books/${a}`);
  await downloadButton(page).click();
  await expect(stateOf(page)).toHaveAttribute(
    "data-download-state",
    "downloading",
  );

  // Next volume: its own button, free to press, and it waits its turn.
  await page.getByRole("link", { name: "Volume Two" }).click();
  await expect(page).toHaveURL(new RegExp(`/books/${b}$`));
  await downloadButton(page).click();
  await expect(stateOf(page)).toHaveAttribute("data-download-state", "queued");
  // A queued book can be taken back out, and queued again.
  await stateOf(page).click();
  await expect(downloadButton(page)).toBeVisible();
  await downloadButton(page).click();
  await expect(stateOf(page)).toHaveAttribute("data-download-state", "queued");

  // Back on A (reused page again): still downloading.
  await page.getByRole("link", { name: "Volume One" }).click();
  await expect(page).toHaveURL(new RegExp(`/books/${a}$`));
  await expect(stateOf(page)).toHaveAttribute(
    "data-download-state",
    "downloading",
  );
  await page.getByRole("link", { name: "Volume Two" }).click();
  await expect(page).toHaveURL(new RegExp(`/books/${b}$`));

  // A lands while B's page is showing: B moves on to downloading, it is
  // not marked done by A's finish.
  release(a);
  await expect(stateOf(page)).toHaveAttribute(
    "data-download-state",
    "downloading",
  );
  await expect(onDevice(page)).toHaveCount(0);

  release(b);
  await expect(onDevice(page)).toBeVisible({ timeout: 15_000 });
  await page.getByRole("link", { name: "Volume One" }).click();
  await expect(page).toHaveURL(new RegExp(`/books/${a}$`));
  await expect(onDevice(page)).toBeVisible();
});

test("the series downloads in one go, skipping what is already here", async ({
  page,
}) => {
  const ids = [
    await seedFixture(page.request, ANCHOR_BOOK),
    await seedFixture(page.request, NOTES_BOOK),
    await seedFixture(page.request, CHAPTERS_BOOK),
  ];
  const books = await Promise.all(
    ids.map(async (id, i) => ({
      ...(await (await page.request.get(`/api/books/${id}`)).json()),
      series: "E2E Lantern Series",
      series_index: i + 1,
      reading_status: null,
      is_favorite: false,
      user_rating: null,
    })),
  );
  const library = books[0].library_id;
  await page.route("**/api/series/detail?*", (route) =>
    route.fulfill({
      json: {
        series_key: "e2e-lantern",
        series_name: "E2E Lantern Series",
        library_id: library,
        library_name: null,
        book_count: 3,
        read_count: 0,
        rating: null,
        notes: null,
        cover_book: books[0],
      },
    }),
  );
  await page.route(/\/api\/books\/all\?.*series=/, (route) =>
    route.fulfill({ json: { items: books, total: 3 } }),
  );
  const release = await holdFiles(page, ids);

  await page.goto(
    `/series?name=${encodeURIComponent("E2E Lantern Series")}&library=${library}`,
  );
  const series = page.getByTestId("series-download");
  await expect(series).toHaveText("Download the series (3)");
  await series.click();
  await expect(series).toContainText("Downloading 0/3");

  // Volume 1 lands, volume 2 starts; cancelling keeps volume 2 (already on
  // its way) and drops volume 3.
  release(ids[0]);
  await expect(series).toContainText("Downloading 1/3");
  await series.click();
  release(ids[1]);
  await expect(page.getByText('Downloaded 2 books of "E2E Lantern Series"'))
    .toBeVisible({ timeout: 15_000 });
  await expect(series).toHaveText("Download the other 1");

  // Picking up again queues only the missing volume.
  release(ids[2]);
  await series.click();
  await expect(series).toHaveText("All on this device", { timeout: 15_000 });
});
