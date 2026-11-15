import { describe, expect, it, vi } from "vitest";

vi.mock("$lib/paraglide/messages.js", () => ({
  error_book_not_found: () => "找不到這本書",
}));

const { errorMessage } = await import("./errors");

describe("errorMessage", () => {
  it("picks the message by the code, whatever the sentence says", () => {
    expect(
      errorMessage({ detail: "Reworded since", code: "book_not_found" }),
    ).toBe("找不到這本書");
  });

  it("shows the sentence when there is no code, or one it does not know", () => {
    expect(errorMessage({ detail: "Series not found" })).toBe(
      "Series not found",
    );
    expect(
      errorMessage({ detail: "Something new", code: "from_a_newer_server" }),
    ).toBe("Something new");
  });

  it("says nothing for a body that says nothing", () => {
    expect(errorMessage({})).toBeNull();
  });
});
