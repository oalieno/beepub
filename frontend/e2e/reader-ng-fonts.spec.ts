import { test, expect, type Page } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";
import {
  NINE_CHAPTERS_BOOK,
  openBook,
  resetProgress,
  seedFixture,
} from "./ng-helpers";

/**
 * The typeface as a setting: a Ming, a Hei and a Kai served with the
 * app, and the device's own. The one chosen leads the page's font list
 * (behind the punctuation face), its slices come from the app's own
 * origin, and the choice is kept. What an older version stored —
 * "serif", "sans-serif" — is the served face of that kind.
 */

test.use({ storageState: ADMIN_STATE });
test.setTimeout(120_000);

/** The page's font list, the served faces that have loaded in it, and
 *  what is stored. */
const typeface = (page: Page) =>
  page.evaluate(async () => {
    const doc: Document = window.__beepubReaderNG.core.getContents()[0].doc;
    await doc.fonts.ready;
    return {
      stack: getComputedStyle(doc.body).fontFamily,
      loaded: [
        ...new Set(
          [...doc.fonts]
            .filter((f) => f.status === "loaded")
            .map((f) => f.family.replace(/['"]/g, "")),
        ),
      ],
      stored: localStorage.getItem("reader-font"),
    };
  });

test("a typeface is chosen in the settings, set from the app's own files, and kept", async ({
  page,
  request,
  baseURL,
}) => {
  const bookId = await seedFixture(request, NINE_CHAPTERS_BOOK);
  await resetProgress(request, bookId);
  const elsewhere = new Set<string>();
  page.on("request", (r) => {
    const url = new URL(r.url());
    if (/\.woff2?$/.test(url.pathname) && url.host !== new URL(baseURL!).host)
      elsewhere.add(url.host);
  });
  // (No `font` in the query: the reader's own choice.)
  await openBook(page, bookId, { font: "", turn: "fade" }, NINE_CHAPTERS_BOOK);

  // Nothing stored: the Ming.
  await expect
    .poll(async () => (await typeface(page)).loaded)
    .toContain("Noto Serif TC Variable");
  expect((await typeface(page)).stack).toMatch(
    /^"BeePub VPunct Serif", "Noto Serif TC Variable"/,
  );

  await page.getByRole("button", { name: "Reader settings" }).click();
  await expect(page.getByTestId("reader-font-mincho")).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await page.getByTestId("reader-font-kai").click();
  await expect
    .poll(async () => (await typeface(page)).loaded)
    .toContain("LXGW WenKai TC");
  let now = await typeface(page);
  expect(now.stack).toMatch(/^"BeePub VPunct Serif", "LXGW WenKai TC"/);
  expect(now.stored).toBe("kai");

  // The device's own: nothing served is named.
  await page.getByTestId("reader-font-system").click();
  await expect
    .poll(async () => (await typeface(page)).stack)
    .toMatch(/^"BeePub VPunct Sans", "Noto Sans CJK TC"/);
  now = await typeface(page);
  expect(now.stack).not.toMatch(/Variable|WenKai/);
  expect(now.stored).toBe("system");

  // Kept: the book opens in it again.
  await page.reload();
  await page.waitForFunction(
    () => !!window.__beepubReaderNG?.core?.lastLocation,
    null,
    { timeout: 30_000 },
  );
  expect((await typeface(page)).stack).not.toMatch(/Variable|WenKai/);

  expect([...elsewhere]).toEqual([]);
});

test("what an older version stored is the served face of its kind", async ({
  page,
  request,
}) => {
  const bookId = await seedFixture(request, NINE_CHAPTERS_BOOK);
  await resetProgress(request, bookId);
  await page.addInitScript(() =>
    localStorage.setItem("reader-font", "sans-serif"),
  );
  await openBook(page, bookId, { font: "", turn: "fade" }, NINE_CHAPTERS_BOOK);
  await expect
    .poll(async () => (await typeface(page)).loaded)
    .toContain("Noto Sans TC Variable");
  expect((await typeface(page)).stack).toMatch(
    /^"BeePub VPunct Sans", "Noto Sans TC Variable"/,
  );
  await page.getByRole("button", { name: "Reader settings" }).click();
  await expect(page.getByTestId("reader-font-gothic")).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});

test("a book that asks for an old Ming font by name is set in the app's Ming, from the app's own files; one that does not is given nothing", async ({
  page,
  request,
  baseURL,
}) => {
  const bookId = await seedFixture(request, NINE_CHAPTERS_BOOK);
  await resetProgress(request, bookId);
  const elsewhere = new Set<string>();
  page.on("request", (r) => {
    const url = new URL(r.url());
    if (url.protocol.startsWith("http") && url.host !== new URL(baseURL!).host)
      elsewhere.add(url.host);
  });
  const legacy = () =>
    page.evaluate(async () => {
      const doc: Document = window.__beepubReaderNG.core.getContents()[0].doc;
      await doc.fonts.ready;
      return {
        linked: !!doc.querySelector('link[href*="legacy-ming"]'),
        loaded: [...doc.fonts]
          .filter((f) => f.status === "loaded")
          .map((f) => f.family.replace(/['"]/g, "")),
      };
    });

  // As the book is: no old name in it.
  await openBook(page, bookId, { turn: "fade" }, NINE_CHAPTERS_BOOK);
  expect((await legacy()).linked).toBe(false);

  // The same book, its chapters asking for 細明體 as an old export does.
  await page.route("**/api/books/*/content/**", async (route) => {
    if (!/\.xhtml$/.test(new URL(route.request().url()).pathname))
      return route.continue();
    const response = await route.fetch();
    const body = (await response.text()).replace(
      "</head>",
      '<style>p { font-family: "細明體", serif; }</style></head>',
    );
    await route.fulfill({ response, body });
  });
  await openBook(page, bookId, { turn: "fade" }, NINE_CHAPTERS_BOOK);
  await expect.poll(async () => (await legacy()).linked).toBe(true);
  await expect.poll(async () => (await legacy()).loaded).toContain("細明體");

  expect([...elsewhere]).toEqual([]);
});

test("the chosen typeface leads the fonts a book names for itself; its code stays as it is", async ({
  page,
  request,
}) => {
  const bookId = await seedFixture(request, NINE_CHAPTERS_BOOK);
  await resetProgress(request, bookId);
  // The book as most are made: its paragraphs name a font themselves.
  await page.route("**/api/books/*/content/**", async (route) => {
    if (!/\.xhtml$/.test(new URL(route.request().url()).pathname))
      return route.continue();
    const response = await route.fetch();
    const body = (await response.text())
      .replace(
        "</head>",
        "<style>p { font-family: serif; } @media all { h1, h2 { font: bold 1.4em sans-serif; } } code { font-family: monospace; }</style></head>",
      )
      .replace(
        "</body>",
        '<p id="plain">一段文字</p><p id="own" style="font-family: \'DFKai-SB\', cursive">一封信</p><code id="code">x = 1</code></body>',
      );
    await route.fulfill({ response, body });
  });
  const lists = () =>
    page.evaluate(() => {
      const doc: Document = window.__beepubReaderNG.core.getContents()[0].doc;
      const of = (el: Element | null) =>
        el ? getComputedStyle(el).fontFamily : "";
      return {
        plain: of(doc.getElementById("plain")),
        own: of(doc.getElementById("own")),
        heading: of(doc.querySelector("h1, h2")),
        code: of(doc.getElementById("code")),
      };
    });
  await openBook(page, bookId, { font: "", turn: "fade" }, NINE_CHAPTERS_BOOK);

  // The Ming first, the book's own list behind it.
  let now = await lists();
  expect(now.plain).toMatch(
    /^"BeePub VPunct Serif", "Noto Serif TC Variable", serif$/,
  );
  expect(now.own).toMatch(
    /^"BeePub VPunct Serif", "Noto Serif TC Variable", "?DFKai-SB"?, cursive$/,
  );
  if (now.heading)
    expect(now.heading).toMatch(/"Noto Serif TC Variable", sans-serif$/);
  // (Its own list — behind the punctuation face, as the book is vertical.)
  expect(now.code).toMatch(/^("BeePub VPunct Serif", )?monospace$/);

  // Another is chosen: the same paragraphs follow it.
  await page.getByRole("button", { name: "Reader settings" }).click();
  await page.getByTestId("reader-font-kai").click();
  await expect
    .poll(async () => (await lists()).plain)
    .toMatch(/^"BeePub VPunct Serif", "LXGW WenKai TC", .*serif$/);
  await expect
    .poll(async () =>
      page.evaluate(async () => {
        const doc: Document = window.__beepubReaderNG.core.getContents()[0].doc;
        await doc.fonts.ready;
        return doc.fonts.check('16px "LXGW WenKai TC"', "一段文字");
      }),
    )
    .toBe(true);

  // The device's own: the book's list, as the book has it.
  await page.getByTestId("reader-font-system").click();
  await expect
    .poll(async () => (await lists()).plain)
    .toBe('"BeePub VPunct Sans", serif');
});
