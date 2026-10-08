import { test, expect } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";

/**
 * The grouped list across every library, and the way out of one
 * library's empty search.
 */

test.use({ storageState: ADMIN_STATE });

test("a series kept in two libraries is two cards in the grouped list", async ({
  page,
}) => {
  // The same series name in two libraries is two series: identity is the
  // library and the name together.
  const series = (library: string, name: string) => ({
    type: "series",
    series: {
      series_key: "e2e lantern series",
      series_name: "E2E Lantern Series",
      library_id: library,
      library_name: name,
      book_count: 2,
      read_count: 0,
      rating: null,
      notes: null,
      cover_book: null,
    },
  });
  await page.route(/\/api\/books\/grouped\?/, (route) =>
    route.fulfill({
      json: {
        items: [
          series("00000000-0000-4000-8000-0000000000a1", "Lantern Room"),
          series("00000000-0000-4000-8000-0000000000a2", "Sealed Annex"),
        ],
        total: 2,
      },
    }),
  );
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));

  await page.goto("/libraries/all?collapse=1");
  await expect(
    page.locator(".book-grid [role=button]", { hasText: "E2E Lantern Series" }),
  ).toHaveCount(2);
  // ...and each says which library it is.
  await expect(page.getByTestId("series-library")).toHaveText([
    /Lantern Room/,
    /Sealed Annex/,
  ]);
  expect(errors).toEqual([]);
});

test("one library's empty search offers the same search over all books, and all books offers nothing further", async ({
  page,
}) => {
  const libraries = await (await page.request.get("/api/libraries")).json();
  const query = "zzqx-no-such-book";

  await page.goto(`/libraries/${libraries[0].id}?search=${query}`);
  const everywhere = page.getByTestId("search-everywhere");
  await expect(everywhere).toBeVisible();
  await everywhere.click();

  await expect(page).toHaveURL(new RegExp(`/libraries/all\\?search=${query}`));
  await expect(page.getByPlaceholder(/Search/)).toHaveValue(query);
  await expect(page.getByText("No books match")).toBeVisible();
  await expect(everywhere).toHaveCount(0);
  await expect(page.getByRole("dialog")).toHaveCount(0);
});
