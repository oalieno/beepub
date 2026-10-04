import { test, expect, type Page } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";
import { openBook, seedBook } from "./ng-helpers";

/**
 * The text block on a wide window: a comfortable measure by default, the
 * whole window when the reader asks for it; and the font size ceiling.
 */

test.use({
  storageState: ADMIN_STATE,
  viewport: { width: 1600, height: 900 },
});

/** The paginator's declared limits and the width the text really takes. */
function measure(page: Page) {
  return page.evaluate(() => {
    const paginator = document.querySelector("[max-inline-size]")!;
    const doc = window.__beepubReaderNG.core.paginator.getContents()[0].doc;
    const p = doc.querySelector("p")!;
    return {
      limit: paginator.getAttribute("max-inline-size"),
      width: p.getBoundingClientRect().width,
    };
  });
}

test("the text keeps to a measure until the reader asks for the full window", async ({
  page,
}) => {
  const bookId = await seedBook(page.request);
  await openBook(page, bookId);
  const fit = await measure(page);
  expect(fit.limit).toBe("720px");
  expect(fit.width).toBeLessThanOrEqual(720);

  await page.getByRole("button", { name: "Reader settings" }).click();
  const row = page.getByTestId("setting-measure");
  await expect(
    row.getByRole("button", { name: "Comfortable" }),
  ).toHaveAttribute("aria-pressed", "true");
  await row.getByRole("button", { name: "Full" }).click();
  await expect.poll(async () => (await measure(page)).width).toBeGreaterThan(
    1400,
  );

  // A reader setting, kept across books and reopens.
  await page.evaluate(() => delete window.__beepubReaderNG);
  await openBook(page, bookId);
  expect((await measure(page)).width).toBeGreaterThan(1400);

  await page.getByRole("button", { name: "Reader settings" }).click();
  await page
    .getByTestId("setting-measure")
    .getByRole("button", { name: "Comfortable" })
    .click();
  await expect
    .poll(async () => (await measure(page)).width)
    .toBeLessThanOrEqual(720);
});

test("the font size goes up to 48px", async ({ page }) => {
  const bookId = await seedBook(page.request);
  await openBook(page, bookId, { size: "44" });
  await page.getByRole("button", { name: "Reader settings" }).click();
  const size = page.getByTestId("setting-font-size");
  const more = page.getByRole("button", { name: "Increase font size" });
  await more.click();
  await more.click();
  await expect(size).toHaveText("48px");
  await expect(more).toBeDisabled();
});
