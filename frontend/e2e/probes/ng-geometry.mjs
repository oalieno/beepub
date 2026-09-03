// reader-ng G0 kill-point probe: turn a few pages, change one geometry
// input at a time, and check that (a) the anchor — the previous visible
// range's start — is still inside the visible range, (b) no text rect is
// cut by the page box on the pagination axis (no second page peeking),
// (c) the iframe took at most one size step per change (no intermediate
// visible state). Run from frontend/:
//   BASE_URL=http://<docker-host>:8091 node e2e/probes/ng-geometry.mjs [--device=iphone] [book...]
// Books: fixture/testbook names below; default runs all. --device=iphone
// uses the iPhone 13 descriptor on chromium (390x664 viewport).
import path from "node:path";
import os from "node:os";
import { adminApi, seedBook, openReader, BASE } from "./lib.mjs";

const TESTBOOKS = path.join(os.homedir(), "work/beepub-testbooks");
const BOOKS = {
  "vertical-long": {
    title: "e2e-vertical-long",
    epub: "e2e/fixtures/e2e-vertical-long-book.epub",
    font: "sans", // Noto Sans CJK TC is the installed CJK face; serif falls back to advance-0 glyphs
  },
  sanguo: { title: "三國演義", epub: `${TESTBOOKS}/sanguoyanyi.epub` },
  hongloumeng: {
    title: "紅樓夢",
    epub: `${TESTBOOKS}/hongloumeng-vertical.epub`,
    font: "sans",
  },
  mushoku: {
    title: "無職転生",
    epub: `${TESTBOOKS}/mushoku.epub`,
    font: "sans",
  },
  flicker: { title: "flicker", epub: `${TESTBOOKS}/flicker-repro.epub` },
  vpunct: {
    title: "vpunct",
    epub: `${TESTBOOKS}/vpunct-trap.epub`,
    font: "sans",
  },
};

// Each step is one geometry input. Sliders in the panel are the product
// path for font/line-height (setStyles); layout params go through
// core.setLayout, the same call BookReader makes.
const STEPS = [
  { name: "gap 7→12%", kind: "layout", layout: { gap: 12 } },
  { name: "margin 48→16px", kind: "layout", layout: { margin: 16 } },
  { name: "font 18→24px", kind: "slider", id: "#ng-size", value: "24" },
  { name: "line-height 1.8→2.4", kind: "slider", id: "#ng-lh", value: "2.4" },
  { name: "header off (container +48px)", kind: "switch", id: "#ng-chrome" },
];

const PAGES_IN = 3;

async function main() {
  const args = process.argv.slice(2);
  const device =
    args.find((a) => a.startsWith("--device="))?.split("=")[1] ?? null;
  const wanted = args.filter((a) => !a.startsWith("--"));
  const names = wanted.length ? wanted : Object.keys(BOOKS);
  const { token, api } = await adminApi();
  const rows = [];
  for (const name of names) {
    const spec = BOOKS[name];
    if (!spec) throw new Error(`unknown book ${name}`);
    const bookId = await seedBook(api, spec.title, spec.epub);
    const result = await probeBook(bookId, spec, token, device);
    rows.push(...result.map((r) => ({ book: name, ...r })));
  }
  console.table(rows);
  const failed = rows.filter((r) => !r.ok);
  console.log(
    failed.length
      ? `FAIL ${failed.length}/${rows.length}`
      : `PASS ${rows.length}`,
  );
  process.exit(failed.length ? 1 : 0);
}

