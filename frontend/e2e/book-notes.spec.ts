import { test, expect } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";
import { seedBook } from "./ng-helpers";

/**
 * A note that could not be saved is said where it is written: beside the
 * Done button, with the editor left open on the text — not in a toast
 * over a page that shows the note as if it had been kept. Done, pressed
 * again, tries again.
 */

test.use({ storageState: ADMIN_STATE });

test("a note that cannot be saved keeps the editor open and says so beside Done; Done again saves it", async ({
  page,
}) => {
  const bookId = await seedBook(page.request);
  const notes = `/api/books/${bookId}/notes`;
  expect(
    (await page.request.put(notes, { data: { notes: null } })).ok(),
  ).toBeTruthy();

  await page.goto(`/books/${bookId}`);
  await page.getByText("Add a private note").click();
  const box = page.getByPlaceholder("Write your notes here...");
  const state = page.getByTestId("notes-save-state");
  const done = page.getByRole("button", { name: "Done" });

  let refused = 0;
  await page.route(`**${notes}`, (route) => {
    refused++;
    return route.abort();
  });
  await box.pressSequentially("kept for later");
  await done.click();
  await expect(state).toHaveText("Couldn’t save");
  await expect(box).toBeVisible();
  await expect(box).toHaveValue("kept for later");
  expect(refused).toBeGreaterThan(0);
  await expect(
    page.getByTestId("toasts").locator("[role=status]"),
  ).toHaveCount(0);

  await page.unroute(`**${notes}`);
  await done.click();
  await expect(box).toBeHidden();
  await expect(page.getByText("kept for later")).toBeVisible();
  const saved = await (await page.request.get(`/api/books/${bookId}/interaction`)).json();
  expect(JSON.stringify(saved)).toContain("kept for later");

  await page.request.put(notes, { data: { notes: null } });
});
