import { beforeEach, describe, expect, it, vi } from "vitest";

const kept = new Map<string, string>();
let native = true;

vi.mock("#lib/platform.ts", () => ({ isNative: () => native }));
vi.mock("@capacitor/preferences", () => ({
  Preferences: {
    get: async ({ key }: { key: string }) => ({ value: kept.get(key) ?? null }),
    set: async ({ key, value }: { key: string; value: string }) => {
      kept.set(key, value);
    },
    remove: async ({ key }: { key: string }) => {
      kept.delete(key);
    },
  },
}));

const working = new Map<string, string>();
vi.stubGlobal("localStorage", {
  getItem: (k: string) => working.get(k) ?? null,
  setItem: (k: string, v: string) => void working.set(k, v),
  removeItem: (k: string) => void working.delete(k),
});

const tokens = await import("./tokens");

beforeEach(() => {
  kept.clear();
  working.clear();
  native = true;
});

describe("the app's login", () => {
  it("is kept in both places when signing in", async () => {
    await tokens.storeTokens("a1", "r1");
    expect(tokens.accessToken()).toBe("a1");
    expect(tokens.refreshToken()).toBe("r1");
    expect(kept.get("auth-token")).toBe("a1");
    expect(kept.get("auth-refresh-token")).toBe("r1");
  });

  it("comes back at start-up after the system cleared the web view's storage", async () => {
    await tokens.storeTokens("a1", "r1");
    working.clear();

    await tokens.restoreTokens();

    expect(tokens.accessToken()).toBe("a1");
    expect(tokens.refreshToken()).toBe("r1");
  });

  it("is copied to safety when it predates the safety copy", async () => {
    working.set("token", "old-a");
    working.set("refresh_token", "old-r");

    await tokens.restoreTokens();

    expect(kept.get("auth-token")).toBe("old-a");
    expect(kept.get("auth-refresh-token")).toBe("old-r");
    expect(tokens.accessToken()).toBe("old-a");
  });

  it("keeps a renewed access token in both places", async () => {
    await tokens.storeTokens("a1", "r1");
    await tokens.storeAccessToken("a2");
    expect(tokens.accessToken()).toBe("a2");
    expect(kept.get("auth-token")).toBe("a2");
    expect(kept.get("auth-refresh-token")).toBe("r1");
  });

  it("is gone from both places after signing out — and stays gone", async () => {
    await tokens.storeTokens("a1", "r1");
    await tokens.clearTokens();
    await tokens.restoreTokens();
    expect(tokens.accessToken()).toBeNull();
    expect(tokens.refreshToken()).toBeNull();
    expect(kept.size).toBe(0);
  });

  it("does none of this on the web, where the login is cookies", async () => {
    native = false;
    await tokens.storeTokens("a1", "r1");
    await tokens.restoreTokens();
    expect(working.size).toBe(0);
    expect(kept.size).toBe(0);
  });
});
