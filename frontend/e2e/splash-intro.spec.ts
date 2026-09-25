import { test, expect } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";

/**
 * The launch intro: on the app (a simulated native platform, local mode so
 * no server is involved) the bee flies in over the loading app and the
 * overlay goes away on its own, letting taps through the whole time. The
 * web never shows it.
 */

test.describe("app", () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      (
        window as unknown as { CapacitorCustomPlatform: { name: string } }
      ).CapacitorCustomPlatform = { name: "ios" };
      localStorage.setItem("localMode", "1");
    });
  });

  test("the intro plays once at launch and then leaves the app", async ({
    page,
  }) => {
    await page.goto("/local");
    const intro = page.getByTestId("splash-intro");
    await expect(intro).toBeVisible();
    // The logo layers are real files.
    for (const src of ["bee-body", "bee-wing-l", "bee-wing-r"]) {
      const res = await page.request.get(`/intro/${src}.webp`);
      expect(res.ok()).toBeTruthy();
    }
    // It never takes input.
    expect(
      await intro.evaluate((el) => getComputedStyle(el).pointerEvents),
    ).toBe("none");
    await expect(intro).toHaveCount(0, { timeout: 5_000 });

    // Moving around the app does not bring it back.
    await page.evaluate(() => history.pushState({}, "", "/catalogs"));
    await page.waitForTimeout(300);
    await expect(intro).toHaveCount(0);
  });
});

test.describe("web", () => {
  test.use({ storageState: ADMIN_STATE });

  test("the web has no intro", async ({ page }) => {
    await page.goto("/");
    await page.waitForLoadState("networkidle");
    await expect(page.getByTestId("splash-intro")).toHaveCount(0);
  });
});
