import { describe, expect, it } from "vitest";
import { applyClick, NO_SELECTION, only } from "./tableSelection";

const order = ["a", "b", "c", "d"];
const plain = { shift: false, toggle: false };

describe("applyClick", () => {
  it("picks the row clicked", () => {
    expect([...applyClick(NO_SELECTION, "b", plain, order).selected]).toEqual([
      "b",
    ]);
  });

  it("lets go of the one row picked when it is clicked again", () => {
    expect(applyClick(only("b"), "b", plain, order)).toEqual(NO_SELECTION);
  });

  it("keeps only the row clicked when several were picked", () => {
    const several = applyClick(
      only("a"),
      "c",
      { ...plain, shift: true },
      order,
    );
    expect([...several.selected]).toEqual(["a", "b", "c"]);
    expect([...applyClick(several, "b", plain, order).selected]).toEqual(["b"]);
  });
});
