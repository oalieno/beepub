import { test, expect, type Page } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";

/** Open the global search (⌘K) and return its input. The shortcut only
 *  works once the page has hydrated, which the first load after a stack
 *  rebuild can take a moment to do: keep pressing until the modal
 *  answers. */
async function openSearch(page: Page) {
  const input = page.getByRole("dialog").getByRole("textbox");
  await expect(async () => {
    await page.keyboard.press("ControlOrMeta+k");
    await expect(input).toBeVisible({ timeout: 1_000 });
  }).toPass({ timeout: 15_000 });
  return input;
}

/** The modal's own request: the library list's endpoint, asked for a
 *  query's first twenty. (The list pages ask the same endpoint for
 *  sixty, and the home page for none with a search.) The upload is a
 *  POST to the same path; it carries no query, so asking for `search`
 *  and `limit` keeps this to the list's GET where only a URL is given. */
function isModalSearch(url: string | URL) {
  const u = new URL(url);
  return (
    u.pathname === "/api/books" &&
    u.searchParams.has("search") &&
    u.searchParams.get("limit") === "20"
  );
}
const bookPage = /\/books\/[0-9a-f-]{36}/;

/**
 * Regression for the global-search empty-state flash: debounced typing
 * keeps several book-search requests in flight, and an older
 * response finishing while a newer request still ran used to clear
 * `loading` — the modal read "not loading + no results" and flashed
 * "No books found" before the real results arrived. Stale responses may
 * touch neither the results nor the loading flag.
 */

test.use({ storageState: ADMIN_STATE });

test("a stale search response cannot flash the empty state", async ({
  page,
}) => {
  // First search request ("E2"): delayed and empty. Second ("E2E"):
  // fast, with results. The old race: the slow empty response lands
  // after the fast one started, clears loading, and the empty state
  // flashes until the fast response arrives.
  let call = 0;
  await page.route(isModalSearch, async (route) => {
    call += 1;
    if (call === 1) {
      await new Promise((r) => setTimeout(r, 1500));
      // (The modal has given this request up by now; answering it is
      // answering nobody.)
      await route
        .fulfill({
          contentType: "application/json",
          body: JSON.stringify({ items: [], total: 0 }),
        })
        .catch(() => {});
      return;
    }
    await route.continue();
  });

  await page.goto("/");
  const input = await openSearch(page);

  // Watch for any appearance of the empty state inside the modal's
  // results panel from now on (the string also exists in page content
  // behind the modal, so scope tightly).
  await page.evaluate(() => {
    const w = window as unknown as { __sawEmpty: boolean };
    w.__sawEmpty = false;
    new MutationObserver(() => {
      const panel = document.querySelector('[role="tabpanel"]');
      if (panel?.textContent?.includes("No books found")) {
        w.__sawEmpty = true;
      }
    }).observe(document.body, {
      childList: true,
      subtree: true,
      characterData: true,
    });
  });

  // The race needs request 1 (slow, empty) actually IN FLIGHT before the
  // second keystroke — a fixed debounce sleep loses under load (both
  // keystrokes coalesce into one request, which meets the slow stub and
  // the results never arrive; flaked right after e2e image rebuilds).
  const firstRequest = page.waitForRequest((r) => isModalSearch(r.url()));
  await input.fill("E2");
  await firstRequest;
  // … then type on so request 2 (fast, with results) races past it.
  // A query only the test book matches: the search ranks prefix matches
  // shorter-title-first, and the fixtures other specs upload every run
  // (the shorter "E2E 直排標點測試") pile up in this persistent database
  // until they fill the 20-result page on a bare "E2E".
  await input.fill("E2E Test");

  // The fast response's results appear …
  await expect(
    page.getByText("E2E Test Book", { exact: false }).first(),
  ).toBeVisible({ timeout: 10_000 });
  // … and stay after the stale response lands.
  await page.waitForTimeout(1500);
  await expect(
    page.getByText("E2E Test Book", { exact: false }).first(),
  ).toBeVisible();

  const sawEmpty = await page.evaluate(
    () => (window as unknown as { __sawEmpty: boolean }).__sawEmpty,
  );
  expect(sawEmpty).toBe(false);
});

/**
 * Enter submits the search; it does not pick a result. It used to open
 * the first book — at once if the results were in, or whenever a slow
 * response landed — so pressing Enter after typing threw the user into a
 * book they had not chosen. Now, with nothing selected, Enter on the
 * Books tab goes to the library's own search (all libraries) with the
 * query; on the passage tabs it runs the search and leaves the results
 * up. A result is opened only when it was picked.
 */

