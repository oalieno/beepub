import {
  test,
  expect,
  type APIRequestContext,
  type Page,
} from "@playwright/test";
import { ADMIN_STATE } from "./helpers";
import {
  iphone,
  location,
  marks,
  openBook,
  resetProgress,
  seedFixture,
  touchTap,
  type Fixture,
} from "./ng-helpers";

/**
 * reader-ng: short numbers stand upright in a book forced vertical
 * (tate-chu-yoko, `$lib/reader/tcy.ts`). The rendered section gets
 * `<beepub-tcy>` wrappers around short digit runs — and nothing that is
 * stored or exchanged may notice: CFIs (progress, highlights, search
 * hits), highlight text and quote context are byte-identical to what the
 * untouched document gives.
 */

test.use({ storageState: ADMIN_STATE });

/** A horizontal zh-TW novel written with ASCII numbers: a chapter whose
 *  heading is just "4", probe paragraphs (#probe, #edge, #lead, #mixed,
 *  a <pre>, a block the book itself sets vertical), then prose carrying a
 *  one- or two-digit number and a three-digit one in every paragraph. */
const DIGITS_BOOK: Fixture = {
  file: "e2e-writing-mode-digits-book.epub",
  title: "鹽田守望人夜錄",
  readyText: "鹽冊甲篇第001段",
};

/** The same prose in a book set vertical-rl on the root (rtl spine),
 *  its numbers unmarked. */
const DIGITS_VERTICAL_BOOK: Fixture = {
  file: "e2e-writing-mode-digits-vertical-book.epub",
  title: "霧燈碼頭更夫簿",
  readyText: "霧簿上卷第001段",
};

const KEY = "reader-writing-mode";
const YELLOW = "#fef08a";
const FLASH = "#fed7aa";

type Mode = "Auto" | "Horizontal" | "Vertical";

function row(page: Page) {
  return page.getByTestId("setting-writing-mode");
}

/** Pick a writing direction in the sheet and wait for the section to be
 *  laid out again (a fresh document) with the landing relocation in. */
