import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { recallProgress, rememberProgress } from "./progress-cache";

function fakeStorage() {
  const kept = new Map<string, string>();
  return {
    getItem: (k: string) => kept.get(k) ?? null,
    setItem: (k: string, v: string) => void kept.set(k, v),
    kept,
  };
}

describe("the position kept on this device", () => {
  let storage: ReturnType<typeof fakeStorage>;
  beforeEach(() => {
    storage = fakeStorage();
    vi.stubGlobal("localStorage", storage);
  });
  afterEach(() => vi.unstubAllGlobals());

  it("comes back as it was kept, per book", () => {
    rememberProgress("a", "epubcfi(/6/4!/4:0)", 12.5, { fontSize: 18 });
    rememberProgress("b", null, 100);
    expect(recallProgress("a")).toEqual({
      cfi: "epubcfi(/6/4!/4:0)",
      percentage: 12.5,
      extra: { fontSize: 18 },
    });
    expect(recallProgress("b")).toEqual({
      cfi: null,
      percentage: 100,
      extra: {},
    });
    expect(recallProgress("c")).toBeNull();
  });

  it("reads what an older version wrote under the same key", () => {
    storage.kept.set(
      "reader-progress-a",
      JSON.stringify({
        cfi: "epubcfi(/6/2!/4:0)",
        percentage: 3,
        currentPage: 2,
      }),
    );
    expect(recallProgress("a")).toMatchObject({
      cfi: "epubcfi(/6/2!/4:0)",
      percentage: 3,
    });
  });

  it("is nothing when what is kept cannot be read", () => {
    storage.kept.set("reader-progress-a", "{not json");
    expect(recallProgress("a")).toBeNull();
    storage.kept.set("reader-progress-a", JSON.stringify({ cfi: 7 }));
    expect(recallProgress("a")).toEqual({
      cfi: null,
      percentage: null,
      extra: {},
    });
  });

  it("does not throw when storage refuses", () => {
    vi.stubGlobal("localStorage", {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("full");
      },
    });
    expect(() => rememberProgress("a", null, 1)).not.toThrow();
    expect(recallProgress("a")).toBeNull();
  });
});
