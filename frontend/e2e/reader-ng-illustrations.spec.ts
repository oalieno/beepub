import { test, expect, type Page } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";
import { TOUCH_BOOK, marks, openBook, seedFixture } from "./ng-helpers";

/**
 * reader-ng: AI illustration markers on the new engine. Generation needs
 * an image model the e2e stack does not have, so the listing is served
 * from the test: a completed illustration on a known passage must be
 * drawn as the gradient marker, sit above a highlight on the same
 * passage, and open the viewer on tap.
 *
 * How a generation ends is said where the illustration is, and stays
 * there — never in a toast: a failed one's row in the list has the
 * reason and a Retry (nothing is drawn for it on the passage, and a
 * highlight there opens as ever); one the page gave up waiting for
 * says so on its row, with a way to look again.
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

const row = (id: string, status: string, error: string | null = null) => ({
  id,
  user_id: "e2e",
  book_id: "e2e",
  cfi_range: PASSAGE_CFI,
  text: "librarian",
  style_prompt: "watercolor",
  custom_prompt: null,
  status,
  error_message: error,
  created_at: "2026-09-06T00:00:00Z",
  updated_at: "2026-09-06T00:00:00Z",
});

test("a generation that failed is said on its row, with a Retry, and leaves the passage alone; one that takes too long has a way to look again — and neither is a toast", async ({
  page,
}) => {
  test.setTimeout(90_000);
  const bookId = await seedFixture(page.request, TOUCH_BOOK);
  const cleanup = await withHighlight(page, bookId);
  try {
    const base = `/api/books/${bookId}/illustrations`;
    const created: unknown[] = [];
    const deleted: string[] = [];
    // What the server says of the retried one, each time it is asked.
    let second: "abort" | "generating" | "failed" | "completed" = "abort";
    let asked = 0;
    const everToasted: string[] = [];

    await page.route(
      (url) => url.pathname === base,
      (route) => {
        if (route.request().method() === "POST") {
          created.push(route.request().postDataJSON());
          return route.fulfill({
            status: 201,
            json: row("e2e-ill-2", "generating"),
          });
        }
        return route.fulfill({
          json: [row("e2e-ill-1", "failed", "ReadTimeout from the model")],
        });
      },
    );
    await page.route(
      (url) => url.pathname === `${base}/e2e-ill-1`,
      (route) => {
        deleted.push(route.request().method());
        return route.fulfill({ status: 204, body: "" });
      },
    );
    await page.route(
      (url) => url.pathname === `${base}/e2e-ill-2`,
      (route) => {
        asked++;
        if (second === "abort") return route.abort();
        return route.fulfill({
          json: row(
            "e2e-ill-2",
            second,
            second === "failed" ? "IMAGE_SAFETY" : null,
          ),
        });
      },
    );
    await page.route(
      (url) => url.pathname === `${base}/e2e-ill-2/image`,
      (route) => route.fulfill({ contentType: "image/png", body: PNG_1X1 }),
    );

    await openBook(page, bookId);
    await page.evaluate(() => {
      // Every toast there ever is, kept: none may be about a failure.
      const seen: string[] = ((window as any).__everToasted = []);
      (window as any).__beepubToasts.subscribe(
        (list: { message: string }[]) => {
          for (const t of list)
            if (!seen.includes(t.message)) seen.push(t.message);
        },
      );
    });
    const toasted = () =>
      page.evaluate(() => (window as any).__everToasted as string[]);

    // Nothing of it on the passage: the only mark there is the highlight,
    // and a tap on it opens the highlight's menu.
    await expect
      .poll(async () => (await marks(page)).map((g) => g.fill))
      .toEqual([YELLOW]);
    const { x, y, w, h } = (await marks(page))[0].rects[0];
    await page.evaluate(
      ([cx, cy]) => {
        const doc: Document = window.__beepubReaderNG.core.getContents()[0].doc;
        doc.dispatchEvent(
          new MouseEvent("click", { clientX: cx, clientY: cy, bubbles: true }),
        );
      },
      [x + w / 2, y + h / 2] as const,
    );
    await expect(page.getByTestId("highlight-menu")).toBeVisible();
    await page.keyboard.press("Escape");

    // In the list, at the illustrations: said on its row.
    await page.getByRole("button", { name: "Highlights", exact: true }).click();
    await page.getByRole("button", { name: /^Illustrations\s*1$/ }).click();
    const rows = page.getByTestId("illustration-row");
    await expect(rows).toHaveCount(1);
    await expect(rows).toHaveAttribute("data-status", "failed");
    await expect(rows).toContainText("failed");
    await expect(rows).toContainText("API timed out");

    // Retry asks again as it was asked, and the failed row gives way.
    await rows.getByTestId("illustration-retry").click();
    await expect(rows).toHaveCount(1);
    await expect(rows).toHaveAttribute("data-status", "generating");
    expect(created).toEqual([
      { cfi_range: PASSAGE_CFI, text: "librarian", style_prompt: "watercolor" },
    ]);
    expect(deleted).toEqual(["DELETE"]);

    // The first look does not get through: the page stops waiting, and the
    // row says so and stays that way.
    await expect(rows).toHaveAttribute("data-status", "stalled", {
      timeout: 10_000,
    });
    await expect(rows).toContainText("taking longer than usual");
    expect(asked).toBe(1);
    await page.waitForTimeout(4000);
    expect(asked).toBe(1);
    await expect(rows).toHaveAttribute("data-status", "stalled");

    // Look again — at once, not three seconds on: it failed. Said here.
    second = "failed";
    await rows.getByTestId("illustration-check").click();
    await expect(rows).toHaveAttribute("data-status", "failed", {
      timeout: 2_000,
    });
    await expect(rows).toContainText("Blocked by safety filters");
    await expect(rows.getByTestId("illustration-retry")).toBeVisible();

    // Nothing of all that was a toast.
    everToasted.push(...(await toasted()));
    expect(everToasted).toEqual([]);
    await expect(
      page.getByTestId("toasts").locator("[role=status]"),
    ).toHaveCount(0);
    // (Still nothing drawn for it on the passage.)
    expect((await marks(page)).map((g) => g.fill)).toEqual([YELLOW]);
  } finally {
    await cleanup();
  }
});
