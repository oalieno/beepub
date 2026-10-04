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

// A visitor who never picked a language gets the browser's.
for (const [browser, lang] of [
  ["zh-TW", "zh-Hant"],
  ["zh-CN", "zh-Hans"],
  ["ja-JP", "en"],
] as const) {
  test(`a ${browser} browser opens in ${lang}`, async ({ browser: b }) => {
    const context = await b.newContext({ locale: browser });
    const page = await context.newPage();
    await page.goto("/login");
    await expect(page.locator("html")).toHaveAttribute("lang", lang);
    // After hydration too: the client agrees with the server.
    await page.waitForLoadState("networkidle");
    await expect(page.locator("html")).toHaveAttribute("lang", lang);
    await context.close();
  });
}

test("a chosen language outranks the browser's", async ({ browser: b }) => {
  const context = await b.newContext({
    locale: "zh-TW",
    storageState: ADMIN_STATE,
  });
  const page = await context.newPage();
  await page.goto("/profile");
  await page.getByRole("button", { name: "語言" }).click();
  await page.getByRole("button", { name: "English" }).click();
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await context.close();
});