async function probeBook(bookId, spec, token, device) {
  const { browser, page } = await openNg(bookId, spec, token, device);
  const rows = [];
  try {
    // Start in a section with real body text — front matter and
    // illustration pages have nothing to measure — then page in so the
    // anchor is a user-driven visible range (reason 'page').
    const startIndex = await page.evaluate(async () => {
      const core = window.__beepubReaderNG.core;
      const cur = core.lastLocation.index;
      const n = core.book.sections.length;
      for (let i = cur; i < Math.min(n, cur + 40); i++) {
        const doc = await core.book.sections[i].createDocument();
        const len = (doc.body?.textContent ?? "").replace(/\s+/g, "").length;
        if (len > 1500) return i;
      }
      return cur;
    });
    const atIndex = await page.evaluate(
      () => window.__beepubReaderNG.core.lastLocation.index,
    );
    if (startIndex !== atIndex) {
      await page.evaluate(
        (i) => window.__beepubReaderNG.core.goTo(i),
        startIndex,
      );
      await page.waitForTimeout(300);
    }
    for (let i = 0; i < PAGES_IN; i++) {
      await page.evaluate(() => window.__beepubReaderNG.core.next());
      await page.waitForTimeout(250);
    }
    const start = await snapshot(page);
    rows.push({ step: "baseline", ...start, ok: start.cut === 0 });
    // The engine's anchor is the visible range of the last user relocation
    // and is re-derived, never re-committed, on layout changes. Mirror
    // that: one anchor for the whole step sequence.
    await commitAnchor(page);

    for (const step of STEPS) {
      await armWatch(page);
      if (step.kind === "layout") {
        await page.evaluate(
          (l) => window.__beepubReaderNG.core.setLayout(l),
          step.layout,
        );
      } else if (step.kind === "slider") {
        await page.locator(step.id).fill(step.value);
      } else if (step.kind === "switch") {
        await page.locator(step.id).click();
      }
      const watch = await settle(page);
      const after = await snapshot(page);
      const held = await anchorHeld(page);
      rows.push({
        step: step.name,
        ...after,
        relocates: watch.relocates,
        sizes: watch.sizes.join("→"),
        anchorHeld: held,
        ok: held === true && after.cut === 0 && watch.sizes.length <= 3,
      });
    }
  } finally {
    await browser.close();
  }
  return rows;
}

async function openNg(bookId, spec, token, device) {
  const { browser, context } = await openReaderContext(token, device);
  const page = await context.newPage();
  page.on("pageerror", (e) => console.log("  [pageerror]", e.message));
  page.on("framenavigated", (f) => {
    if (f === page.mainFrame()) console.log("  [navigated]", f.url());
  });
  page.on("console", (m) => {
    if (m.type() === "error" || m.type() === "warning")
      console.log(`  [console.${m.type()}]`, m.text());
  });
  const params = new URLSearchParams({
    size: "18",
    lh: "1.8",
    gap: "7",
    margin: "48",
    cols: "1",
  });
  if (spec.font) params.set("font", spec.font);
  await page.goto(`/books/${bookId}/read-ng?${params}`);
  // The vite dev stack may full-reload once after discovering new deps;
  // let the network settle so that reload lands before we start measuring.
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForFunction(
    () => !!window.__beepubReaderNG?.core?.lastLocation,
    null,
    {
      timeout: 60_000,
    },
  );
  await page.waitForTimeout(500);
  return { browser, page };
}

// lib.openReader navigates to the old route; reuse only its context setup.
async function openReaderContext(token, device) {
  const { chromium, devices } = await import("@playwright/test");
  const browser = await chromium.launch();
  let opts = { baseURL: BASE, viewport: { width: 900, height: 700 } };
  if (device === "iphone") {
    // chromium + the iPhone 13 descriptor (viewport, DPR, touch, UA)
    const { defaultBrowserType: _webkit, ...iphone } = devices["iPhone 13"];
    opts = { baseURL: BASE, ...iphone };
  }
  const context = await browser.newContext(opts);
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
  return { browser, context };
}

/** Anchor bookkeeping lives in the page: the previous user-level visible
 *  range start, compared against the current visible range. */
async function commitAnchor(page) {
  await page.evaluate(() => {
    const loc = window.__beepubReaderNG.core.lastLocation;
    window.__ngAnchor = loc?.range ? loc.range.cloneRange() : null;
  });
}

/** The anchor is on screen when the rect of its first character (or the
 *  first rect of an element anchor) sits inside the clipping container on
 *  the pagination axis. Boundary-point comparison is too strict: foliate's
 *  visible range starts at (p, 0) when the paragraph is fully in view and
 *  at (text, 0) once it spans a page — the same place, different points. */