async function pick(page: Page, mode: Mode, body: string) {
  await page.evaluate(() => {
    const doc: Document = window.__beepubReaderNG.core.getContents()[0].doc;
    (doc as unknown as { __before: boolean }).__before = true;
  });
  await page.getByRole("button", { name: "Reader settings" }).click();
  await row(page).getByRole("button", { name: mode, exact: true }).click();
  await expect(
    row(page).getByRole("button", { name: mode, exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect
    .poll(() =>
      page.evaluate(() => {
        const core = window.__beepubReaderNG.core;
        const doc: (Document & { __before?: boolean }) | undefined =
          core.getContents()[0]?.doc;
        if (!doc?.body || doc.__before) return null;
        if (core.lastLocation.range?.startContainer.ownerDocument !== doc)
          return null;
        return getComputedStyle(doc.body).writingMode;
      }),
    )
    .toBe(body);
  await page.waitForTimeout(300);
}

/** Open a book with a writing direction already chosen for it. */
async function openIn(
  page: Page,
  bookId: string,
  mode: "auto" | "horizontal" | "vertical",
  fixture: Fixture,
  overrides: Record<string, string> = {},
) {
  // Set from a page of the app rather than an init script: init scripts
  // pile up across the opens of one test.
  await page.goto("/");
  await page.evaluate(
    ([key, mode]) => {
      if (mode === "auto") localStorage.removeItem(key);
      else localStorage.setItem(key, mode);
    },
    [`${KEY}:${bookId}`, mode],
  );
  await openBook(page, bookId, { font: "sans", ...overrides }, fixture);
}

/**
 * Text-position helpers for the section documents, installed on the top
 * window. Everything is by flattened text — "character g of the body" —
 * so the same call names the same place whether or not the document
 * carries wrappers.
 */
function installHelpers(page: Page) {
  return page.addInitScript(() => {
    type Flat = { nodes: { node: Text; base: number }[]; text: string };
    const t = {
      doc(): Document {
        return window.__beepubReaderNG.core.getContents()[0].doc;
      },
      flat(root: Node): Flat {
        const doc = root.ownerDocument!;
        const walker = doc.createTreeWalker(root, NodeFilter.SHOW_TEXT);
        const nodes: Flat["nodes"] = [];
        let text = "";
        while (walker.nextNode()) {
          const node = walker.currentNode as Text;
          nodes.push({ node, base: text.length });
          text += node.nodeValue ?? "";
        }
        return { nodes, text };
      },
      /** Character g as a boundary point: named by the node holding the
       *  character, or (asEnd) by the node holding the one before. */
      point(flat: Flat, g: number, asEnd: boolean) {
        for (const { node, base } of flat.nodes) {
          const end = base + node.length;
          if (asEnd ? g > base && g <= end : g >= base && g < end)
            return { node, offset: g - base };
        }
        const last = flat.nodes[flat.nodes.length - 1].node;
        return { node: last, offset: last.length };
      },
      /** The Range of the nth occurrence of a phrase under `root`. */
      range(root: Node, phrase: string, nth = 0): Range | null {
        const flat = t.flat(root);
        let at = -1;
        for (let i = 0; i <= nth; i++) {
          at = flat.text.indexOf(phrase, at + 1);
          if (at < 0) return null;
        }
        const start = t.point(flat, at, false);
        const end = t.point(flat, at + phrase.length, true);
        const range = root.ownerDocument!.createRange();
        range.setStart(start.node, start.offset);
        range.setEnd(end.node, end.offset);
        return range;
      },
      /** Flattened offset of a boundary point under `root`. */
      offsetOf(root: Node, node: Node, offset: number): number {
        const probe = root.ownerDocument!.createRange();
        probe.selectNodeContents(root);
        probe.setEnd(node, offset);
        return probe.toString().length;
      },
    };
    (window as unknown as { __t: typeof t }).__t = t;
  });
}

declare global {
  interface Window {
    __t: any;
  }
}

/** Wrapped runs under a selector (the whole body by default), in order. */
function wrapped(page: Page, selector = "body") {
  return page.evaluate((selector) => {
    const doc: Document = window.__t.doc();
    return [...doc.querySelectorAll(`${selector} beepub-tcy`)].map(
      (el) => el.textContent,
    );
  }, selector);
}

/** Iframe-local box of a phrase's text in the section on screen: the
 *  union of its text rects (a Range's own bounding rect would add the
 *  line-high boxes of the elements it contains). */
function phraseRect(page: Page, phrase: string) {
  return page.evaluate((phrase) => {
    const doc: Document = window.__t.doc();
    const range = window.__t.range(doc.body, phrase) as Range;
    let left = Infinity;
    let top = Infinity;
    let right = -Infinity;
    let bottom = -Infinity;
    for (const { node } of window.__t.flat(doc.body).nodes as {
      node: Text;
    }[]) {
      if (!range.intersectsNode(node)) continue;
      const sub = doc.createRange();
      sub.selectNodeContents(node);
      if (node === range.startContainer) sub.setStart(node, range.startOffset);
      if (node === range.endContainer) sub.setEnd(node, range.endOffset);
      for (const r of sub.getClientRects()) {
        if (!r.width || !r.height) continue;
        left = Math.min(left, r.left);
        top = Math.min(top, r.top);
        right = Math.max(right, r.right);
        bottom = Math.max(bottom, r.bottom);
      }
    }
    return { x: left, y: top, w: right - left, h: bottom - top };
  }, phrase);
}

/** The section CFI of a phrase in the section on screen. */
function phraseCfi(page: Page, phrase: string): Promise<string> {
  return page.evaluate((phrase) => {
    const core = window.__beepubReaderNG.core;
    const doc: Document = window.__t.doc();
    return core.cfiOf(core.currentIndex(), window.__t.range(doc.body, phrase));
  }, phrase);
}

/** Whether the place a CFI names is on the page now on screen. */
function onScreen(page: Page, cfi: string) {
  return page.evaluate((cfi) => {
    const core = window.__beepubReaderNG.core;
    const doc: Document = core.getContents()[0].doc;
    const point = core.resolve(cfi)?.anchor?.(doc) as Range | null;
    const visible: Range | null = core.lastLocation.range;
    if (!point || !visible) return false;
    return visible.comparePoint(point.startContainer, point.startOffset) === 0;
  }, cfi);
}

/** The text a point CFI stands before, in the section on screen. */
function textAfter(page: Page, cfi: string, length = 12) {
  return page.evaluate(
    ([cfi, length]) => {
      const core = window.__beepubReaderNG.core;
      const doc: Document = core.getContents()[0].doc;
      const point = core.resolve(cfi as string)?.anchor?.(doc) as Range;
      const g = window.__t.offsetOf(
        doc.body,
        point.startContainer,
        point.startOffset,
      );
      return (doc.body.textContent ?? "").slice(g, g + (length as number));
    },
    [cfi, length] as const,
  );
}

function bounds(rects: { x: number; y: number; w: number; h: number }[]) {
  const x = Math.min(...rects.map((r) => r.x));
  const y = Math.min(...rects.map((r) => r.y));
  return {
    x,
    y,
    w: Math.max(...rects.map((r) => r.x + r.w)) - x,
    h: Math.max(...rects.map((r) => r.y + r.h)) - y,
  };
}

function expectSameBox(
  a: { x: number; y: number; w: number; h: number },
  b: { x: number; y: number; w: number; h: number },
) {
  expect(Math.abs(a.x - b.x)).toBeLessThanOrEqual(2);
  expect(Math.abs(a.y - b.y)).toBeLessThanOrEqual(2);
  expect(Math.abs(a.w - b.w)).toBeLessThanOrEqual(2);
  expect(Math.abs(a.h - b.h)).toBeLessThanOrEqual(2);
}

interface Row {
  id: string;
  cfi_range: string;
  text: string;
  prefix: string | null;
  suffix: string | null;
  section_index: number | null;
}

async function clearHighlights(request: APIRequestContext, bookId: string) {
  const rows: Row[] = await (
    await request.get(`/api/books/${bookId}/highlights`)
  ).json();
  for (const h of rows) {
    const res = await request.delete(`/api/books/${bookId}/highlights/${h.id}`);
    expect(res.ok()).toBeTruthy();
  }
}

/** Drag-select a phrase with the mouse, along the line of text, and save
 *  it from the selection menu. Resolves to the stored row. */
async function highlightByDrag(page: Page, phrase: string): Promise<Row> {
  const ends = await page.evaluate((phrase) => {
    const doc: Document = window.__t.doc();
    const frame = (
      doc.defaultView!.frameElement as HTMLElement
    ).getBoundingClientRect();
    const vertical = getComputedStyle(doc.body).writingMode.startsWith("v");
    const box = (text: string, nth: number) => {
      // The first and the last character of the phrase.
      const whole = window.__t.range(doc.body, phrase) as Range;
      const flat = window.__t.flat(doc.body);
      const g =
        window.__t.offsetOf(doc.body, whole.startContainer, whole.startOffset) +
        nth;
      const s = window.__t.point(flat, g, false);
      const e = window.__t.point(flat, g + text.length, true);
      const r = doc.createRange();
      r.setStart(s.node, s.offset);
      r.setEnd(e.node, e.offset);
      return r.getBoundingClientRect();
    };
    const first = box(phrase[0], 0);
    const last = box(phrase[phrase.length - 1], phrase.length - 1);
    const from = vertical
      ? { x: first.left + first.width / 2, y: first.top + 1 }
      : { x: first.left + 1, y: first.top + first.height / 2 };
    const to = vertical
      ? { x: last.left + last.width / 2, y: last.bottom - 1 }
      : { x: last.right - 1, y: last.top + last.height / 2 };
    return {
      from: { x: frame.left + from.x, y: frame.top + from.y },
      to: { x: frame.left + to.x, y: frame.top + to.y },
    };
  }, phrase);
  await page.mouse.move(ends.from.x, ends.from.y);
  await page.mouse.down();
  await page.mouse.move(
    (ends.from.x + ends.to.x) / 2,
    (ends.from.y + ends.to.y) / 2,
    { steps: 4 },
  );
  await page.mouse.move(ends.to.x, ends.to.y, { steps: 4 });
  await page.mouse.up();
  return saveFromMenu(page);
}

/** Select a range given as flattened offsets within an element — the way
 *  a selection that starts or ends inside a number comes about — and save
 *  it from the selection menu. */
async function highlightByOffsets(
  page: Page,
  selector: string,
  phrase: string,
  startShift: number,
  endShift: number,
): Promise<Row> {
  await page.evaluate(
    ([selector, phrase, startShift, endShift]) => {
      const doc: Document = window.__t.doc();
      const root = doc.querySelector(selector as string)!;
      const flat = window.__t.flat(root);
      const at = flat.text.indexOf(phrase as string);
      const s = window.__t.point(flat, at + (startShift as number), false);
      const e = window.__t.point(
        flat,
        at + (phrase as string).length + (endShift as number),
        true,
      );
      const range = doc.createRange();
      range.setStart(s.node, s.offset);
      range.setEnd(e.node, e.offset);
      const sel = doc.defaultView!.getSelection()!;
      sel.removeAllRanges();
      sel.addRange(range);
      doc.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
    },
    [selector, phrase, startShift, endShift] as const,
  );
  return saveFromMenu(page);
}

async function saveFromMenu(page: Page): Promise<Row> {
  const menu = page.getByTestId("highlight-menu");
  await expect(menu).toBeVisible();
  const created = page.waitForResponse(
    (r) => r.request().method() === "POST" && r.url().endsWith("/highlights"),
  );
  await menu.getByTitle("Highlight", { exact: true }).click();
  const res = await created;
  expect(res.ok()).toBeTruthy();
  await expect(menu).toBeHidden();
  return res.json();
}

const stored = (r: Row) => ({
  cfi_range: r.cfi_range,
  text: r.text,
  prefix: r.prefix,
  suffix: r.suffix,
  section_index: r.section_index,
});

test.describe("upright numbers in a book forced vertical", () => {
  test.beforeEach(async ({ page }) => {
    await installHelpers(page);
    for (const fixture of [DIGITS_BOOK, DIGITS_VERTICAL_BOOK]) {
      const id = await seedFixture(page.request, fixture);
      await resetProgress(page.request, id);
    }
  });

  test.afterEach(async ({ page }) => {
    for (const fixture of [DIGITS_BOOK, DIGITS_VERTICAL_BOOK]) {
      const id = await seedFixture(page.request, fixture);
      await resetProgress(page.request, id);
      await clearHighlights(page.request, id);
    }
  });

  test("one- and two-digit numbers are wrapped and stand upright; longer numbers, figures and Latin stay on their side", async ({
    page,
  }) => {
    const bookId = await seedFixture(page.request, DIGITS_BOOK);
    await openIn(page, bookId, "vertical", DIGITS_BOOK);

    // Which runs are combined, paragraph by paragraph.
    expect(await wrapped(page, "#head")).toEqual(["4"]);
    // 第4夜 and 第12夜; not 2024, 3.14, 12:30, A4, 50%, "Chapter 6", No.8.
    expect(await wrapped(page, "#probe")).toEqual(["4", "12"]);
    // A run at the very start and at the very end of a text node.
    expect(await wrapped(page, "#edge")).toEqual(["7", "9"]);
    expect(await wrapped(page, "#lead")).toEqual(["5"]);
    // 註<sup>1</sup>, (3) and ［14］; not x<sup>2</sup>, <b>B</b>5, the
    // ruby annotation, the book's own tcy span or <code>.
    expect(await wrapped(page, "#mixed")).toEqual(["1", "3", "14"]);
    expect(await wrapped(page, "pre")).toEqual([]);
    // Text the book itself sets vertical is the publisher's to mark up.
    expect(await wrapped(page, "#own")).toEqual([]);
    // Prose: 第1夜 … 共17擔 are, 第001段 is not.
    const prose = await page.evaluate(() => {
      const doc: Document = window.__t.doc();
      const p = [...doc.querySelectorAll("p")].find((p) =>
        p.textContent!.includes("甲篇第037段"),
      )!;
      return {
        runs: [...p.querySelectorAll("beepub-tcy")].map((e) => e.textContent),
        text: p.textContent,
      };
    });
    expect(prose.runs).toEqual(["37", "89"]);
    expect(prose.text).toContain("第037段。第37夜");

    // Upright: combined into one cell of the line. A vertical line runs
    // down the page, so a run's extent along the line is its height —
    // one em for a combined run however many digits it has, where the
    // digits of a sideways run each add their advance.
    const geometry = await page.evaluate(() => {
      const doc: Document = window.__t.doc();
      const win = doc.defaultView!;
      const probe = doc.getElementById("probe")!;
      const em = parseFloat(win.getComputedStyle(probe).fontSize);
      const run = (el: Element) => {
        const range = doc.createRange();
        range.selectNodeContents(el);
        const rects = [...range.getClientRects()];
        const style = win.getComputedStyle(el);
        return {
          text: el.textContent,
          rects: rects.length,
          w: rects[0].width,
          h: rects[0].height,
          combine: style.getPropertyValue("text-combine-upright"),
          mode: style.writingMode,
        };
      };
      const sideways = (text: string) => {
        const r = (window.__t.range(probe, text) as Range).getClientRects()[0];
        return { w: r.width, h: r.height };
      };
      const head = doc.querySelector("#head beepub-tcy")!;
      return {
        em,
        headEm: parseFloat(win.getComputedStyle(head).fontSize),
        head: run(head),
        runs: [...probe.querySelectorAll("beepub-tcy")].map(run),
        year: sideways("2024"),
        word: sideways("Heron"),
        cjk: sideways("夜"),
      };
    });
    for (const [run, em] of [
      [geometry.head, geometry.headEm],
      [geometry.runs[0], geometry.em],
      [geometry.runs[1], geometry.em],
    ] as const) {
      expect(run.combine).toBe("all");
      expect(run.mode).toBe("vertical-rl");
      expect(run.rects).toBe(1);
      // One character cell: an em along the line, no wider than one.
      expect(Math.abs(run.h - em)).toBeLessThanOrEqual(1.5);
      expect(run.w).toBeGreaterThan(em * 0.3);
      expect(run.w).toBeLessThanOrEqual(em + 1.5);
    }
    // The same cell a CJK character takes along the line.
    expect(Math.abs(geometry.runs[1].h - geometry.cjk.h)).toBeLessThanOrEqual(
      1.5,
    );
    // Sideways runs lie along the line: four digits, five letters long.
    expect(geometry.year.h).toBeGreaterThan(geometry.em * 1.8);
    expect(geometry.word.h).toBeGreaterThan(geometry.em * 2);
  });

  test("Auto and Horizontal render the untouched document, and a book set vertical by itself is never wrapped", async ({
    page,
  }) => {
    const bookId = await seedFixture(page.request, DIGITS_BOOK);
    const markup = () =>
      page.evaluate(() => (window.__t.doc() as Document).body.innerHTML);
    const pristine = () =>
      page.evaluate(async () => {
        const core = window.__beepubReaderNG.core;
        const doc: Document = await core.pristineDocument(core.currentIndex());
        return doc.body.innerHTML;
      });

    await openIn(page, bookId, "auto", DIGITS_BOOK);
    expect(await wrapped(page)).toEqual([]);
    const own = await markup();
    // The rendered body is the parsed file's, element for element.
    expect(own).toBe(await pristine());

    await pick(page, "Horizontal", "horizontal-tb");
    expect(await wrapped(page)).toEqual([]);
    expect(await markup()).toBe(own);

    await pick(page, "Vertical", "vertical-rl");
    expect((await wrapped(page)).length).toBeGreaterThan(100);
    // Wrappers add elements, never characters.
    expect(
      await page.evaluate(
        () => (window.__t.doc() as Document).body.textContent,
      ),
    ).toBe(
      await page.evaluate(async () => {
        const core = window.__beepubReaderNG.core;
        const doc: Document = await core.pristineDocument(core.currentIndex());
        return doc.body.textContent;
      }),
    );

    // They go with the mode.
    await pick(page, "Horizontal", "horizontal-tb");
    expect(await wrapped(page)).toEqual([]);
    expect(await markup()).toBe(own);
    await pick(page, "Auto", "horizontal-tb");
    expect(await wrapped(page)).toEqual([]);
    expect(await markup()).toBe(own);

    // A natively vertical book, in Auto and with Vertical chosen on top.
    const verticalId = await seedFixture(page.request, DIGITS_VERTICAL_BOOK);
    await openIn(page, verticalId, "auto", DIGITS_VERTICAL_BOOK);
    expect(await wrapped(page)).toEqual([]);
    expect(await markup()).toContain("第12夜");
    await pick(page, "Vertical", "vertical-rl");
    expect(
      await page.evaluate(() =>
        window.__beepubReaderNG.core.forcedWritingMode(),
      ),
    ).toBe("vertical");
    expect(await wrapped(page)).toEqual([]);
    expect(await markup()).toContain("第12夜");
  });

  test("every position gives the same CFI with and without the wrappers, and every CFI resolves to the same character", async ({
    page,
  }) => {
    test.setTimeout(120_000);
    const bookId = await seedFixture(page.request, DIGITS_BOOK);

    // Named places in one paragraph, read in the untouched layout first:
    // before a wrapped run, inside it, and after it.
    const places = (page: Page) =>
      page.evaluate(() => {
        const core = window.__beepubReaderNG.core;
        const doc: Document = window.__t.doc();
        const probe = doc.getElementById("probe")!;
        const flat = window.__t.flat(probe);
        const at = (text: string, shift: number, asEnd: boolean) => {
          const p = window.__t.point(
            flat,
            flat.text.indexOf(text) + shift,
            asEnd,
          );
          const range = doc.createRange();
          range.setStart(p.node, p.offset);
          range.collapse(true);
          return [
            core.cfiOf(0, range) as string,
            core.positionCFI(0, range) as string,
          ];
        };
        const out: Record<string, string[]> = {};
        for (const asEnd of [false, true]) {
          const k = asEnd ? "/end" : "";
          out[`before${k}`] = at("守望人在第4夜", 0, asEnd);
          out[`just before 4${k}`] = at("4夜點燈", 0, asEnd);
          out[`just after 4${k}`] = at("4夜點燈", 1, asEnd);
          out[`just before 12${k}`] = at("12夜才熄", 0, asEnd);
          out[`inside 12${k}`] = at("12夜才熄", 1, asEnd);
          out[`just after 12${k}`] = at("12夜才熄", 2, asEnd);
          out[`after${k}`] = at("才熄。那是", 0, asEnd);
        }
        // Ranges across, onto and off a run.
        const range = (text: string) =>
          core.cfiOf(0, window.__t.range(probe, text)) as string;
        out.ranges = [
          "在第4夜點燈",
          "夜點燈",
          "到第12",
          "12",
          "4",
          "2夜才",
          "第4夜點燈，到第12夜才熄",
        ].map(range);
        // The whitespace a paragraph opens on, ahead of a wrapped run.
        const lead = doc.getElementById("lead")!;
        const open = doc.createRange();
        open.setStart(window.__t.flat(lead).nodes[0].node, 0);
        open.collapse(true);
        out.lead = [core.cfiOf(0, open), core.positionCFI(0, open)];
        return out;
      });

    await openIn(page, bookId, "auto", DIGITS_BOOK);
    expect(await wrapped(page)).toEqual([]);
    const plain = await places(page);
    // The saved-position rule skips the opening whitespace onto the "5".
    expect(plain.lead[0]).not.toBe(plain.lead[1]);
    expect(plain["inside 12"][0]).toMatch(/:\d+\)$/);

    await pick(page, "Vertical", "vertical-rl");
    expect(await wrapped(page, "#probe")).toEqual(["4", "12"]);
    expect(await places(page)).toEqual(plain);

    // The whole section, character by character, against the parsed file
    // (the document a reader without the feature renders): every spelling
    // of every position in the wrapped document gives the CFI the
    // untouched one gives, and that CFI resolves back onto the same
    // character.
    const sweep = await page.evaluate(async () => {
      const core = window.__beepubReaderNG.core;
      const index: number = core.currentIndex();
      const live: Document = window.__t.doc();
      const file: Document = await core.pristineDocument(index);
      const a = window.__t.flat(live.body);
      const b = window.__t.flat(file.body);
      const fail: string[] = [];
      const note = (what: string, g: number, x: unknown, y: unknown) => {
        if (fail.length < 12) fail.push(`${what} @${g}: ${x} ≠ ${y}`);
      };
      const collapsed = (doc: Document, node: Node, offset: number) => {
        const r = doc.createRange();
        r.setStart(node, offset);
        r.collapse(true);
        return r;
      };
      let points = 0;
      let onPieces = 0;
      let onWrappers = 0;
      let i = 0;
      for (const { node: whole, base } of b.nodes) {
        // The pieces of this text node in the rendered document.
        const parts: typeof a.nodes = [];
        while (i < a.nodes.length && a.nodes[i].base < base + whole.length)
          parts.push(a.nodes[i++]);
        if (!whole.length) continue;
        for (let o = 0; o <= whole.length; o++) {
          const g = base + o;
          const want = core.cfiOf(index, collapsed(file, whole, o));
          const wantPosition = core.positionCFI(
            index,
            collapsed(file, whole, o),
          );
          for (const part of parts) {
            const at = g - part.base;
            if (at < 0 || at > part.node.length) continue;
            const spellings: [Node, number][] = [[part.node, at]];
            const parent = part.node.parentElement!;
            if (parent.localName === "beepub-tcy") {
              if (at === 0) spellings.push([parent, 0]);
              if (at === part.node.length) spellings.push([parent, 1]);
              onWrappers += spellings.length - 1;
            }
            for (const [n, k] of spellings) {
              points++;
              if (parts.length > 1) onPieces++;
              const got = core.cfiOf(index, collapsed(live, n, k));
              if (got !== want) note("cfi", g, got, want);
              const position = core.positionCFI(index, collapsed(live, n, k));
              if (position !== wantPosition)
                note("position", g, position, wantPosition);
            }
          }
          // Back again: the CFI names character g in the rendered copy,
          // by the node that holds it.
          const back = core.resolve(want)?.anchor?.(live) as Range;
          const landed = window.__t.offsetOf(
            live.body,
            back.startContainer,
            back.startOffset,
          );
          if (landed !== g) note("resolve", g, landed, g);
          if (o < whole.length) {
            const ch = back.startContainer.nodeValue?.[back.startOffset];
            if (ch !== whole.nodeValue![o]) note("char", g, ch, whole.data[o]);
          }
        }
      }
      // Ranges over every run: across it, onto it, off it, and (for two
      // digits) from inside it.
      let ranges = 0;
      const span = (flat: typeof a, from: number, to: number) => {
        const s = window.__t.point(flat, from, false);
        const e = window.__t.point(flat, to, true);
        const r = s.node.ownerDocument!.createRange();
        r.setStart(s.node, s.offset);
        r.setEnd(e.node, e.offset);
        return r;
      };
      for (const el of live.querySelectorAll("beepub-tcy")) {
        const text = el.firstChild as Text;
        const g = a.nodes.find((n: { node: Text }) => n.node === text)!.base;
        const end = g + text.length;
        const home = b.nodes.find(
          (n: { node: Text; base: number }) =>
            n.base <= g && g < n.base + n.node.length,
        )!;
        const lo = Math.max(home.base, g - 3);
        const hi = Math.min(home.base + home.node.length, end + 3);
        const pairs = [
          [lo, hi],
          [lo, g],
          [lo, end],
          [g, end],
          [g, hi],
          [end, hi],
          [g + 1, hi],
          [lo, end - 1],
        ].filter(([from, to]) => from < to);
        for (const [from, to] of pairs) {
          ranges++;
          const x = span(a, from, to);
          const y = span(b, from, to);
          const got = core.cfiOf(index, x);
          const want = core.cfiOf(index, y);
          if (got !== want) note("range", from, got, want);
          if (String(x) !== String(y)) note("text", from, x, y);
          const back = core.resolve(want)?.anchor?.(live) as Range;
          if (String(back) !== String(y)) note("range text", from, back, y);
        }
      }
      return {
        fail,
        points,
        onPieces,
        onWrappers,
        ranges,
        same: a.text === b.text,
      };
    });
    expect(sweep.same).toBe(true);
    expect(sweep.fail).toEqual([]);
    expect(sweep.points).toBeGreaterThan(5000);
    expect(sweep.onPieces).toBeGreaterThan(3000);
    expect(sweep.onWrappers).toBeGreaterThan(200);
    expect(sweep.ranges).toBeGreaterThan(600);

    // And on the page: going to a place before, inside and after a run
    // lands on it, and what the reader then reports as its position is a
    // CFI of the untouched document.
    const targets = await page.evaluate(() => {
      const core = window.__beepubReaderNG.core;
      const doc: Document = window.__t.doc();
      const p = [...doc.querySelectorAll("p")].find((p) =>
        p.textContent!.includes("甲篇第037段"),
      )!;
      const flat = window.__t.flat(p);
      // 鹽冊甲篇第037段。第37夜，… — "37" is characters 11 and 12.
      return [0, 11, 12, 13, 20].map((g) => {
        const at = window.__t.point(flat, g, false);
        const r = doc.createRange();
        r.setStart(at.node, at.offset);
        r.collapse(true);
        return core.cfiOf(0, r) as string;
      });
    });
    expect(await textAfter(page, targets[1], 3)).toBe("37夜");
    expect(await textAfter(page, targets[2], 2)).toBe("7夜");
    for (const cfi of targets) {
      await page.evaluate((cfi) => window.__beepubReaderNG.core.goTo(cfi), cfi);
      await expect.poll(() => onScreen(page, cfi)).toBe(true);
      expect((await location(page)).fraction).toBeGreaterThan(0);
      const reported = await page.evaluate(async () => {
        const core = window.__beepubReaderNG.core;
        const { startCfi, range } = core.lastLocation;
        const live: Document = window.__t.doc();
        const file: Document = await core.pristineDocument(0);
        const point = (doc: Document) =>
          core.resolve(startCfi).anchor(doc) as Range;
        const offset = (doc: Document) => {
          const r = point(doc);
          return window.__t.offsetOf(doc.body, r.startContainer, r.startOffset);
        };
        return {
          live: offset(live),
          file: offset(file),
          // The page starts where the reported position says.
          visible: window.__t.offsetOf(
            live.body,
            range.startContainer,
            range.startOffset,
          ),
        };
      });
      expect(reported.live).toBe(reported.file);
      expect(reported.live).toBeGreaterThanOrEqual(reported.visible);
      expect(reported.live - reported.visible).toBeLessThan(8);
    }
  });

  test("a highlight made in Auto is painted on the same text once the book is forced vertical", async ({
    page,
  }) => {
    const bookId = await seedFixture(page.request, DIGITS_BOOK);
    await openIn(page, bookId, "auto", DIGITS_BOOK);
    // Across two runs; exactly one run; text that only touches a run.
    const phrases = ["第4夜點燈，到第12夜才熄", "17", "擔鹽，說：「這盞燈"];
    for (const phrase of phrases) {
      const cfi = await phraseCfi(page, phrase);
      const created = await page.request.post(
        `/api/books/${bookId}/highlights`,
        { data: { cfi_range: cfi, text: phrase, color: "yellow" } },
      );
      expect(created.ok()).toBeTruthy();
    }
    const rows: Row[] = await (
      await page.request.get(`/api/books/${bookId}/highlights`)
    ).json();
    const byText = (phrase: string) => rows.find((r) => r.text === phrase)!;

    const check = async () => {
      await expect.poll(async () => (await marks(page)).length).toBe(3);
      // Each phrase has exactly one mark, on its text.
      const all = await marks(page);
      expect(all.every((m) => m.fill === YELLOW)).toBe(true);
      const boxes = all.map((m) => bounds(m.rects));
      for (const phrase of phrases) {
        const word = await phraseRect(page, phrase);
        const match = boxes.filter(
          (b) =>
            Math.abs(b.x - word.x) <= 2 &&
            Math.abs(b.y - word.y) <= 2 &&
            Math.abs(b.w - word.w) <= 2 &&
            Math.abs(b.h - word.h) <= 2,
        );
        expect(match, phrase).toHaveLength(1);
        // The layer's Range for the row reads the highlighted text.
        expect(
          await page.evaluate((cfi) => {
            const core = window.__beepubReaderNG.core;
            const doc: Document = window.__t.doc();
            return String(core.resolve(cfi).anchor(doc));
          }, byText(phrase).cfi_range),
        ).toBe(phrase);
      }
    };

    await openIn(page, bookId, "auto", DIGITS_BOOK);
    await check();

    await pick(page, "Vertical", "vertical-rl");
    expect(await wrapped(page, "#probe")).toEqual(["4", "12"]);
    await check();
    // The mark on a lone combined run is the run's own cell.
    const cell = await page.evaluate(() => {
      const doc: Document = window.__t.doc();
      const el = (window.__t.range(doc.body, "17") as Range).startContainer
        .parentElement!;
      const r = el.getBoundingClientRect();
      return {
        tag: el.localName,
        em: parseFloat(getComputedStyle(el).fontSize),
        box: { x: r.left, y: r.top, w: r.width, h: r.height },
      };
    });
    expect(cell.tag).toBe("beepub-tcy");
    const word = await phraseRect(page, "17");
    const mark = (await marks(page))
      .map((m) => bounds(m.rects))
      .find((b) => Math.abs(b.x - word.x) <= 2 && Math.abs(b.y - word.y) <= 2)!;
    expect(mark.w).toBeGreaterThan(cell.em * 0.5);
    expect(mark.w).toBeLessThanOrEqual(cell.em + 2);
    expect(Math.abs(mark.h - cell.em)).toBeLessThanOrEqual(2);
    expect(mark.x).toBeGreaterThanOrEqual(cell.box.x - 1);
    expect(mark.x + mark.w).toBeLessThanOrEqual(cell.box.x + cell.box.w + 1);
    expect(mark.y).toBeGreaterThanOrEqual(cell.box.y - 1);
    expect(mark.y + mark.h).toBeLessThanOrEqual(cell.box.y + cell.box.h + 1);

    await pick(page, "Auto", "horizontal-tb");
    await check();
  });

  test("a highlight made under forced vertical stores what the same selection stores in Auto, and survives the switch back", async ({
    page,
  }) => {
    const bookId = await seedFixture(page.request, DIGITS_BOOK);
    // Dragged with the mouse: containing a run, starting right after
    // one, ending right on one.
    const dragged = ["在第4夜點燈", "夜才熄", "到第12"];
    // Set as a selection: starting inside "12" (word snapping grows it to
    // the whole number either way), and ending inside it.
    const inside: [string, number, number][] = [
      ["12夜才熄", 1, 0],
      ["，到第12", 0, -1],
    ];
    const collect = async (mode: "auto" | "vertical") => {
      const rows: Row[] = [];
      for (const phrase of dragged) {
        await clearHighlights(page.request, bookId);
        await openIn(page, bookId, mode, DIGITS_BOOK);
        expect((await wrapped(page, "#probe")).length).toBe(
          mode === "vertical" ? 2 : 0,
        );
        rows.push(await highlightByDrag(page, phrase));
      }
      for (const [phrase, startShift, endShift] of inside) {
        await clearHighlights(page.request, bookId);
        await openIn(page, bookId, mode, DIGITS_BOOK);
        rows.push(
          await highlightByOffsets(
            page,
            "#probe",
            phrase,
            startShift,
            endShift,
          ),
        );
      }
      return rows;
    };

    const plain = await collect("auto");
    expect(plain.map((r) => r.text)).toEqual([
      "在第4夜點燈",
      "夜才熄",
      "到第12",
      "12夜才熄",
      "，到第12",
    ]);
    // The quote context reads through the numbers.
    expect(plain[1].prefix).toMatch(/到第12$/);
    expect(plain[2].suffix).toMatch(/^夜才熄。那是2024年/);

    const upright = await collect("vertical");
    expect(upright.map(stored)).toEqual(plain.map(stored));

    // The last one made under forced vertical: drawn there, and still on
    // its text back in Auto and in Horizontal.
    const last = upright[upright.length - 1];
    const drawn = async () => {
      await expect.poll(async () => (await marks(page)).length).toBe(1);
      expectSameBox(
        bounds((await marks(page))[0].rects),
        await phraseRect(page, last.text),
      );
    };
    await drawn();
    await pick(page, "Auto", "horizontal-tb");
    expect(await wrapped(page)).toEqual([]);
    await drawn();
    await pick(page, "Vertical", "vertical-rl");
    await drawn();
    // Its menu opens on it as the saved highlight it is.
    const rows: Row[] = await (
      await page.request.get(`/api/books/${bookId}/highlights`)
    ).json();
    expect(rows.map(stored)).toEqual([stored(last)]);
  });

  test("search finds a phrase that spans a wrapped run and lands on it", async ({
    page,
  }) => {
    const bookId = await seedFixture(page.request, DIGITS_BOOK);
    await openIn(page, bookId, "vertical", DIGITS_BOOK);
    // 037 stays sideways, 37 is wrapped.
    const phrase = "甲篇第037段。第37夜，";
    expect(await onScreen(page, await phraseCfi(page, phrase))).toBe(false);

    await page.getByRole("button", { name: "Search in Book" }).click();
    const dialog = page.getByRole("dialog", { name: "Search in Book" });
    await dialog.getByRole("textbox").fill(phrase);
    await expect(dialog).toContainText("1 results");
    await dialog.getByRole("button").filter({ hasText: "第37夜" }).click();
    await expect(dialog).toBeHidden();

    await expect
      .poll(async () => (await marks(page)).some((m) => m.fill === FLASH))
      .toBe(true);
    expect(await wrapped(page, "#probe")).toEqual(["4", "12"]);
    expect(await onScreen(page, await phraseCfi(page, phrase))).toBe(true);
    // The flash covers the phrase, wrapped run included.
    const flash = (await marks(page)).find((m) => m.fill === FLASH)!;
    expectSameBox(bounds(flash.rects), await phraseRect(page, phrase));
    await expect
      .poll(async () => (await marks(page)).some((m) => m.fill === FLASH), {
        timeout: 6_000,
      })
      .toBe(false);

    // A number on its own is found as well, run by run.
    await page.getByRole("button", { name: "Search in Book" }).click();
    await dialog.getByRole("textbox").fill("第12夜才熄");
    await expect(dialog).toContainText("1 results");
  });

  test("progress saved under forced vertical restores to the same place in Auto", async ({
    page,
  }) => {
    const bookId = await seedFixture(page.request, DIGITS_BOOK);
    await openIn(page, bookId, "vertical", DIGITS_BOOK);
    const saved = page.waitForResponse(
      (r) => r.request().method() === "PUT" && r.url().endsWith("/progress"),
      { timeout: 10_000 },
    );
    // A forced vertical book turns leftward.
    for (let i = 0; i < 3; i++) {
      const before = (await location(page)).fraction;
      await page.keyboard.press("ArrowLeft");
      await expect
        .poll(async () => (await location(page)).fraction)
        .toBeGreaterThan(before);
      await page.waitForTimeout(250);
    }
    expect((await saved).ok()).toBeTruthy();
    const here = await page.evaluate(
      () => window.__beepubReaderNG.core.lastLocation.startCfi as string,
    );
    const saving = await (
      await page.request.get(`/api/books/${bookId}/progress`)
    ).json();
    expect(saving.cfi).toBe(here);
    const text = await textAfter(page, here);
    expect(text.length).toBe(12);
    // The stored position is one the parsed file gives for that text: it
    // resolves there onto the same words, and reads back as itself.
    const inFile = await page.evaluate(async (cfi) => {
      const core = window.__beepubReaderNG.core;
      const file: Document = await core.pristineDocument(0);
      const point = core.resolve(cfi).anchor(file) as Range;
      const g = window.__t.offsetOf(
        file.body,
        point.startContainer,
        point.startOffset,
      );
      return {
        text: file.body.textContent!.slice(g, g + 12),
        cfi: core.cfiOf(0, point) as string,
      };
    }, here);
    expect(inFile).toEqual({ text, cfi: here });

    // Reopened in Auto: no wrappers, and the stored place is on screen,
    // standing before the same text.
    await openIn(page, bookId, "auto", DIGITS_BOOK, { restore: "1" });
    expect(await wrapped(page)).toEqual([]);
    expect(
      await page.evaluate(() =>
        window.__beepubReaderNG.core.forcedWritingMode(),
      ),
    ).toBe(null);
    await expect.poll(() => onScreen(page, here)).toBe(true);
    expect(await textAfter(page, here)).toBe(text);
    expect((await location(page)).fraction).toBeGreaterThan(0);

    // And the other way: what Auto saves, forced vertical restores.
    const savedAgain = page.waitForResponse(
      (r) => r.request().method() === "PUT" && r.url().endsWith("/progress"),
      { timeout: 10_000 },
    );
    await page.keyboard.press("ArrowRight");
    await page.waitForTimeout(250);
    await page.keyboard.press("ArrowRight");
    expect((await savedAgain).ok()).toBeTruthy();
    await page.waitForTimeout(2600); // the save debounce, for the last turn
    const there = (
      await (await page.request.get(`/api/books/${bookId}/progress`)).json()
    ).cfi as string;
    const thereText = await textAfter(page, there);
    await openIn(page, bookId, "vertical", DIGITS_BOOK, { restore: "1" });
    expect((await wrapped(page)).length).toBeGreaterThan(100);
    await expect.poll(() => onScreen(page, there)).toBe(true);
    expect(await textAfter(page, there)).toBe(thereText);
  });
});

test.describe("upright numbers on a phone", () => {
  test.use({ ...iphone });

  test.beforeEach(async ({ page }) => {
    await installHelpers(page);
  });

  test.afterEach(async ({ page }) => {
    const id = await seedFixture(page.request, DIGITS_BOOK);
    await resetProgress(page.request, id);
    await clearHighlights(page.request, id);
  });

  test("a long press on an upright number selects the number and saves the CFI of the untouched document", async ({
    page,
    context,
  }) => {
    const bookId = await seedFixture(page.request, DIGITS_BOOK);
    await clearHighlights(page.request, bookId);
    await openIn(page, bookId, "vertical", DIGITS_BOOK);
    expect(await wrapped(page, "#probe")).toEqual(["4", "12"]);

    const target = await page.evaluate(async () => {
      const core = window.__beepubReaderNG.core;
      const doc: Document = window.__t.doc();
      const el = doc.querySelectorAll("#probe beepub-tcy")[1];
      const io = (
        doc.defaultView!.frameElement as HTMLElement
      ).getBoundingClientRect();
      const text = doc.createRange();
      text.selectNodeContents(el);
      const r = text.getBoundingClientRect();
      const file: Document = await core.pristineDocument(0);
      return {
        x: io.left + r.left + r.width / 2,
        y: io.top + r.top + r.height / 2,
        cfi: core.cfiOf(
          0,
          window.__t.range(file.getElementById("probe"), "12"),
        ) as string,
      };
    });
    const cdp = await context.newCDPSession(page);
    await touchTap(cdp, target, 900);
    const row = await saveFromMenu(page);
    expect(row.text).toBe("12");
    expect(row.cfi_range).toBe(target.cfi);
    expect(row.prefix).toMatch(/到第$/);
    expect(row.suffix).toMatch(/^夜才熄/);
    await expect.poll(async () => (await marks(page)).length).toBe(1);
  });
});
