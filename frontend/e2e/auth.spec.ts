import { test, expect } from "@playwright/test";
import { ADMIN } from "./helpers";

test("logs in through the form and lands on home", async ({ page }) => {
  await page.goto("/login");
  await page.locator("#username").fill(ADMIN.username);
  await page.locator("#password").fill(ADMIN.password);
  await page.getByRole("button", { name: "Login", exact: true }).click();
  await expect(page).toHaveURL("/");
});

test("rejects a wrong password", async ({ page }) => {
  await page.goto("/login");
  await page.locator("#username").fill(ADMIN.username);
  await page.locator("#password").fill("definitely-wrong");
  await page.getByRole("button", { name: "Login", exact: true }).click();
  await expect(page).toHaveURL(/\/login/);
});
