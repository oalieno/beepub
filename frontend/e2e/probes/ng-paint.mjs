// reader-ng: does a layout change paint an intermediate frame? The
// geometry probe samples iframe size with rAF, which can observe states
// that never reach the screen. This one records CDP screencast frames
// (every composited frame) around one change and counts distinct frames.
//   BASE_URL=http://<docker-host>:8091 node e2e/probes/ng-paint.mjs [book]
import path from "node:path";
import os from "node:os";
import crypto from "node:crypto";
import { chromium } from "@playwright/test";
import { adminApi, seedBook, BASE } from "./lib.mjs";

const TESTBOOKS = path.join(os.homedir(), "work/beepub-testbooks");
const BOOKS = {
  "vertical-long": {
    title: "e2e-vertical-long",
    epub: "e2e/fixtures/e2e-vertical-long-book.epub",
    font: "sans",
  },
  sanguo: { title: "三國演義", epub: `${TESTBOOKS}/sanguoyanyi.epub` },
};
const STEPS = [
  {
    name: "margin 48→16px",
    run: (page) =>
      page.evaluate(() =>
        window.__beepubReaderNG.core.setLayout({ margin: 16 }),
      ),
  },
  {
    name: "gap 64px",
    run: (page) =>
      page.evaluate(() => window.__beepubReaderNG.core.setLayout({ gap: 64 })),
  },
  // Hide the header by DOM: a control's own animation would add frames
  // that have nothing to do with the reader.
  {
    name: "header off (display:none)",
    run: (page) =>
      page.evaluate(() => {
        document.querySelector('[data-testid="ng-chrome"]').style.display =
          "none";
      }),
  },
];

const name = process.argv[2] ?? "vertical-long";
const spec = BOOKS[name];
const { token, api } = await adminApi();
const bookId = await seedBook(api, spec.title, spec.epub);
const browser = await chromium.launch();
const context = await browser.newContext({
  baseURL: BASE,
  viewport: { width: 900, height: 700 },
});
await context.addCookies([
  {
    name: "token",
    value: token,
    domain: new URL(BASE).hostname,
    path: "/",
    httpOnly: true,
    secure: false,
    sameSite: "Lax",
  },
]);
const page = await context.newPage();
const params = new URLSearchParams({
  size: "18",
  lh: "1.8",
  mx: "24",
  my: "48",
  // Bare page turns, no fade: the page is read right after each one.
  turn: "instant",
});
if (spec.font) params.set("font", spec.font);
await page.goto(`/books/${bookId}/read?${params}`);
await page.waitForFunction(
  () => !!window.__beepubReaderNG?.core?.lastLocation,
  null,
  { timeout: 60_000 },
);
for (let i = 0; i < 3; i++) {
  await page.evaluate(() => window.__beepubReaderNG.core.next());
  await page.waitForTimeout(250);
}
// The header's % text still changes on relocate, so counts below are an
// upper bound for the reader area.
const cdp = await context.newCDPSession(page);
for (const step of STEPS) {
  const frames = [];
  const onFrame = async ({ data, sessionId, metadata }) => {
    frames.push({
      t: metadata.timestamp,
      hash: crypto.createHash("md5").update(data).digest("hex").slice(0, 8),
    });
    await cdp.send("Page.screencastFrameAck", { sessionId });
  };
  cdp.on("Page.screencastFrame", onFrame);
  await cdp.send("Page.startScreencast", { format: "png", everyNthFrame: 1 });
  await page.waitForTimeout(400);
  const before = frames.length;
  const t0 = Date.now();
  await step.run(page);
  await page.waitForTimeout(1200);
  await cdp.send("Page.stopScreencast");
  cdp.off("Page.screencastFrame", onFrame);
  // collapse consecutive identical frames
  const distinct = [];
  for (const f of frames.slice(Math.max(0, before - 1)))
    if (distinct.at(-1)?.hash !== f.hash) distinct.push(f);
  const base = distinct[0]?.t ?? 0;
  console.log(
    `${step.name}: ${frames.length} frames captured, ${distinct.length} distinct →`,
    distinct
      .map((f) => `${f.hash}@${Math.round((f.t - base) * 1000)}ms`)
      .join(" "),
  );
  await page.waitForTimeout(300);
}
await browser.close();
