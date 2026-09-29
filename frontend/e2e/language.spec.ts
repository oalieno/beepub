import { test, expect } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";

test.use({
  storageState: ADMIN_STATE,
});

test("the interface switches to Simplified Chinese and stays there", async ({
  page,
}) => {
  await page.goto("/profile");
  await page.getByRole("button", { name: "Language" }).click();
  await page.getByRole("button", { name: "简体中文" }).click();

  // setLocale reloads; the page comes back in the new language.
  await expect(page.locator("html")).toHaveAttribute("lang", "zh-Hans");
  await expect(page.getByRole("button", { name: "语言" })).toBeVisible();

  await page.goto("/");
  await expect(page.getByRole("link", { name: "书库" }).first()).toBeVisible();
});
