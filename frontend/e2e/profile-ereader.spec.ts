import { test, expect } from "@playwright/test";
import { ADMIN, ADMIN_STATE } from "./helpers";

test.use({
  storageState: ADMIN_STATE,
});

test("the profile hands out the server's OPDS and sync addresses", async ({
  page,
  baseURL,
}) => {
  const origin = baseURL!.replace(/\/$/, "");
  await page.goto("/profile");
  await page.getByRole("button", { name: "Connect an e-reader" }).click();
  await expect(page.getByText(`${origin}/opds`, { exact: true })).toBeVisible();
  await expect(
    page.getByText(`${origin}/kosync`, { exact: true }),
  ).toBeVisible();

  // The stack is plain http, like many home servers: no clipboard API,
  // so this also covers the fallback.
  const copyOpds = page.getByRole("button", { name: "Copy address" }).first();
  await copyOpds.click();
  await expect(copyOpds).toHaveAttribute("title", "Copied");
  const copied = `${origin}/opds`;

  // What was copied is a catalog an e-reader can sign in to.
  const feed = await page.request.get(copied, {
    headers: {
      Authorization: `Basic ${Buffer.from(`${ADMIN.username}:${ADMIN.password}`).toString("base64")}`,
    },
  });
  expect(feed.ok()).toBeTruthy();
  expect(await feed.text()).toContain("<feed");
});
