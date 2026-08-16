// Shared helpers for ad-hoc reader probes — see README.md in this folder.
// Import style: this file runs with plain `node` from frontend/, resolving
// playwright through @playwright/test (the only playwright package installed).
import fs from "node:fs";
import { chromium, devices, request } from "@playwright/test";

export const BASE = process.env.BASE_URL ?? "http://localhost:8091";
export const ADMIN = {
  username: process.env.E2E_ADMIN_USERNAME ?? "e2e-admin",
  password: process.env.E2E_ADMIN_PASSWORD ?? "e2e-password-123",
};

/** Log in (registering on a fresh stack) → { token, api } request context. */
export async function adminApi() {
  const anon = await request.newContext({ baseURL: BASE });
  const status = await anon.get("/api/auth/registration-status");
  if (!status.ok()) {
    throw new Error(
      `stack unreachable at ${BASE} (${status.status()}) — e2e/stack.sh up?`,
    );
  }
  if ((await status.json()).first_user) {
    await anon.post("/api/auth/register", { data: ADMIN });
  }
  const login = await anon.post("/api/auth/login", { form: ADMIN });
  if (!login.ok()) throw new Error(await login.text());
  const { access_token } = await login.json();
  await anon.dispose();
  const api = await request.newContext({
    baseURL: BASE,
    extraHTTPHeaders: { Authorization: `Bearer ${access_token}` },
  });
  return { token: access_token, api };
}

/** Find a book by (partial) title, or upload the given epub. Returns its id. */
export async function seedBook(api, title, epubPath) {
  const books = await (await api.get("/api/books/all?limit=500")).json();
  const existing = books.items?.find((b) =>
    (b.display_title ?? b.epub_title ?? "").includes(title),
  );
  if (existing) return existing.id;
  if (!epubPath)
    throw new Error(`book "${title}" not on the stack and no epub given`);
  const libs = await (await api.get("/api/libraries")).json();
  const uploaded = await api.post("/api/books", {
    multipart: {
      file: {
        name: "probe.epub",
        mimeType: "application/epub+zip",
        buffer: fs.readFileSync(epubPath),
      },
      library_id: libs[0].id,
    },
  });
  if (!uploaded.ok()) throw new Error(await uploaded.text());
  return (await uploaded.json()).id;
}

/**
 * Launch a browser page logged in as admin with reader settings pre-seeded.
 * device: "iphone" (chromium + iPhone 13 descriptor — the reader's iOS paths
 * are UA-gated, and CDP still works) or a {width,height} viewport for desktop.
 */
export async function openReader(
  bookId,
  { device, margin, fontSize, lineHeight, token } = {},
) {
  const browser = await chromium.launch();
  let ctxOpts = { baseURL: BASE };
  if (device === "iphone") {
    // Keep the chromium project's browser: webkit isn't runnable everywhere,
    // and CDP (touch dispatch, trusted click synthesis) is chromium-only.
    const { defaultBrowserType: _webkit, ...iphone } = devices["iPhone 13"];
    ctxOpts = { ...ctxOpts, ...iphone };
  } else if (device) {
    ctxOpts.viewport = device;
  }
  const context = await browser.newContext(ctxOpts);
  await context.addCookies([
    {
      name: "token",
      value: token,
      domain: new URL(BASE).hostname,
      path: "/",
      httpOnly: true,
      secure: BASE.startsWith("https"),
      sameSite: "Lax",
    },
  ]);
  const page = await context.newPage();
  await page.addInitScript(
    (s) => {
      localStorage.setItem("reader-gestures-seen", "1"); // coach mark eats the first tap
      if (s.margin != null)
        localStorage.setItem("reader-margin", String(s.margin));
      if (s.fontSize != null)
        localStorage.setItem("reader-size", String(s.fontSize));
      if (s.lineHeight != null)
        localStorage.setItem("reader-lineheight", String(s.lineHeight));
    },
    { margin, fontSize, lineHeight },
  );
  await page.goto(`/books/${bookId}/read`);
  await page.waitForSelector("iframe", { timeout: 30_000 });
  await page.waitForTimeout(3000); // locations, progress restore, hooks
  return { browser, context, page };
}

/**
 * Alignment of the visible page: text insets against the scroll window and
 * how many rects are cut by its edges. Works for horizontal and vertical
 * pagination (the scroller is found by overflow, axis-agnostic).
 */