async function anchorHeld(page) {
  return page.evaluate(() => {
    const core = window.__beepubReaderNG.core;
    const a = window.__ngAnchor;
    const doc = core.getContents()[0].doc;
    if (!a || a.startContainer.ownerDocument !== doc) return null;
    const node = a.startContainer;
    const off = a.startOffset;
    const r = doc.createRange();
    const max = node.nodeType === 3 ? node.length : node.childNodes.length;
    if (off < max) {
      r.setStart(node, off);
      r.setEnd(node, off + 1);
    } else r.selectNodeContents(node);
    const rect = Array.from(r.getClientRects()).find(
      (x) => x.width > 0 && x.height > 0,
    );
    if (!rect) return null;
    const frame = doc.defaultView.frameElement;
    const fb = frame.getBoundingClientRect();
    const box = frame.parentElement.parentElement.getBoundingClientRect();
    const mid = core.vertical
      ? (rect.top + rect.bottom) / 2 + fb.top
      : (rect.left + rect.right) / 2 + fb.left;
    const [lo, hi] = core.vertical
      ? [box.top, box.bottom]
      : [box.left, box.right];
    return mid >= lo && mid <= hi;
  });
}

/** rAF-sample the iframe's pagination-axis size and count relocates until
 *  quiet for 600ms (or 5s cap). */
async function armWatch(page) {
  await page.evaluate(() => {
    const core = window.__beepubReaderNG.core;
    const doc = core.getContents()[0].doc;
    const frame = doc.defaultView.frameElement;
    const w = { sizes: [], relocates: 0, done: false };
    const axis = core.vertical ? "height" : "width";
    const sample = () => {
      const s = Math.round(frame.getBoundingClientRect()[axis]);
      if (w.sizes.at(-1) !== s) w.sizes.push(s);
      if (!w.done) requestAnimationFrame(sample);
    };
    sample();
    const onRelocate = () => (w.relocates += 1);
    core.paginator.addEventListener("relocate", onRelocate);
    w.stop = () => {
      w.done = true;
      core.paginator.removeEventListener("relocate", onRelocate);
    };
    window.__ngWatch = w;
  });
}

async function settle(page) {
  const t0 = Date.now();
  let last = null;
  let lastChange = Date.now();
  while (Date.now() - t0 < 5000) {
    await page.waitForTimeout(100);
    const cur = await page.evaluate(() =>
      JSON.stringify([window.__ngWatch.sizes, window.__ngWatch.relocates]),
    );
    if (cur !== last) {
      last = cur;
      lastChange = Date.now();
    } else if (Date.now() - lastChange > 600) break;
  }
  return page.evaluate(() => {
    const w = window.__ngWatch;
    w.stop();
    return { sizes: w.sizes, relocates: w.relocates };
  });
}

/** Visible text rects vs the paginator host box: count rects cut by the
 *  pagination-axis edges, plus the location readout. */
async function snapshot(page) {
  return page.evaluate(() => {
    const core = window.__beepubReaderNG.core;
    const loc = core.lastLocation;
    const doc = core.getContents()[0].doc;
    const frame = doc.defaultView.frameElement;
    // The scroll container clips; the host box also covers the margins
    // and the neighbouring columns that overflow: hidden removes.
    const host = frame.parentElement.parentElement.getBoundingClientRect();
    const fb = frame.getBoundingClientRect();
    const vertical = core.vertical;
    const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT);
    let vis = 0;
    let cut = 0;
    while (walker.nextNode()) {
      const n = walker.currentNode;
      if (!n.textContent.trim()) continue;
      const rg = doc.createRange();
      rg.selectNodeContents(n);
      for (const r of rg.getClientRects()) {
        if (r.width <= 0 || r.height <= 0) continue;
        const top = r.top + fb.top,
          bottom = r.bottom + fb.top;
        const left = r.left + fb.left,
          right = r.right + fb.left;
        const inside =
          bottom > host.top + 1 &&
          top < host.bottom - 1 &&
          right > host.left + 1 &&
          left < host.right - 1;
        if (!inside) continue;
        vis++;
        const cutHere = vertical
          ? top < host.top - 1 || bottom > host.bottom + 1
          : left < host.left - 1 || right > host.right + 1;
        if (cutHere) cut++;
      }
    }
    return {
      index: loc?.index,
      frac: loc ? Number(loc.fraction.toFixed(3)) : null,
      reason: loc?.reason,
      vis,
      cut,
      frame: Math.round(fb[vertical ? "height" : "width"]),
      box: Math.round(host[vertical ? "height" : "width"]),
    };
  });
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
