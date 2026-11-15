import { test, expect } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";
import { VERTICAL_BOOK, seedBook, seedFixture } from "./ng-helpers";

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
  await expect(page.getByTestId("toasts").locator("[role=status]")).toHaveCount(
    0,
  );

  await page.unroute(`**${notes}`);
  await done.click();
  await expect(box).toBeHidden();
  await expect(page.getByText("kept for later")).toBeVisible();
  const saved = await (
    await page.request.get(`/api/books/${bookId}/interaction`)
  ).json();
  expect(JSON.stringify(saved)).toContain("kept for later");

  await page.request.put(notes, { data: { notes: null } });
});

test("a note typed on one book is saved to that book when the page moves on to another", async ({
  page,
}) => {
  const first = await seedBook(page.request);
  const second = await seedFixture(page.request, VERTICAL_BOOK);
  for (const id of [first, second]) {
    await page.request.put(`/api/books/${id}/notes`, { data: { notes: null } });
  }
  const savedTo: string[] = [];
  page.on("request", (req) => {
    const hit = /\/api\/books\/([^/]+)\/notes$/.exec(
      new URL(req.url()).pathname,
    );
    if (hit && req.method() === "PUT") savedTo.push(hit[1]);
  });

  await page.goto(`/books/${first}`);
  await page.getByText("Add a private note").click();
  await page
    .getByPlaceholder("Write your notes here...")
    .pressSequentially("belongs to the first");

  // The detail page is reused from book to book (similar books, series
  // neighbours): follow a link to the second one before the save is due.
  await page.evaluate((id) => {
    const a = document.createElement("a");
    a.href = `/books/${id}`;
    a.textContent = "next";
    a.style.cssText = "position:fixed;top:0;left:0;z-index:99999";
    document.body.append(a);
    a.click();
    a.remove();
  }, second);
  await expect(page).toHaveURL(new RegExp(`/books/${second}$`));
  await expect(page.getByText("Add a private note")).toBeVisible();

  await expect.poll(() => savedTo).toContain(first);
  expect(savedTo).not.toContain(second);
  const interaction = async (id: string) =>
    JSON.stringify(
      await (await page.request.get(`/api/books/${id}/interaction`)).json(),
    );
  await expect.poll(() => interaction(first)).toContain("belongs to the first");
  expect(await interaction(second)).not.toContain("belongs to the first");
  await expect(page.getByText("belongs to the first")).toHaveCount(0);

  await page.request.put(`/api/books/${first}/notes`, {
    data: { notes: null },
  });
});