export async function measureAlignment(page) {
  return page.evaluate(() => {
    const ifr = document.querySelector("iframe");
    const doc = ifr?.contentDocument;
    if (!doc) return null;
    let sc = ifr.parentElement;
    while (
      sc &&
      sc.scrollHeight <= sc.clientHeight + 1 &&
      sc.scrollWidth <= sc.clientWidth + 1
    ) {
      sc = sc.parentElement;
    }
    const box = (sc ?? document.body).getBoundingClientRect();
    const ifrBox = ifr.getBoundingClientRect();
    const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT);
    let minT = Infinity,
      maxB = -Infinity,
      minL = Infinity,
      maxR = -Infinity;
    let cut = 0,
      vis = 0;
    while (walker.nextNode()) {
      const n = walker.currentNode;
      if (!n.textContent.trim()) continue;
      const rg = doc.createRange();
      rg.selectNodeContents(n);
      for (const r of rg.getClientRects()) {
        if (r.width <= 0 || r.height <= 0) continue;
        const top = r.top + ifrBox.top - box.top;
        const bottom = r.bottom + ifrBox.top - box.top;
        const left = r.left + ifrBox.left - box.left;
        const right = r.right + ifrBox.left - box.left;
        if (
          bottom > 1 &&
          top < box.height - 1 &&
          right > 1 &&
          left < box.width - 1
        ) {
          vis++;
          minT = Math.min(minT, top);
          maxB = Math.max(maxB, bottom);
          minL = Math.min(minL, left);
          maxR = Math.max(maxR, right);
          if (top < -2 || bottom > box.height + 2) cut++;
        }
      }
    }
    return {
      topInset: Math.round(minT),
      bottomInset: Math.round(box.height - maxB),
      leftInset: Math.round(minL),
      rightInset: Math.round(box.width - maxR),
      cut,
      vis,
      scrollTop: sc?.scrollTop ?? 0,
      scrollLeft: sc?.scrollLeft ?? 0,
      windowH: Math.round(box.height * 10) / 10,
    };
  });
}

/**
 * Record highlight-menu SHOW/HIDE transitions with timestamps via a
 * MutationObserver (catches blinks that polling misses). Read the log with
 * menuTimeline(page).
 */
export async function armMenuWatcher(page) {
  await page.evaluate(() => {
    window.__menuLog = [];
    window.__menuT0 = performance.now();
    let visible = !!document.querySelector('[data-testid="highlight-menu"]');
    new MutationObserver(() => {
      const v = !!document.querySelector('[data-testid="highlight-menu"]');
      if (v === visible) return;
      visible = v;
      window.__menuLog.push(
        `${Math.round(performance.now() - window.__menuT0)}ms ${v ? "SHOW" : "HIDE"}`,
      );
    }).observe(document.body, { childList: true, subtree: true });
  });
}

export function menuTimeline(page) {
  return page.evaluate(() => window.__menuLog);
}

/** Trusted touch tap/hold via CDP (chromium only). */
export async function touchTap(page, pt, holdMs = 80) {
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Input.dispatchTouchEvent", {
    type: "touchStart",
    touchPoints: [{ x: pt.x, y: pt.y }],
  });
  await new Promise((r) => setTimeout(r, holdMs));
  await cdp.send("Input.dispatchTouchEvent", {
    type: "touchEnd",
    touchPoints: [],
  });
  await cdp.detach();
}

/**
 * Viewport point of a word inside the epub iframe (nth occurrence). Only
 * valid for content on the first visible column — in paginated mode the
 * iframe spans every column, so never derive tap points from the iframe
 * rect's center; use window.innerWidth for horizontal centering instead.
 */
export async function pointOnWord(page, word, occurrence = 0) {
  return page.evaluate(
    ([word, occurrence]) => {
      const ifr = document.querySelector("iframe");
      const doc = ifr.contentDocument;
      const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT);
      let hits = 0;
      while (walker.nextNode()) {
        const node = walker.currentNode;
        const idx = (node.textContent ?? "").indexOf(word);
        if (idx < 0 || hits++ < occurrence) continue;
        const range = doc.createRange();
        range.setStart(node, idx);
        range.setEnd(node, idx + word.length);
        const rect = range.getBoundingClientRect();
        const io = ifr.getBoundingClientRect();
        return {
          x: io.left + rect.left + rect.width / 2,
          y: io.top + rect.top + rect.height / 2,
        };
      }
      return null;
    },
    [word, occurrence],
  );
}
