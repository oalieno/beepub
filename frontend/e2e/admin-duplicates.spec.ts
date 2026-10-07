import { test, expect } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";

/**
 * The duplicates scan starts by itself when the page opens and takes a
 * while: what it came to is said on the page and stays there — a toast
 * would be gone before anyone looked. A scan that ran out of time shows
 * what it found, says that it is only part, and can be run again; one
 * that failed says so, with the same way out.
 */

test.use({ storageState: ADMIN_STATE });

const toasts = (page: import("@playwright/test").Page) =>
  page.getByTestId("toasts").locator("[role=status]");

test("a scan that ran out of time, or failed, says so on the page until it is run again", async ({
  page,
}) => {
  let answer: "partial" | "broken" | "whole" = "partial";
  let scans = 0;
  await page.route("**/api/works/suggestions", (route) => {
    scans++;
    if (answer === "broken")
      return route.fulfill({ status: 500, json: { detail: "scan blew up" } });
    return route.fulfill({
      json: {
        groups: [],
        total_books_scanned: 12,
        truncated: answer === "partial",
      },
    });
  });

  await page.goto("/admin/duplicates");
  const partial = page.getByTestId("duplicates-scan-partial");
  const failed = page.getByTestId("duplicates-scan-failed");
  await expect(partial).toContainText("only part of the results");
  await expect(toasts(page)).toHaveCount(0);
  // It does not go away by itself (a warning toast lasts six seconds).
  await page.waitForTimeout(7000);
  await expect(partial).toBeVisible();
  expect(scans).toBe(1);

  // Run again, and it fails: said in the same place.
  answer = "broken";
  await partial.getByRole("button", { name: "Scan again" }).click();
  await expect(failed).toContainText("couldn't be completed");
  await expect(failed).toContainText("scan blew up");
  await expect(partial).toHaveCount(0);
  await expect(toasts(page)).toHaveCount(0);
  expect(scans).toBe(2);

  // And again, whole this time: nothing left to say.
  answer = "whole";
  await failed.getByRole("button", { name: "Scan again" }).click();
  await expect(failed).toHaveCount(0);
  await expect(partial).toHaveCount(0);
  await expect(page.getByText("No duplicate editions found")).toBeVisible();
  expect(scans).toBe(3);
});
