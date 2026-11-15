import { describe, expect, it } from "vitest";
import { normalizeCFI } from "./cfi";

describe("normalizeCFI", () => {
  it("moves the shared text step into both ends of an Apple Books range", () => {
    expect(normalizeCFI("epubcfi(/6/4!/4/8/1,:4,:17)")).toBe(
      "epubcfi(/6/4!/4/8,/1:4,/1:17)",
    );
  });

  it("keeps the step's assertion with it", () => {
    expect(normalizeCFI("epubcfi(/6/4!/4/8[p1]/1[a,b],:4,:17)")).toBe(
      "epubcfi(/6/4!/4/8[p1],/1[a,b]:4,/1[a,b]:17)",
    );
  });

  it("leaves a range whose ends already start with a step", () => {
    const ours = "epubcfi(/6/4!/4/8,/1:4,/1:17)";
    expect(normalizeCFI(ours)).toBe(ours);
  });

  it("leaves a point, and what is not a CFI", () => {
    expect(normalizeCFI("epubcfi(/6/4!/4/8/1:4)")).toBe(
      "epubcfi(/6/4!/4/8/1:4)",
    );
    expect(normalizeCFI("chapter-3")).toBe("chapter-3");
  });

  it("does not take a comma inside an assertion for a range", () => {
    const cfi = "epubcfi(/6/4[a,b,c]!/4/8/1:4)";
    expect(normalizeCFI(cfi)).toBe(cfi);
  });

  it("will not empty the path before the content document", () => {
    const cfi = "epubcfi(/6/4!/4,:4,:17)";
    // "/4" is the only step after "!": moving it would leave "…!" bare.
    expect(normalizeCFI(cfi)).toBe(cfi);
  });
});
