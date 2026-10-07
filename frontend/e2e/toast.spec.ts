import { test, expect } from "@playwright/test";
import { get } from "svelte/store";
import { toastStore } from "../src/lib/stores/toast";
import { ADMIN_STATE } from "./helpers";
import { iphone, seedBook, swipe } from "./ng-helpers";
import type { Locator, Page } from "@playwright/test";

declare global {
  interface Window {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    __beepubToasts?: any;
    __toastActed?: number;
  }
}

/**
 * Toasts leave by themselves — errors and warnings too (they used to
 * stay until tapped: "Cannot reach the server" sat on the screen long
 * after the server was back) — and a message that is already showing is
 * not stacked a second time; it starts its time over (and shakes).
 */

/** Run `body` on a clock the test moves by hand. */
function onFakeClock(body: (advance: (ms: number) => void) => void) {
  const real = {
    setTimeout: globalThis.setTimeout,
    clearTimeout: globalThis.clearTimeout,
    now: Date.now,
  };
  let now = 1_000_000;
  let nextId = 1;
  const pending = new Map<number, { at: number; fn: () => void }>();
  globalThis.setTimeout = ((fn: () => void, ms = 0) => {
    pending.set(nextId, { at: now + ms, fn });
    return nextId++;
  }) as unknown as typeof setTimeout;
  globalThis.clearTimeout = ((id: number) => {
    pending.delete(id);
  }) as unknown as typeof clearTimeout;
  Date.now = () => now;
  try {
    body((ms) => {
      const until = now + ms;
      for (;;) {
        const due = [...pending.entries()]
          .filter(([, t]) => t.at <= until)
          .sort((a, b) => a[1].at - b[1].at)[0];
        if (!due) break;
        pending.delete(due[0]);
        now = due[1].at;
        due[1].fn();
      }
      now = until;
    });
  } finally {
    for (const t of get(toastStore)) toastStore.remove(t.id);
    globalThis.setTimeout = real.setTimeout;
    globalThis.clearTimeout = real.clearTimeout;
    Date.now = real.now;
  }
}

const showing = () => get(toastStore).map((t) => `${t.type}: ${t.message}`);

test("an error or a warning leaves by itself, later than a confirmation", () => {
  onFakeClock((advance) => {
    toastStore.info("Saved");
    toastStore.error("Cannot reach the server");
    toastStore.warning("Check the file");
    expect(showing()).toHaveLength(3);
    advance(3999);
    expect(showing()).toHaveLength(3);
    advance(1);
    expect(showing()).toEqual([
      "error: Cannot reach the server",
      "warning: Check the file",
    ]);
    advance(1999);
    expect(showing()).toHaveLength(2);
    advance(1);
    expect(showing()).toEqual([]);
  });
});

test("a long error gets its reading time, to a limit", () => {
  onFakeClock((advance) => {
    toastStore.error("x".repeat(60)); // 4 s + 60 × 60 ms
    toastStore.error("y".repeat(400));
    advance(7599);
    expect(showing()).toHaveLength(2);
    advance(1);
    expect(showing()).toHaveLength(1);
    advance(2399);
    expect(showing()).toHaveLength(1);
    advance(1);
    expect(showing()).toEqual([]);
  });
});

test("an error that offers an action stays longer, and still leaves", () => {
  onFakeClock((advance) => {
    toastStore.error("Upload failed", {
      action: { label: "Retry", onclick: () => {} },
    });
    advance(14_999);
    expect(showing()).toHaveLength(1);
    advance(1);
    expect(showing()).toEqual([]);
  });
});

test("a duration that is given is kept, and none of them means until dismissed: 0 gets the usual time", () => {
  onFakeClock((advance) => {
    toastStore.error("Short", { duration: 1000 });
    toastStore.error("Not kept", { duration: 0 });
    toastStore.info("Nor this", { duration: -1 });
    advance(1000);
    expect(showing()).toEqual(["error: Not kept", "info: Nor this"]);
    advance(3000);
    expect(showing()).toEqual(["error: Not kept"]);
    advance(2000);
    expect(showing()).toEqual([]);
  });
});

