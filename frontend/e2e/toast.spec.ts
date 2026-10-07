import { test, expect } from "@playwright/test";
import { get } from "svelte/store";
import { toastStore } from "../src/lib/stores/toast";
import { ADMIN_STATE } from "./helpers";
import { seedBook } from "./ng-helpers";

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

test("a duration that is given is kept, and 0 means until dismissed", () => {
  onFakeClock((advance) => {
    toastStore.error("Short", { duration: 1000 });
    const kept = toastStore.error("Kept", { duration: 0 });
    advance(1000);
    expect(showing()).toEqual(["error: Kept"]);
    advance(600_000);
    expect(showing()).toEqual(["error: Kept"]);
    toastStore.remove(kept);
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