test("Enter with results on screen goes to the library search, not into the first book", async ({
  page,
}) => {
  await page.goto("/");
  const input = await openSearch(page);
  await input.fill("E2E Test");
  const first = page.getByRole("dialog").getByText("E2E Test Book").first();
  await expect(first).toBeVisible({ timeout: 10_000 });

  await input.press("Enter");
  // The library then writes the relevance sort it searches by into the
  // address — often before this looks.
  await expect(page).toHaveURL(
    /\/libraries\/all\?search=E2E(%20|\+)Test(&sort=relevance%3Aasc)?$/,
  );
  await expect(page.getByRole("dialog")).toBeHidden();
  await expect(page.getByPlaceholder("Search all libraries...")).toHaveValue(
    "E2E Test",
  );
  await expect(page.getByText("E2E Test Book").first()).toBeVisible();
  await page.waitForTimeout(1000);
  expect(page.url()).not.toMatch(bookPage);
});

test("Enter before a slow search answers does not open a book when the answer lands", async ({
  page,
}) => {
  const visited: string[] = [];
  page.on("framenavigated", (f) => {
    if (f === page.mainFrame()) visited.push(f.url());
  });
  await page.route(isModalSearch, async (route) => {
    await new Promise((r) => setTimeout(r, 1500));
    await route.continue().catch(() => {});
  });
  await page.goto("/");
  const input = await openSearch(page);
  const asked = page.waitForRequest((r) => isModalSearch(r.url()));
  await input.fill("E2E Test");
  await asked;
  await input.press("Enter");
  await expect(page).toHaveURL(/\/libraries\/all\?search=/);
  // Well past the slow answer.
  await page.waitForTimeout(2500);
  await expect(page).toHaveURL(/\/libraries\/all\?search=/);
  expect(visited.filter((u) => bookPage.test(u))).toEqual([]);
  await expect(page.getByPlaceholder("Search all libraries...")).toHaveValue(
    "E2E Test",
  );
});

test("from the library itself, Enter searches that list; Back returns to it as it was", async ({
  page,
}) => {
  await page.goto("/libraries/all");
  const search = page.getByPlaceholder("Search all libraries...");
  await expect(search).toHaveValue("");
  const input = await openSearch(page);
  await input.fill("E2E Test");
  const listed = page.waitForRequest(
    (r) =>
      r.method() === "GET" &&
      /\/api\/books(\/grouped)?\?/.test(r.url()) &&
      // (The list's request, not the modal's for the same words.)
      !isModalSearch(r.url()) &&
      new URL(r.url()).searchParams.get("search") === "E2E Test",
  );
  await input.press("Enter");
  await listed;
  await expect(page).toHaveURL(/\/libraries\/all\?search=/);
  await expect(search).toHaveValue("E2E Test");
  await expect(page.getByText("E2E Test Book").first()).toBeVisible();

  await page.goBack();
  await expect(page).toHaveURL(/\/libraries\/all$/);
  await expect(search).toHaveValue("");
});

test("a result picked with the arrow keys is opened by Enter", async ({
  page,
}) => {
  await page.goto("/");
  const input = await openSearch(page);
  await input.fill("E2E Test");
  await expect(
    page.getByRole("dialog").getByText("E2E Test Book").first(),
  ).toBeVisible({ timeout: 10_000 });
  await input.press("ArrowDown");
  await input.press("Enter");
  await expect(page).toHaveURL(bookPage);
  // Opening a result remembers the search that found it.
  await openSearch(page);
  await expect(
    page
      .getByRole("dialog")
      .getByRole("list", { name: "Recent searches" })
      .getByRole("listitem"),
  ).toHaveText(["E2E Test"]);
});

test("typing on aborts the search it has made pointless", async ({ page }) => {
  // Every search is slow: the first is still out when the second key
  // comes.
  await page.route(isModalSearch, async (route) => {
    await new Promise((r) => setTimeout(r, 1500));
    await route.continue().catch(() => {});
  });
  const aborted: string[] = [];
  page.on("requestfailed", (r) => {
    if (isModalSearch(r.url()))
      aborted.push(
        `${new URL(r.url()).searchParams.get("search")}: ${r.failure()?.errorText}`,
      );
  });
  await page.goto("/");
  const input = await openSearch(page);
  let asked = page.waitForRequest((r) => isModalSearch(r.url()));
  await input.fill("E2");
  await asked;
  asked = page.waitForRequest((r) => isModalSearch(r.url()));
  await input.fill("E2E Test");
  await expect.poll(() => aborted).toEqual(["E2: net::ERR_ABORTED"]);
  await asked;
  // The one that is wanted is answered …
  await expect(
    page.getByRole("dialog").getByText("E2E Test Book").first(),
  ).toBeVisible({ timeout: 10_000 });
  // … and closing the modal gives up what it is still waiting for.
  asked = page.waitForRequest((r) => isModalSearch(r.url()));
  await input.fill("E2E Te");
  await asked;
  await page.keyboard.press("Escape");
  await expect
    .poll(() => aborted)
    .toEqual(["E2: net::ERR_ABORTED", "E2E Te: net::ERR_ABORTED"]);
  // An abandoned request is not a lost connection: no error is shown.
  await expect(page.locator(".toast-position [role=status]")).toHaveCount(0);
});

