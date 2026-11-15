import { describe, expect, it } from "vitest";
import {
  buildSpreads,
  comicPages,
  displayOrder,
  halves,
  isWide,
  pageFromPercent,
  pagePercent,
  spreadIndexOf,
  type PageEntry,
} from "./pages";

/** A portrait page of a comic; `over` makes it something else. */
function page(index: number, over: Partial<PageEntry> = {}): PageEntry {
  return {
    index,
    image: `p${index}.jpg`,
    width: 800,
    height: 1200,
    spread: null,
    ...over,
  } as PageEntry;
}
const book = (n: number) => Array.from({ length: n }, (_, i) => page(i));
const shape = (spreads: PageEntry[][]) =>
  spreads.map((s) => s.map((p) => p.index));

describe("buildSpreads", () => {
  it("shows one page per screen in the one-page layout", () => {
    expect(shape(buildSpreads(book(3), false, true))).toEqual([[0], [1], [2]]);
  });

  it("leaves the cover alone and pairs the rest", () => {
    expect(shape(buildSpreads(book(6), true, true))).toEqual([
      [0],
      [1, 2],
      [3, 4],
      [5],
    ]);
  });

  it("gives a wide page the screen, and does not pair the page before it", () => {
    const pages = book(6);
    pages[2] = page(2, { width: 1600, height: 1200 });
    expect(shape(buildSpreads(pages, true, true))).toEqual([
      [0],
      [1],
      [2],
      [3, 4],
      [5],
    ]);
  });

  it("pairs a wide picture the book places on one side", () => {
    const pages = book(3);
    pages[1] = page(1, { width: 1600, height: 1200, spread: "left" });
    expect(isWide(pages[1])).toBe(false);
    expect(shape(buildSpreads(pages, true, true))).toEqual([[0], [1, 2]]);
  });

  it("shifted, pairs from the first page", () => {
    expect(shape(buildSpreads(book(5), true, true, true))).toEqual([
      [0, 1],
      [2, 3],
      [4],
    ]);
  });
});

describe("halves", () => {
  it("puts the cover in the second half and any other lone page in the first", () => {
    const [cover] = book(1);
    expect(halves([cover], true)).toEqual([null, cover]);
    const last = page(5);
    expect(halves([last], true)).toEqual([last, null]);
    expect(halves([cover], true, true)).toEqual([cover, null]);
  });

  it("leaves a pair, a wide page and the one-page layout as they are", () => {
    const pair = [page(1), page(2)];
    expect(halves(pair, true)).toBe(pair);
    const wide = [page(3, { width: 1600, height: 1200 })];
    expect(halves(wide, true)).toBe(wide);
    const single = [page(0)];
    expect(halves(single, false)).toBe(single);
  });
});

describe("comicPages", () => {
  it("drops pages with no picture and renumbers the rest", () => {
    const pages = [page(0), page(1, { image: null }), page(2)];
    expect(comicPages(pages)?.map((p) => [p.index, p.image])).toEqual([
      [0, "p0.jpg"],
      [1, "p2.jpg"],
    ]);
  });

  it("is no comic when a page said to be a picture has none, or none has", () => {
    expect(
      comicPages([page(0), page(1, { image: null, picture: true })]),
    ).toBeNull();
    expect(comicPages([page(0, { image: null })])).toBeNull();
  });
});

describe("where a page is", () => {
  it("reads right-to-left on screen in a right-to-left book", () => {
    expect(displayOrder([1, 2], true)).toEqual([2, 1]);
    expect(displayOrder([1, 2], false)).toEqual([1, 2]);
  });

  it("finds the screen a page is on", () => {
    const spreads = buildSpreads(book(6), true, true);
    expect(spreadIndexOf(spreads, 4)).toBe(2);
    expect(spreadIndexOf(spreads, 99)).toBe(0);
  });

  it("counts the last page as finished, and goes back to the same page", () => {
    expect(pagePercent(0, 11)).toBe(0);
    expect(pagePercent(10, 11)).toBe(100);
    expect(pagePercent(0, 1)).toBe(100);
    for (const total of [2, 7, 200])
      for (let i = 0; i < total; i++)
        expect(pageFromPercent(pagePercent(i, total), total)).toBe(i);
    expect(pageFromPercent(150, 10)).toBe(9);
    expect(pageFromPercent(-5, 10)).toBe(0);
  });
});