test("a message already showing is not shown twice: it starts its time over", () => {
  onFakeClock((advance) => {
    const first = toastStore.error("Cannot reach the server");
    advance(5000);
    const second = toastStore.error("Cannot reach the server");
    expect(second).toBe(first);
    expect(showing()).toEqual(["error: Cannot reach the server"]);
    // Past the first one's time, within the second's.
    advance(5999);
    expect(showing()).toHaveLength(1);
    advance(1);
    expect(showing()).toEqual([]);

    // The same words as another kind of message are another message.
    toastStore.error("Done");
    toastStore.success("Done");
    toastStore.error("Something else");
    expect(showing()).toHaveLength(3);
  });
});

test("a repeat while the pointer rests on the toast does not start the clock", () => {
  onFakeClock((advance) => {
    const id = toastStore.error("Cannot reach the server");
    advance(1000);
    toastStore.pause(id);
    toastStore.error("Cannot reach the server");
    advance(60_000);
    expect(showing()).toHaveLength(1);
    toastStore.resume(id);
    advance(5999);
    expect(showing()).toHaveLength(1);
    advance(1);
    expect(showing()).toEqual([]);
  });
});

test("a message that comes again is counted on the toast showing, and keeps what it offered", () => {
  onFakeClock(() => {
    let tried = 0;
    const id = toastStore.error("Upload failed", {
      action: { label: "Retry", onclick: () => tried++ },
      testId: "upload-failed",
    });
    expect(get(toastStore)[0].repeats ?? 0).toBe(0);
    expect(toastStore.error("Upload failed")).toBe(id);
    expect(toastStore.error("Upload failed")).toBe(id);
    const [toast] = get(toastStore);
    expect(toast.repeats).toBe(2);
    expect(toast.testId).toBe("upload-failed");
    toast.action!.onclick();
    expect(tried).toBe(1);
    // Gone and said afresh, it is a new toast.
    toastStore.remove(id);
    toastStore.error("Upload failed");
    expect(get(toastStore)[0].repeats ?? 0).toBe(0);
  });
});

test.describe("on the page", () => {
  test.use({ storageState: ADMIN_STATE });
  test.setTimeout(60_000);

  test("the same failure twice is one toast, and it goes away untouched", async ({
    page,
  }) => {
    const bookId = await seedBook(page.request);
    await page.goto(`/books/${bookId}`);
    const more = page.getByRole("button", { name: "More actions" }).first();
    await expect(more).toBeVisible();
    await page.route("**/api/books/*/favorite", (route) => route.abort());

    const toasts = page.locator(".toast-position [role=status]");
    for (let i = 0; i < 2; i++) {
      const refused = page.waitForEvent("requestfailed", (r) =>
        r.url().endsWith("/favorite"),
      );
      await more.click();
      await page.getByRole("menuitem", { name: /favorites/ }).click();
      await refused;
      await expect(toasts).toHaveText(["Cannot reach the server"]);
      await expect(toasts).toHaveAttribute("data-repeats", String(i));
    }
    await page.waitForTimeout(500);
    await expect(toasts).toHaveCount(1);

    // Nobody touches it (the pointer is parked away from it): still
    // there well into its time, gone soon after.
    await page.mouse.move(5, 5);
    await page.waitForTimeout(3500);
    await expect(toasts).toHaveCount(1);
    await expect(toasts).toHaveCount(0, { timeout: 5_000 });
  });
});

/**
 * Where the toasts are. On a phone: at the top, under the status bar,
 * dropping in from above the screen's edge (newest nearest the edge) and
 * pushed back up by a finger. From the `md` breakpoint: at the bottom,
 * centred, rising into place. In both: above whatever is open.
 */
const column = (page: Page) => page.getByTestId("toasts");
const toastsOn = (page: Page) => column(page).locator("[role=status]");

/** Raise a toast from the page (`window.__beepubToasts` is the store). */
function raise(
  page: Page,
  message: string,
  type: "success" | "error" | "info" | "warning" = "error",
  action?: string,
) {
  return page.evaluate(
    ([message, type, action]) =>
      window.__beepubToasts[type!](
        message,
        action
          ? {
              action: {
                label: action,
                onclick: () =>
                  (window.__toastActed = (window.__toastActed ?? 0) + 1),
              },
            }
          : undefined,
      ) as string,
    [message, type, action] as const,
  );
}

/** Its top edge on every frame from the moment it is raised until it has
 *  been still for a while: where it came from, and where it came to. */
