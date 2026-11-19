import { describe, expect, it, vi } from "vitest";

// The language BeePub is set to; the generated runtime is not needed to
// know what a date looks like in it.
vi.mock("#lib/paraglide/runtime.js", () => ({ getLocale: () => "en" }));

import { formatDate, formatSize } from "./format";

describe("formatDate", () => {
  const noon = "2026-11-15T12:00:00Z";

  it("writes the date in the language the app is set to", () => {
    expect(formatDate(noon)).toBe("Nov 15, 2026");
    expect(formatDate(noon, "date", "zh-TW")).toBe("2026年11月15日");
  });

  it("leaves the year out of a day", () => {
    expect(formatDate(noon, "day")).toBe("Nov 15");
  });

  it("writes a column of dates in digits", () => {
    expect(formatDate(noon, "numeric")).toBe("11/15/2026");
  });

  it("writes nothing for what is not a date", () => {
    expect(formatDate(null)).toBe("");
    expect(formatDate(undefined)).toBe("");
    expect(formatDate("")).toBe("");
    expect(formatDate("not a date")).toBe("");
  });
});

describe("formatSize", () => {
  it("says a size in the unit a person would", () => {
    expect(formatSize(0)).toBe("0 KB");
    expect(formatSize(812 * 1024)).toBe("812 KB");
    expect(formatSize(3.4 * 1024 * 1024)).toBe("3.4 MB");
    expect(formatSize(1.2 * 1024 ** 3)).toBe("1.2 GB");
  });

  it("changes unit at the boundary, not after it", () => {
    expect(formatSize(1024 * 1024 - 1)).toBe("1024 KB");
    expect(formatSize(1024 * 1024)).toBe("1.0 MB");
    expect(formatSize(1024 ** 3)).toBe("1.0 GB");
  });
});
