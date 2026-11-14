import { test, expect } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";
import {
  NINE_CHAPTERS_BOOK,
  openBook,
  resetProgress,
  seedFixture,
} from "./ng-helpers";

/**
 * A book's scripts do not run. A chapter is shown in a frame of the
 * app's own origin, so a script in it would act as the reader — call
 * the API with their session, read what the page holds. Whatever form
 * it takes in the book (a script element, a handler attribute, a
 * `javascript:` link), it stays text.
 */

test.use({ storageState: ADMIN_STATE });
test.setTimeout(120_000);

declare global {
  interface Window {
    __ranInline?: number;
    __ranHandler?: number;
    __ranLink?: number;
  }
}

test("a script in a book — an element, a handler, a javascript: link — does not run", async ({
  page,
  request,
}) => {
  const bookId = await seedFixture(request, NINE_CHAPTERS_BOOK);
  await resetProgress(request, bookId);
  await page.route("**/api/books/*/content/**", async (route) => {
    if (!/\.xhtml$/.test(new URL(route.request().url()).pathname))
      return route.continue();
    const response = await route.fetch();
    const body = (await response.text())
      .replace("</head>", "<script>window.top.__ranInline = 1;</script></head>")
      .replace(
        "</body>",
        '<script>window.top.__ranInline = 2;</script><img id="trap" src="no-such-image" onerror="window.top.__ranHandler = 1" alt=""/><a id="link" href="javascript:void(window.top.__ranLink = 1)">x</a></body>',
      );
    await route.fulfill({ response, body });
  });
  await openBook(page, bookId, { turn: "fade" }, NINE_CHAPTERS_BOOK);

  const state = await page.evaluate(async () => {
    const doc: Document = window.__beepubReaderNG.core.getContents()[0].doc;
    (doc.getElementById("link") as HTMLElement | null)?.click();
    await new Promise((r) => setTimeout(r, 500));
    return {
      // The book's own markup is all still there: positions in it
      // (highlights, progress) count its elements.
      scripts: doc.querySelectorAll("script").length,
      trap: !!doc.getElementById("trap"),
      policy:
        doc
          .querySelector('meta[http-equiv="Content-Security-Policy"]')
          ?.getAttribute("content") ?? null,
      ran: [window.__ranInline, window.__ranHandler, window.__ranLink],
    };
  });
  expect(state.scripts).toBe(2);
  expect(state.trap).toBe(true);
  expect(state.policy).toContain("script-src 'none'");
  expect(state.ran).toEqual([undefined, undefined, undefined]);
});