function travel(page: Page, message: string) {
  return page.evaluate(
    (message) =>
      new Promise<number[]>((resolve) => {
        window.__beepubToasts.error(message);
        const tops: number[] = [];
        let still = 0;
        const frame = () => {
          const el = [
            ...document.querySelectorAll("[data-testid=toasts] [role=status]"),
          ].find((n) => n.textContent?.includes(message));
          if (el) {
            const top = el.getBoundingClientRect().top;
            still =
              tops.length && tops[tops.length - 1] === top ? still + 1 : 0;
            tops.push(top);
          }
          if (still >= 20 || tops.length > 600) resolve(tops);
          else requestAnimationFrame(frame);
        };
        requestAnimationFrame(frame);
      }),
    message,
  );
}

async function box(locator: Locator) {
  const b = await locator.boundingBox();
  expect(b).not.toBeNull();
  return { ...b!, top: b!.y, bottom: b!.y + b!.height };
}

/** The toast is what a finger at its middle would land on — and at the
 *  middle of its action, the action. */
async function topmost(page: Page, toast: Locator) {
  for (const target of [toast, toast.getByRole("button").first()]) {
    const b = await box(target);
    expect(
      await page.evaluate(
        ([x, y]) =>
          !!document
            .elementFromPoint(x, y)
            ?.closest("[data-testid=toasts] [role=status]"),
        [b.x + b.width / 2, b.y + b.height / 2],
      ),
    ).toBe(true);
  }
}

test.describe("from the md breakpoint up", () => {
  test.use({ storageState: ADMIN_STATE });

  test("a toast rises into place at the bottom, centred, the newest lowest", async ({
    page,
  }) => {
    await page.goto("/");
    await page.waitForFunction(() => !!window.__beepubToasts);
    const viewport = page.viewportSize()!;
    expect(viewport.width).toBeGreaterThanOrEqual(768);

    const tops = await travel(page, "A first thing went wrong");
    const settled = tops[tops.length - 1];
    // From below, upwards.
    expect(tops[0]).toBeGreaterThan(settled);
    expect(Math.min(...tops)).toBeGreaterThanOrEqual(settled - 0.5);

    const first = toastsOn(page).filter({ hasText: "A first thing" });
    const b = await box(first);
    expect(viewport.height - b.bottom).toBeGreaterThanOrEqual(15);
    expect(viewport.height - b.bottom).toBeLessThanOrEqual(17);
    expect(Math.abs(b.x + b.width / 2 - viewport.width / 2)).toBeLessThan(2);

    await raise(page, "A second thing went wrong");
    const second = toastsOn(page).filter({ hasText: "A second thing" });
    await expect(second).toBeVisible();
    await page.waitForTimeout(400);
    expect((await box(second)).top).toBeGreaterThan((await box(first)).bottom);
    expect(viewport.height - (await box(second)).bottom).toBeLessThanOrEqual(
      17,
    );
  });
});

