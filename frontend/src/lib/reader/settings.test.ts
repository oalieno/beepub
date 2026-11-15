import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  DEFAULT_SETTINGS,
  KEY,
  parsePageTurn,
  readSettings,
  storePagerShift,
  storeWritingMode,
  storedPagerShift,
  storedWritingMode,
} from "./settings";

const phone = { canCurl: true, appDark: false };
const desk = { canCurl: false, appDark: false };
const none = new URLSearchParams();

describe("the reader's settings as a device keeps them", () => {
  let kept: Map<string, string>;
  beforeEach(() => {
    kept = new Map();
    vi.stubGlobal("localStorage", {
      getItem: (k: string) => kept.get(k) ?? null,
      setItem: (k: string, v: string) => void kept.set(k, v),
      removeItem: (k: string) => void kept.delete(k),
    });
  });
  afterEach(() => vi.unstubAllGlobals());

  it("is the defaults for a reader who has set nothing", () => {
    expect(readSettings(none, desk)).toEqual(DEFAULT_SETTINGS);
  });

  it("is the defaults when storage cannot be read", () => {
    vi.stubGlobal("localStorage", {
      getItem: () => {
        throw new Error("blocked");
      },
    });
    expect(readSettings(none, desk)).toEqual(DEFAULT_SETTINGS);
  });

  it("reads what was stored", () => {
    kept.set(KEY.size, "20");
    kept.set(KEY.lineHeight, "2");
    kept.set(KEY.fullPage, "1");
    kept.set(KEY.pagerMode, "webtoon");
    kept.set(KEY.pagerDirection, "ltr");
    kept.set(KEY.pagerPadding, "12");
    expect(readSettings(none, desk)).toMatchObject({
      fontSize: 20,
      lineHeight: 2,
      fullPage: true,
      pagerMode: "webtoon",
      pagerDirection: "ltr",
      pagerPadding: 12,
    });
  });

  it("falls back on what makes no sense", () => {
    kept.set(KEY.size, "large");
    kept.set(KEY.pagerMode, "sideways");
    kept.set(KEY.pagerDirection, "up");
    kept.set(KEY.pagerPadding, "-40");
    expect(readSettings(none, desk)).toMatchObject({
      fontSize: 16,
      pagerMode: "single",
      pagerDirection: "auto",
      pagerPadding: 0,
    });
  });

  it("lets the query win over what is stored, without writing it back", () => {
    kept.set(KEY.size, "20");
    kept.set(KEY.dark, "0");
    const q = new URLSearchParams("size=18&mx=8&dark=1&font=sans&turn=instant");
    expect(readSettings(q, desk)).toMatchObject({
      fontSize: 18,
      marginX: 8,
      dark: true,
      font: "system",
      pageTurn: "instant",
    });
    expect(kept.get(KEY.size)).toBe("20");
    expect(kept.get(KEY.dark)).toBe("0");
  });

  it("seeds both margins from the old single margin, until each is set", () => {
    kept.set(KEY.legacyMargin, "48");
    expect(readSettings(none, desk)).toMatchObject({
      marginX: 48,
      marginY: 48,
    });
    kept.set(KEY.marginX, "16");
    expect(readSettings(none, desk)).toMatchObject({
      marginX: 16,
      marginY: 48,
    });
  });

  it("follows the app's theme until the reader is given its own", () => {
    expect(readSettings(none, { canCurl: false, appDark: true }).dark).toBe(
      true,
    );
    kept.set(KEY.dark, "0");
    expect(readSettings(none, { canCurl: false, appDark: true }).dark).toBe(
      false,
    );
  });

  describe("page turn", () => {
    it("understands the modes from before 2026-10", () => {
      expect(parsePageTurn("animated")).toBe("slide");
      expect(parsePageTurn("follow")).toBe("slide");
      expect(parsePageTurn("instant")).toBe("fade");
      expect(parsePageTurn(null)).toBe("fade");
      expect(parsePageTurn("scroll")).toBe("scroll");
    });

    it("rewrites an old stored mode in today's words", () => {
      kept.set(KEY.pageTurn, "follow");
      expect(readSettings(none, desk).pageTurn).toBe("slide");
      expect(kept.get(KEY.pageTurn)).toBe("slide");
    });

    it("slides where the curl cannot be drawn, and keeps the choice", () => {
      kept.set(KEY.pageTurn, "curl");
      kept.set(KEY.pagerTurn, "curl");
      expect(readSettings(none, phone)).toMatchObject({
        pageTurn: "curl",
        pagerTurn: "curl",
      });
      expect(readSettings(none, desk)).toMatchObject({
        pageTurn: "slide",
        pagerTurn: "instant",
      });
      expect(kept.get(KEY.pageTurn)).toBe("curl");
    });
  });

  describe("per book", () => {
    it("keeps a writing mode for one book, and forgets it on auto", () => {
      storeWritingMode("a", "vertical");
      expect(storedWritingMode("a")).toBe("vertical");
      expect(storedWritingMode("b")).toBe("auto");
      storeWritingMode("a", "auto");
      expect(storedWritingMode("a")).toBe("auto");
      expect([...kept.keys()]).toEqual([]);
    });

    it("keeps the pair shift for one book", () => {
      storePagerShift("a", true);
      expect(storedPagerShift("a")).toBe(true);
      expect(storedPagerShift("b")).toBe(false);
      storePagerShift("a", false);
      expect(storedPagerShift("a")).toBe(false);
    });
  });
});