test("on the passage tabs Enter runs the search and leaves the results up", async ({
  page,
}) => {
  let calls = 0;
  await page.route("**/api/search/keyword*", async (route) => {
    calls += 1;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        query: "lantern",
        total: 1,
        results: [
          {
            book_id: "00000000-0000-4000-8000-000000000001",
            book_title: "The Lantern Ledger",
            book_author: "A. Keeper",
            passage: "The lantern was lit at dusk.",
            spine_index: 0,
            char_offset_start: 0,
            char_offset_end: 28,
          },
        ],
      }),
    });
  });
  await page.goto("/");
  const start = page.url();
  const input = await openSearch(page);
  await page.getByRole("tab", { name: "Full Text" }).click();
  await input.fill("lantern");
  // Typing alone does not search here.
  await page.waitForTimeout(600);
  expect(calls).toBe(0);

  await input.press("Enter");
  const hit = page.getByRole("dialog").getByText("The Lantern Ledger");
  await expect(hit).toBeVisible();
  expect(calls).toBe(1);
  // Enter again: the results are already there; nothing is opened and
  // nothing is asked twice.
  await input.press("Enter");
  await page.waitForTimeout(600);
  await expect(hit).toBeVisible();
  expect(calls).toBe(1);
  expect(page.url()).toBe(start);
});

/**
 * The modal and the library list ask one endpoint, so what the modal
 * shows is the head of the list Enter leads to: the same books, in the
 * same order.
 */
test("the modal lists the first books of the library search, in its order", async ({
  page,
}) => {
  await page.goto("/");
  for (const q of ["E2E", "E2E Test", "test", "書"]) {
    const input = await openSearch(page);
    const answered = page.waitForResponse(
      (r) =>
        isModalSearch(r.url()) &&
        new URL(r.url()).searchParams.get("search") === q,
    );
    await input.fill(q);
    const answer = await (await answered).json();
    expect(answer.items.length, q).toBeGreaterThan(0);
    const rows = page.getByRole("dialog").locator("[role=tabpanel] > button");
    await expect(rows, q).toHaveCount(answer.items.length);
    const modalTitles = await rows.evaluateAll((els) =>
      els.map((el) => el.querySelector("p")?.textContent?.trim()),
    );

    const listed = page.waitForResponse(
      (r) =>
        r.request().method() === "GET" &&
        new URL(r.url()).pathname === "/api/books" &&
        !isModalSearch(r.url()) &&
        new URL(r.url()).searchParams.get("search") === q,
    );
    await input.press("Enter");
    const list = await (await listed).json();
    await expect(page).toHaveURL(/\/libraries\/all\?search=/);
    const cards = page.locator(".book-grid > [role=button]");
    await expect(cards, q).toHaveCount(list.items.length);
    const listTitles = await cards.evaluateAll((els) =>
      els.map((el) => el.querySelector("h3")?.textContent?.trim()),
    );
    // On screen: the same titles, in the same order …
    expect(listTitles.slice(0, modalTitles.length), q).toEqual(modalTitles);
    // … and they are the same books, not namesakes.
    expect(
      list.items.slice(0, answer.items.length).map((b: { id: string }) => b.id),
      q,
    ).toEqual(answer.items.map((b: { id: string }) => b.id));
    expect(list.total, q).toBe(answer.total);
  }
});

/**
 * Recent searches: kept per account on this device, newest first, and
 * shown under the empty input. A search is remembered when it is
 * submitted (Enter) or one of its results is opened — never while
 * typing. (Invented search terms only.)
 */

async function userId(page: Page): Promise<string> {
  const me = await page.request.get("/api/auth/me");
  expect(me.ok()).toBe(true);
  return (await me.json()).id;
}

/** Plant a history list under `key` before the app reads it. */
async function seedHistory(page: Page, key: string, terms: string[]) {
  await page.evaluate(([k, v]) => localStorage.setItem(k, v), [
    key,
    JSON.stringify(terms),
  ] as const);
}

function recentList(page: Page) {
  return page
    .getByRole("dialog")
    .getByRole("list", { name: "Recent searches" });
}