test.describe("on a phone", () => {
  test.use({ storageState: ADMIN_STATE, ...iphone });

  test("a toast drops in at the top from above the screen's edge, the newest nearest the edge", async ({
    page,
  }) => {
    await page.goto("/");
    await page.waitForFunction(() => !!window.__beepubToasts);
    const viewport = page.viewportSize()!;
    expect(viewport.width).toBeLessThan(768);

    const tops = await travel(page, "A first thing went wrong");
    const settled = tops[tops.length - 1];
    // Under the status bar (no inset in a browser: the small gap alone).
    expect(settled).toBeGreaterThanOrEqual(7);
    expect(settled).toBeLessThanOrEqual(9);
    // From above the edge, downwards — and a little past its place
    // before it settles (the spring).
    expect(tops[0]).toBeLessThan(0);
    expect(Math.max(...tops)).toBeGreaterThan(settled);
    expect(Math.max(...tops)).toBeLessThan(settled + 20);

    const first = toastsOn(page).filter({ hasText: "A first thing" });
    const b = await box(first);
    expect(b.x).toBeGreaterThanOrEqual(0);
    expect(b.x + b.width).toBeLessThanOrEqual(viewport.width);
    expect(Math.abs(b.x + b.width / 2 - viewport.width / 2)).toBeLessThan(2);

    // The next one takes the top; the older moves down under it.
    await raise(page, "A second thing went wrong");
    const second = toastsOn(page).filter({ hasText: "A second thing" });
    await expect(second).toBeVisible();
    await page.waitForTimeout(600);
    expect((await box(second)).top).toBeLessThanOrEqual(9);
    expect((await box(first)).top).toBeGreaterThan((await box(second)).bottom);
  });

  test("with reduced motion it is simply there", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/");
    await page.waitForFunction(() => !!window.__beepubToasts);
    const tops = await travel(page, "A thing went wrong");
    expect(new Set(tops).size).toBe(1);
    expect(tops[0]).toBeGreaterThanOrEqual(7);
  });

  test("a finger pushes it back up and it is gone; a short push lets it settle back; a tap on its action is still a tap", async ({
    page,
    context,
  }) => {
    await page.goto("/");
    await page.waitForFunction(() => !!window.__beepubToasts);
    const cdp = await context.newCDPSession(page);

    await raise(page, "Push me away", "error", "Retry");
    const toast = toastsOn(page).filter({ hasText: "Push me away" });
    await expect(toast).toBeVisible();
    await page.waitForTimeout(600);
    const at = await box(toast);
    const from = { x: at.x + 60, y: at.y + at.height / 2 };

    // Not far enough, and slowly: it comes back to its place.
    await cdp.send("Input.dispatchTouchEvent", {
      type: "touchStart",
      touchPoints: [from],
    });
    for (const dy of [-4, -8, -12, -14]) {
      await page.waitForTimeout(120);
      await cdp.send("Input.dispatchTouchEvent", {
        type: "touchMove",
        touchPoints: [{ x: from.x, y: from.y + dy }],
      });
    }
    expect((await box(toast)).top).toBeLessThan(at.top - 8);
    await page.waitForTimeout(200);
    await cdp.send("Input.dispatchTouchEvent", {
      type: "touchEnd",
      touchPoints: [],
    });
    await expect.poll(async () => (await box(toast)).top).toBe(at.top);
    await expect(toast).toBeVisible();
    expect(await page.evaluate(() => window.__toastActed ?? 0)).toBe(0);

    // A tap on the action is the action (and takes the toast down).
    await raise(page, "Tap my action", "error", "Retry");
    const tapped = toastsOn(page).filter({ hasText: "Tap my action" });
    await page.waitForTimeout(600);
    await tapped.getByRole("button", { name: "Retry" }).tap();
    await expect(tapped).toHaveCount(0);
    expect(await page.evaluate(() => window.__toastActed)).toBe(1);

    // Pushed up: gone, long before its fifteen seconds.
    await expect(toast).toBeVisible();
    const now = await box(toast);
    const onAction = await box(toast.getByRole("button", { name: "Retry" }));
    const grip = {
      x: onAction.x + onAction.width / 2,
      y: onAction.y + onAction.height / 2,
    };
    expect(grip.y).toBeGreaterThan(now.top);
    await swipe(cdp, grip, { x: grip.x, y: grip.y - 70 });
    await expect(toast).toHaveCount(0, { timeout: 2_000 });
    // (Started on the toast's own action, a swipe is not a press of it.)
    expect(await page.evaluate(() => window.__toastActed)).toBe(1);
  });

  test("raised while a dialog is open, it is on top of it and its action can be tapped", async ({
    page,
  }) => {
    await page.goto("/");
    await page.waitForFunction(() => !!window.__beepubToasts);
    const dialog = page.getByRole("dialog");
    await expect(async () => {
      await page.keyboard.press("ControlOrMeta+k");
      await expect(dialog).toBeVisible({ timeout: 1_000 });
    }).toPass({ timeout: 15_000 });

    await raise(page, "Said over the dialog", "error", "Retry");
    const toast = toastsOn(page).filter({ hasText: "Said over the dialog" });
    await expect(toast).toBeVisible();
    await page.waitForTimeout(600);
    await topmost(page, toast);
    await toast.getByRole("button", { name: "Retry" }).tap();
    expect(await page.evaluate(() => window.__toastActed)).toBe(1);
    await expect(toast).toHaveCount(0);
    // (And the dialog it was said over is still open.)
    await expect(dialog).toBeVisible();
  });
});
