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

// A user-less server can't be produced on the seeded e2e stack, so the
// first-run status is mocked; the register/first-admin backend behavior
// itself is covered by global-setup registering the admin.
test("a fresh server shows the admin setup instead of a login form", async ({
  page,
}) => {
  await page.route("**/api/auth/registration-status", (route) =>
    route.fulfill({
      json: { registration_enabled: true, first_user: true, demo: null },
    }),
  );
  await page.goto("/login");
  await expect(page.getByText("Create the admin account")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Create account" }),
  ).toBeVisible();
  // No login/register tabs and no login submit — setup is the only path.
  await expect(page.getByRole("tab")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Login", exact: true }),
  ).toHaveCount(0);
});