test("a search submitted with Enter is remembered; typing alone is not", async ({
  page,
}) => {
  await page.goto("/");
  let input = await openSearch(page);
  // Nothing remembered yet: the empty input shows nothing.
  await expect(recentList(page)).toHaveCount(0);

  // Typed (and searched as you type) but never submitted.
  await input.fill("marmalade orbit");
  await page.waitForTimeout(800);
  await page.keyboard.press("Escape");
  input = await openSearch(page);
  await expect(recentList(page)).toHaveCount(0);

  // Submitted.
  await input.fill("zephyr quill");
  await input.press("Enter");
  await expect(page).toHaveURL(/\/libraries\/all\?search=zephyr/);
  input = await openSearch(page);
  await expect(input).toHaveValue("");
  const list = recentList(page);
  await expect(list.getByRole("listitem")).toHaveText(["zephyr quill"]);

  // Stored under this account's own key.
  const id = await userId(page);
  const stored = await page.evaluate(
    (k) => localStorage.getItem(k),
    `search-history:${id}`,
  );
  expect(JSON.parse(stored ?? "[]")).toEqual(["zephyr quill"]);

  // A repeat, spelled differently, moves to the front with its new
  // spelling rather than appearing twice.
  await input.fill("cobalt fern");
  await input.press("Enter");
  await expect(page).toHaveURL(/search=cobalt/);
  input = await openSearch(page);
  await input.fill("Zephyr Quill");
  await input.press("Enter");
  await expect(page).toHaveURL(/search=Zephyr/);
  await openSearch(page);
  await expect(recentList(page).getByRole("listitem")).toHaveText([
    "Zephyr Quill",
    "cobalt fern",
  ]);

  // And it survives a reload.
  await page.reload();
  await openSearch(page);
  await expect(recentList(page).getByRole("listitem")).toHaveText([
    "Zephyr Quill",
    "cobalt fern",
  ]);
});

test("a recent search is run again by a click or by the keyboard", async ({
  page,
}) => {
  const asked: string[] = [];
  await page.route("**/api/search/keyword*", async (route) => {
    asked.push(new URL(route.request().url()).searchParams.get("q") ?? "");
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ query: "", total: 0, results: [] }),
    });
  });
  await page.goto("/");
  await seedHistory(page, `search-history:${await userId(page)}`, [
    "velvet comet",
    "tin harbor",
  ]);
  const input = await openSearch(page);
  await page.getByRole("tab", { name: "Full Text" }).click();
  const list = recentList(page);
  await expect(list.getByRole("listitem")).toHaveText([
    "velvet comet",
    "tin harbor",
  ]);
  // The tab's own hint is still there, under the list.
  await expect(
    page.getByRole("dialog").getByText("Type a word or phrase and press Enter"),
  ).toBeVisible();

  await list.getByRole("button", { name: "tin harbor" }).click();
  await expect(input).toHaveValue("tin harbor");
  await expect(input).toBeFocused();
  await expect.poll(() => asked).toEqual(["tin harbor"]);
  await expect(list).toHaveCount(0);

  // Back to empty: the arrows walk the list, Enter runs the pick.
  await page.getByRole("dialog").getByRole("button", { name: "Clear" }).click();
  await expect(list).toBeVisible();
  await input.press("ArrowDown");
  await input.press("ArrowDown");
  await input.press("ArrowUp");
  await input.press("Enter");
  await expect(input).toHaveValue("velvet comet");
  await expect.poll(() => asked).toEqual(["tin harbor", "velvet comet"]);
});

test("recent searches are removed one at a time or all at once, and belong to one account", async ({
  page,
}) => {
  await page.goto("/");
  const id = await userId(page);
  await seedHistory(page, `search-history:${id}`, [
    "amber lattice",
    "quiet anvil",
    "paper moth",
  ]);
  // Another account's list on the same device.
  await seedHistory(
    page,
    "search-history:00000000-0000-4000-8000-00000000beef",
    ["someone else's term"],
  );
  await openSearch(page);
  const list = recentList(page);
  await expect(list.getByRole("listitem")).toHaveText([
    "amber lattice",
    "quiet anvil",
    "paper moth",
  ]);
  await expect(
    page.getByRole("dialog").getByText("someone else's term"),
  ).toHaveCount(0);

  await list
    .getByRole("listitem")
    .filter({ hasText: "quiet anvil" })
    .getByRole("button", { name: "Remove from recent searches" })
    .click();
  await expect(list.getByRole("listitem")).toHaveText([
    "amber lattice",
    "paper moth",
  ]);

  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Clear", exact: true })
    .click();
  await expect(list).toHaveCount(0);
  await expect(page.getByText("Recent searches")).toHaveCount(0);
  const stored = await page.evaluate(
    (k) => localStorage.getItem(k),
    `search-history:${id}`,
  );
  expect(JSON.parse(stored ?? "[]")).toEqual([]);
  // The other account's list is left alone.
  const other = await page.evaluate(() =>
    localStorage.getItem("search-history:00000000-0000-4000-8000-00000000beef"),
  );
  expect(JSON.parse(other ?? "[]")).toEqual(["someone else's term"]);
});
