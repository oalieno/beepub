import { test, expect, type Page } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";
import { TOUCH_BOOK, marks, openBook, seedFixture } from "./ng-helpers";

/**
 * reader-ng: AI illustration markers on the new engine. Generation needs
 * an image model the e2e stack does not have, so the listing is served
 * from the test: a completed illustration on a known passage must be
 * drawn as the gradient marker, sit above a highlight on the same
 * passage, and open the viewer on tap.
 */

test.use({ storageState: ADMIN_STATE });
test.setTimeout(60_000);

/** The first "librarian" as epub.js anchors it (reader-ios-touch.spec). */
const PASSAGE_CFI = "epubcfi(/6/2!/4/4,/1:13,/1:22)";
const ILLUSTRATION_ID = "e2e-illustration-1";
const YELLOW = "#fef08a";
const PNG_1X1 = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==",
  "base64",
);

interface HighlightRow {
  id: string;
  cfi_range: string;
}

/** A highlight on the passage (created here when absent, removed again
 *  only if this test created it). */
async function withHighlight(page: Page, bookId: string) {
  const rows: HighlightRow[] = await (
    await page.request.get(`/api/books/${bookId}/highlights`)
  ).json();
  const existing = rows.find((h) => h.cfi_range === PASSAGE_CFI);
  if (existing) return async () => {};
  const created = await page.request.post(`/api/books/${bookId}/highlights`, {
    data: { cfi_range: PASSAGE_CFI, text: "librarian", color: "yellow" },
  });
  expect(created.ok()).toBeTruthy();
  const { id } = (await created.json()) as HighlightRow;
  return async () => {
    await page.request.delete(`/api/books/${bookId}/highlights/${id}`);
  };
}

test("a completed illustration is drawn as a marker above the highlight and opens the viewer", async ({
  page,
}) => {
  const bookId = await seedFixture(page.request, TOUCH_BOOK);
  const cleanup = await withHighlight(page, bookId);
  try {
    let imageRequests = 0;
    await page.route(
      (url) => url.pathname === `/api/books/${bookId}/illustrations`,
      (route) =>
        route.fulfill({
          json: [
            {
              id: ILLUSTRATION_ID,
              user_id: "e2e",
              book_id: bookId,
              cfi_range: PASSAGE_CFI,
              text: "librarian",
              style_prompt: "watercolor",
              custom_prompt: null,
              status: "completed",
              error_message: null,
              created_at: "2026-09-06T00:00:00Z",
              updated_at: "2026-09-06T00:00:00Z",
            },
          ],
        }),
    );
    await page.route(
      (url) =>
        url.pathname ===
        `/api/books/${bookId}/illustrations/${ILLUSTRATION_ID}/image`,
      (route) => {
        imageRequests++;
        return route.fulfill({ contentType: "image/png", body: PNG_1X1 });
      },
    );
    await openBook(page, bookId);

    // Both are drawn on the passage: the yellow mark and the gradient
    // marker (a `url(#…)` fill, not a colour).
    const isMarker = (fill: string | null) =>
      !!fill?.startsWith("url(#beepub-illustration-fill");
    await expect
      .poll(async () =>
        (await marks(page)).map((g) => (isMarker(g.fill) ? "marker" : g.fill)),
      )
      .toEqual(expect.arrayContaining([YELLOW, "marker"]));
    const marker = (await marks(page)).find((g) => isMarker(g.fill))!;
    expect(marker.rects.length).toBeGreaterThan(0);

    // A tap on the marker opens the picture, not the highlight menu: the
    // marker wins the hit test whatever the draw order.
    const { x, y, w, h } = marker.rects[0];
    await page.evaluate(
      ([cx, cy]) => {
        const doc: Document = window.__beepubReaderNG.core.getContents()[0].doc;
        doc.dispatchEvent(
          new MouseEvent("click", { clientX: cx, clientY: cy, bubbles: true }),
        );
      },
      [x + w / 2, y + h / 2] as const,
    );
    await expect(page.getByRole("button", { name: "Close" })).toBeVisible();
    await expect(page.getByTestId("highlight-menu")).toHaveCount(0);
    await expect.poll(() => imageRequests).toBeGreaterThan(0);

    // Escape closes the viewer.
    await page.keyboard.press("Escape");
    await expect(page.getByRole("button", { name: "Close" })).toHaveCount(0);

    // The sidebar's illustrations tab counts it.
    await page.getByRole("button", { name: "Highlights", exact: true }).click();
    await expect(
      page.getByRole("button", { name: /^Illustrations\s*1$/ }),
    ).toBeVisible();
  } finally {
    await cleanup();
  }
});
