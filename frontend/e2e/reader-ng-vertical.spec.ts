import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test, expect, type Page } from "@playwright/test";
import { ADMIN_STATE } from "./helpers";

/**
 * reader-ng: vertical-rl (直排) on the new engine — the two engine-agnostic
 * checks from reader-vertical.spec.ts. The paging-grid cases there are
 * about the old fork's pageStep; read-ng's geometry is covered by
 * reader-ng.spec.ts.
 */

const fixture = (name: string) =>
  path.join(path.dirname(fileURLToPath(import.meta.url)), "fixtures", name);

test.use({ storageState: ADMIN_STATE });

declare global {
  interface Window {
    __beepubReaderNG?: any;
  }
}

async function seed(page: Page, file: string, name: string) {
  const libraries = await (await page.request.get("/api/libraries")).json();
  const uploaded = await page.request.post("/api/books", {
    multipart: {
      file: {
        name: `${name}.epub`,
        mimeType: "application/epub+zip",
        buffer: fs.readFileSync(file),
      },
      library_id: libraries[0].id,
    },
  });
  expect(uploaded.ok()).toBeTruthy();
  return (await uploaded.json()).id as string;
}

async function openNg(page: Page, bookId: string, text: string, font: string) {
  await page.goto(`/books/${bookId}/read-ng?font=${font}&panel=0`);
  await page.waitForFunction(
    () => !!window.__beepubReaderNG?.core?.lastLocation,
    null,
    { timeout: 30_000 },
  );
  await expect
    .poll(() =>
      page.evaluate(
        (t) =>
          (
            window.__beepubReaderNG.core.getContents()[0].doc as Document
          ).body?.textContent?.includes(t) ?? false,
        text,
      ),
    )
    .toBe(true);
}

test("vertical book renders vertical-rl in read-ng", async ({ page }) => {
  const bookId = await seed(
    page,
    fixture("e2e-vertical-book.epub"),
    "ng-vertical",
  );
  await openNg(page, bookId, "話說天下大勢", "sans");
  const state = await page.evaluate(() => {
    const core = window.__beepubReaderNG.core;
    const doc: Document = core.getContents()[0].doc;
    return {
      vertical: core.vertical as boolean,
      bodyWritingMode: getComputedStyle(doc.body).writingMode,
      // Vertical pagination stacks pages along the block axis: the iframe
      // keeps the container's width and grows in whole container heights.
      axis: (() => {
        const frame = doc.defaultView!.frameElement as HTMLElement;
        const f = frame.getBoundingClientRect();
        const c = frame.parentElement!.parentElement!.getBoundingClientRect();
        return {
          widthMatches: Math.abs(f.width - c.width) < 1,
          pages: f.height / c.height,
        };
      })(),
    };
  });
  expect(state.vertical).toBe(true);
  expect(state.bodyWritingMode).toBe("vertical-rl");
  expect(state.axis.widthMatches).toBe(true);
  expect(
    Math.abs(state.axis.pages - Math.round(state.axis.pages)),
  ).toBeLessThan(0.01);
});

test("vertical punctuation faces reach a book that bypasses the body font stack", async ({
  page,
}) => {
  const bookId = await seed(page, fixture("e2e-vpunct-book.epub"), "ng-vpunct");
  await openNg(page, bookId, "免費服務已終止", "serif");

  const state = await page.evaluate(() => {
    const core = window.__beepubReaderNG.core;
    const doc: Document = core.getContents()[0].doc;
    const p = [...doc.querySelectorAll("p")].find((n) =>
      n.textContent?.includes("免費服務已終止"),
    ) as HTMLElement | undefined;
    const kai = doc.querySelector("span.kai") as HTMLElement | null;
    const em = doc.querySelector("em") as HTMLElement | null;
    return {
      vertical: core.vertical as boolean,
      faces: [...doc.querySelectorAll("style")]
        .map((s) => s.textContent)
        .join("\n"),
      pPin: p?.style.fontFamily ?? "",
      kaiPin: kai?.style.fontFamily ?? "",
      emPin: em?.style.fontFamily ?? "",
    };
  });

  // The -webkit-prefixed-only writing-mode still routes the vertical path.
  expect(state.vertical).toBe(true);

  // Both faces arrive in the section, and the range stays curated: it must
  // claim the bracket but not — or － (no vert forms in the subset source).
  expect(state.faces).toContain('"BeePub VPunct Serif"');
  expect(state.faces).toContain('"BeePub VPunct Sans"');
  expect(state.faces).toContain("U+FF3B");
  expect(state.faces).not.toContain("U+2014");
  expect(state.faces).not.toContain("U+FF0D");

  // `p { font-family: serif }` bypasses the body stack → pinned inline with
  // the book's own stack preserved behind the face. Same for class-declared
  // fonts. Elements that merely inherit must stay unpinned.
  expect(state.pPin).toMatch(/^"BeePub VPunct (Serif|Sans)", serif$/);
  expect(state.kaiPin).toContain("BeePub VPunct");
  expect(state.kaiPin).toContain("標楷體");
  expect(state.emPin).toBe("");

  const bracketLoaded = await page.evaluate(async () => {
    const doc: Document = window.__beepubReaderNG.core.getContents()[0].doc;
    await doc.fonts.ready;
    return doc.fonts.check('16px "BeePub VPunct Serif"', "［");
  });
  expect(bracketLoaded).toBe(true);
  const woff = await page.request.get("/fonts/beepub-vpunct-serif.woff2");
  expect(woff.ok()).toBeTruthy();
});
