import fs from "node:fs";
import {
  test,
  expect,
  type APIRequestContext,
  type CDPSession,
  type Page,
  type TestInfo,
} from "@playwright/test";
import { ADMIN_STATE } from "./helpers";
import {
  ANCHOR_BOOK,
  CHAPTER_ANCHORS_BOOK,
  LONG_CHAPTERS_BOOK,
  NOTES_BOOK,
  VERTICAL_LONG_BOOK,
  VERTICAL_MIXED_BOOK,
  VERTICAL_PLATE_BOOK,
  iphone,
  location,
  openBook,
  seedBook,
  seedFixture,
  touchTap,
  type Fixture,
} from "./ng-helpers";

/**
 * reader-ng: the slide page turn. One page is a sheet that moves over
 * another, and the lower page number is always the upper sheet: going
 * forward the page on screen slides away off the page beneath it, going
 * back the previous page slides in over the one on screen. The page
 * underneath drifts the same way, a quarter as far (the parallax). The
 * other page is a second, inert rendering (a ghost) of the neighbouring
 * page; only the layers' horizontal positions move, so
 * vertical text and a plate laid out against the book's direction slide
 * like any other page. There is a ghost for every section a turn could
 * reach: one in the middle of a chapter, another for the neighbouring
 * chapter near a boundary.
 *
 * Read through the debug handle: `paginator` / `core.getContents()` are
 * always the live section; `core.ghost` is the ghost in the turn under
 * way (else the one on the page ahead), `core.ghostFor(±1)` the one
 * holding the page a turn back or forward, `core.ghosts` all of them,
 * and `core.slideLog` what became of each turn.
 */

test.use({ storageState: ADMIN_STATE, ...iphone });
test.setTimeout(90_000);

interface Layer {
  left: number;
  width: number;
  z: number;
  index: number | null;
  page: number;
  pages: number;
  /** The text on the page this layer shows. */
  text: string;
}

/** Both renderings: where each sits on screen, which is on top, and the
 *  page each shows (pages count from 1 within a section). */
function layers(page: Page): Promise<{ live: Layer; ghost: Layer | null }> {
  return page.evaluate(() => {
    const { core, paginator } = window.__beepubReaderNG;
    const read = (el: any, range: Range | null | undefined) => {
      const r = el.getBoundingClientRect();
      let at = { index: null as number | null, page: -1, pages: -1 };
      try {
        at = {
          index: el.getContents()[0]?.index ?? null,
          page: el.page,
          pages: el.pages,
        };
      } catch {
        // nothing rendered in it yet
      }
      return {
        left: Math.round(r.left),
        width: Math.round(r.width),
        z: Number(getComputedStyle(el).zIndex) || 0,
        ...at,
        text: range?.toString() ?? "",
      };
    };
    const ghost = core.ghost;
    return {
      live: read(paginator, core.lastLocation?.range),
      ghost: ghost ? read(ghost, core.ghostLocation?.range) : null,
    };
  });
}

/** Wait until the ghost shows the page one turn away in `dir`. */
async function ghostReady(page: Page, dir: 1 | -1 = 1) {
  await expect
    .poll(
      () =>
        page.evaluate((dir) => {
          const { core, paginator } = window.__beepubReaderNG;
          const g = core.ghostFor(dir);
          if (!g) return false;
          try {
            const li = paginator.getContents()[0].index;
            const gi = g.getContents()[0]?.index;
            if (dir > 0)
              return paginator.page < paginator.pages - 2
                ? gi === li &&
                    g.page === paginator.page + 1 &&
                    g.pages === paginator.pages
                : gi > li && g.page === 1;
            return paginator.page > 1
              ? gi === li &&
                  g.page === paginator.page - 1 &&
                  g.pages === paginator.pages
              : gi < li && g.page === g.pages - 2;
          } catch {
            return false;
          }
        }, dir),
      { timeout: 10_000 },
    )
    .toBe(true);
  await page.waitForTimeout(100);
}

/** At rest: the live page flat and on top, nothing animating, taps
 *  reaching it again. */
function settled(page: Page): Promise<boolean> {
  return page.evaluate(() => {
    const { core, paginator } = window.__beepubReaderNG;
    const style = getComputedStyle(paginator);
    if (paginator.getBoundingClientRect().left !== 0) return false;
    if (paginator.getAnimations().length) return false;
    if (style.pointerEvents === "none" || style.opacity !== "1") return false;
    return (core.ghosts as HTMLElement[]).every(
      (ghost) =>
        ghost.getBoundingClientRect().left === 0 &&
        ghost.getAnimations().length === 0 &&
        Number(getComputedStyle(ghost).zIndex) < Number(style.zIndex),
    );
  });
}

/** Record how each page turn from here on is animated: a layer's
 *  transform (the slide) or the page's opacity (the fade). */
function watchTurns(page: Page) {
  return page.evaluate(() => {
    const { paginator } = window.__beepubReaderNG;
    window.__turns = [];
    // On the element class: ghosts come and go.
    const proto = customElements.get("foliate-paginator")!.prototype;
    // (Asked for again, the record starts over: one wrapper.)
    if (proto.__watched) return;
    proto.__watched = true;
    const animate = proto.animate;
    proto.animate = function (
      this: HTMLElement,
      keyframes: Keyframe[],
      options: unknown,
    ) {
      const last = keyframes[keyframes.length - 1]!;
      // The sheet that slides is the one with the shadow; the page
      // drifting underneath it is not a turn of its own.
      if ("transform" in last && !this.style.boxShadow)
        return animate.call(this, keyframes, options);
      window.__turns!.push(
        `${this === paginator ? "live" : "ghost"}:${"transform" in last ? "slide" : "fade"}`,
      );
      return animate.call(this, keyframes, options);
    };
  });
}

function turns(page: Page): Promise<string[]> {
  return page.evaluate(() => window.__turns ?? []);
}

type Point = { x: number; y: number };

function touchDown(cdp: CDPSession, at: Point) {
  return cdp.send("Input.dispatchTouchEvent", {
    type: "touchStart",
    touchPoints: [at],
  });
}

/** Move the finger from `from` to `to` in even steps, a frame apart. */
async function touchMove(
  cdp: CDPSession,
  from: Point,
  to: Point,
  steps: number,
) {
  for (let i = 1; i <= steps; i++) {
    await new Promise((resolve) => setTimeout(resolve, 16));
    await cdp.send("Input.dispatchTouchEvent", {
      type: "touchMove",
      touchPoints: [
        {
          x: from.x + ((to.x - from.x) * i) / steps,
          y: from.y + ((to.y - from.y) * i) / steps,
        },
      ],
    });
  }
}

function touchUp(cdp: CDPSession) {
  return cdp.send("Input.dispatchTouchEvent", {
    type: "touchEnd",
    touchPoints: [],
  });
}

const at = (x: number): Point => ({ x, y: 400 });

/** The page under the sheet travels this much of the width (slide.ts). */
const PARALLAX = 0.25;

/** Where a layer stands, to the pixel or two a rounded transform gives. */
function expectLeft(layer: Layer | null, left: number) {
  expect(layer).not.toBeNull();
  expect(Math.abs(layer!.left - left)).toBeLessThanOrEqual(2);
}

/** Wait for a layer to stand `left` px from the reader's left edge and
 *  return both layers. (A touch move is delivered with the next frame,
 *  after CDP has answered: the state has to be polled for.) */
async function layersWhen(page: Page, which: "live" | "ghost", left: number) {
  await expect
    .poll(async () => {
      const l = (await layers(page))[which];
      return l ? Math.abs(l.left - left) <= 2 : false;
    })
    .toBe(true);
  return layers(page);
}

function goTo(page: Page, target: unknown) {
  return page.evaluate(
    (target) => void window.__beepubReaderNG.core.goTo(target),
    target,
  );
}

async function openSettings(page: Page, cdp: CDPSession) {
  await touchTap(cdp, { x: 195, y: 420 }, 60);
  const bar = page.getByRole("toolbar", { name: "Reading controls" });
  await expect(bar).toBeVisible();
  await bar.getByRole("button", { name: "Reader settings" }).click();
  await expect(page.getByText("Line spacing")).toBeVisible();
}

test("a horizontal book: the page on screen follows the finger off the next page, and the previous page slides back in over it", async ({
  page,
  context,
}, testInfo) => {
  const bookId = await seedFixture(page.request, ANCHOR_BOOK);
  await openBook(page, bookId, { turn: "slide", size: "24" }, ANCHOR_BOOK);
  const cdp = await context.newCDPSession(page);
  await ghostReady(page, 1);
  const rest = await layers(page);
  expect(rest.live.pages - 2).toBeGreaterThanOrEqual(3);
  expect(rest.live.left).toBe(0);
  expect(rest.ghost!.z).toBeLessThan(rest.live.z);
  const width = rest.live.width;

  // Forward in a left-to-right book: the finger goes left, and the page
  // on screen goes with it, 1:1. The next page lies underneath…
  await touchDown(cdp, at(320));
  await touchMove(cdp, at(320), at(200), 10);
  const mid = await layersWhen(page, "live", -120);
  // …pushed a little to the right, on its way to rest.
  expectLeft(mid.ghost, PARALLAX * (width - 120));
  expect(mid.ghost!.z).toBeLessThan(mid.live.z);
  expect(mid.ghost).toMatchObject({
    index: rest.live.index,
    page: rest.live.page + 1,
    pages: rest.live.pages,
  });
  expect(mid.ghost!.text.length).toBeGreaterThan(40);
  expect(mid.ghost!.text).not.toBe(mid.live.text);
  // The reader itself has not moved yet.
  expect(mid.live.page).toBe(rest.live.page);
  // (Kept with the run's output: what the two sheets look like mid-turn.)
  await page.screenshot({ path: testInfo.outputPath("mid-slide.png") });

  // Released past half the page, the turn completes: the live reader is
  // on the page that lay underneath, flat and on top again.
  await touchMove(cdp, at(200), at(60), 6);
  await touchUp(cdp);
  await expect
    .poll(async () => (await layers(page)).live.page)
    .toBe(rest.live.page + 1);
  await expect.poll(() => settled(page)).toBe(true);
  const next = await layers(page);
  expect(next.live.text).toBe(mid.ghost!.text);
  expect((await location(page)).reason).toBe("page");

  // A short, slow drag springs back to the same page.
  await touchDown(cdp, at(320));
  await touchMove(cdp, at(320), at(250), 10);
  await layersWhen(page, "live", -70);
  await page.waitForTimeout(250);
  await touchUp(cdp);
  await expect.poll(() => settled(page)).toBe(true);
  expect((await layers(page)).live.page).toBe(next.live.page);

  // Back: the finger goes right and pulls the previous page in from the
  // left, over the page on screen, which gives way a little.
  await touchDown(cdp, at(60));
  await touchMove(cdp, at(60), at(210), 10);
  const back = await layersWhen(page, "ghost", 150 - width);
  expectLeft(back.live, PARALLAX * 150);
  expect(back.ghost!.z).toBeGreaterThan(back.live.z);
  expect(back.ghost).toMatchObject({
    index: rest.live.index,
    page: rest.live.page,
  });
  expect(back.ghost!.text).toBe(rest.live.text);
  await touchMove(cdp, at(210), at(340), 6);
  await touchUp(cdp);
  await expect
    .poll(async () => (await layers(page)).live.page)
    .toBe(rest.live.page);
  await expect.poll(() => settled(page)).toBe(true);
  expect((await layers(page)).live.text).toBe(rest.live.text);
});

/** The two curves and the times (slide.ts). */
const TURN_MS = 520;
const EASE_FROM_REST = "cubic-bezier(0.42, 0, 0.35, 1)";
const EASE_RELEASED = "cubic-bezier(0.2, 0.5, 0.3, 1)";
const RELEASED_MS = 400;
const SETTLE_MIN_MS = 120;

test("a turn from rest sets off, travels and settles over its time; a sheet the finger lets go of only comes to rest, in what is left of a shorter one", async ({
  page,
  context,
}) => {
  const bookId = await seedFixture(page.request, ANCHOR_BOOK);
  await openBook(page, bookId, { turn: "slide", size: "24" }, ANCHOR_BOOK);
  const cdp = await context.newCDPSession(page);
  await ghostReady(page);
  // Every animation the reader starts, as it was asked for (not sampled
  // while it runs: nothing here depends on when the test looks).
  await page.evaluate(() => {
    const asked: { easing: string; duration: number }[] = ((
      window as any
    ).__asked = []);
    const animate = Element.prototype.animate;
    Element.prototype.animate = function (keyframes: any, options: any) {
      if (keyframes?.[0] && "transform" in keyframes[0])
        asked.push({ easing: options.easing, duration: options.duration });
      return animate.call(this, keyframes, options);
    };
  });
  const asked = async () => {
    const list = await page.evaluate(() => (window as any).__asked.splice(0));
    return list as { easing: string; duration: number }[];
  };
  const livePage = async () => (await layers(page)).live.page;
  const start = await livePage();

  // By key: from rest, the whole time, both sheets on the one curve.
  await page.keyboard.press("PageDown");
  await expect.poll(livePage).toBe(start + 1);
  await expect.poll(() => settled(page)).toBe(true);
  let list = await asked();
  expect(list).toEqual([
    { easing: EASE_FROM_REST, duration: TURN_MS },
    { easing: EASE_FROM_REST, duration: TURN_MS },
  ]);

  // A turn asked for while one slides ends that one there and then
  // (seen on the animations themselves, not on a clock): the longer
  // turn holds nobody up.
  await ghostReady(page);
  const cut = await page.evaluate(
    () =>
      new Promise<string[]>((resolve) => {
        const { core, paginator } = window.__beepubReaderNG;
        const sheets = [paginator, ...core.ghosts] as HTMLElement[];
        core.next();
        setTimeout(() => {
          const running = sheets.flatMap((el) => el.getAnimations());
          core.next();
          setTimeout(() => resolve(running.map((a) => a.playState)), 0);
        }, 100);
      }),
  );
  expect(cut.length).toBeGreaterThan(0);
  expect(new Set(cut)).toEqual(new Set(["finished"]));
  await expect.poll(livePage).toBe(start + 3);
  await expect.poll(() => settled(page)).toBe(true);
  await asked();

  // Dragged slowly past half the page and let go at rest: it comes to
  // rest on the released curve, in the share of its time that is left.
  await ghostReady(page);
  await touchDown(cdp, at(330));
  await touchMove(cdp, at(330), at(100), 10);
  await layersWhen(page, "live", -230);
  await page.waitForTimeout(250);
  await touchUp(cdp);
  await expect.poll(livePage).toBe(start + 4);
  await expect.poll(() => settled(page)).toBe(true);
  list = await asked();
  expect(list.map((a) => a.easing)).toEqual([EASE_RELEASED, EASE_RELEASED]);
  const width = page.viewportSize()!.width;
  const rest = Math.round(RELEASED_MS * (1 - 230 / width));
  expect(Math.abs(list[0].duration - rest)).toBeLessThanOrEqual(8);

  // Flicked: the same curve, within the released sheet's times. (How
  // long exactly is the finger's speed and where the sheet stood, which
  // a test's touches do not have to the millisecond: only the bounds
  // are held to.)
  await ghostReady(page);
  await touchDown(cdp, at(330));
  await touchMove(cdp, at(330), at(230), 2);
  await touchUp(cdp);
  await expect.poll(livePage).toBe(start + 5);
  await expect.poll(() => settled(page)).toBe(true);
  list = await asked();
  expect(list.map((a) => a.easing)).toEqual([EASE_RELEASED, EASE_RELEASED]);
  expect(list[0].duration).toBeGreaterThanOrEqual(SETTLE_MIN_MS);
  expect(list[0].duration).toBeLessThan(RELEASED_MS);

  // A short drag let go: it springs back, coming to rest the same way.
  await touchDown(cdp, at(320));
  await touchMove(cdp, at(320), at(250), 10);
  await layersWhen(page, "live", -70);
  await page.waitForTimeout(250);
  await touchUp(cdp);
  await expect.poll(() => settled(page)).toBe(true);
  expect(await livePage()).toBe(start + 5);
  list = await asked();
  expect(list.map((a) => a.easing)).toEqual([EASE_RELEASED, EASE_RELEASED]);
  expect(list[0].duration).toBe(SETTLE_MIN_MS);
});

test("a vertical book slides too, the other way round, and the sheet offers the choice", async ({
  page,
  context,
}) => {
  // Numbered paragraphs: every page reads differently.
  const bookId = await seedFixture(page.request, CHAPTER_ANCHORS_BOOK);
  await openBook(
    page,
    bookId,
    { turn: "slide", font: "sans" },
    CHAPTER_ANCHORS_BOOK,
  );
  expect(
    await page.evaluate(() => {
      const core = window.__beepubReaderNG.core;
      return [core.vertical, core.advancesLeftward(), core.effectivePageTurn()];
    }),
  ).toEqual([true, true, "slide"]);
  const cdp = await context.newCDPSession(page);
  await ghostReady(page, 1);
  const rest = await layers(page);
  test.skip(
    rest.live.pages - 2 < 3,
    "vertical fragmentation degenerate — CJK fonts missing",
  );
  const width = rest.live.width;

  // The book advances leftward: forward is the finger going right, and
  // the page on screen leaves to the right.
  await touchDown(cdp, at(80));
  await touchMove(cdp, at(80), at(200), 10);
  const mid = await layersWhen(page, "live", 120);
  expectLeft(mid.ghost, -PARALLAX * (width - 120));
  expect(mid.ghost!.z).toBeLessThan(mid.live.z);
  expect(mid.ghost).toMatchObject({
    index: rest.live.index,
    page: rest.live.page + 1,
    pages: rest.live.pages,
  });
  expect(mid.ghost!.text).not.toBe(mid.live.text);
  await touchMove(cdp, at(200), at(340), 6);
  await touchUp(cdp);
  await expect
    .poll(async () => (await layers(page)).live.page)
    .toBe(rest.live.page + 1);
  await expect.poll(() => settled(page)).toBe(true);
  expect((await layers(page)).live.text).toBe(mid.ghost!.text);

  // A short drag springs back.
  await touchDown(cdp, at(80));
  await touchMove(cdp, at(80), at(140), 10);
  await layersWhen(page, "live", 60);
  await page.waitForTimeout(250);
  await touchUp(cdp);
  await expect.poll(() => settled(page)).toBe(true);
  expect((await layers(page)).live.page).toBe(rest.live.page + 1);

  // Back: the finger goes left, the previous page comes in from the
  // right over the page on screen.
  await touchDown(cdp, at(330));
  await touchMove(cdp, at(330), at(180), 10);
  const back = await layersWhen(page, "ghost", width - 150);
  expectLeft(back.live, -PARALLAX * 150);
  expect(back.ghost!.z).toBeGreaterThan(back.live.z);
  expect(back.ghost!.text).toBe(rest.live.text);
  await touchMove(cdp, at(180), at(50), 6);
  await touchUp(cdp);
  await expect
    .poll(async () => (await layers(page)).live.page)
    .toBe(rest.live.page);
  await expect.poll(() => settled(page)).toBe(true);
  expect((await layers(page)).live.text).toBe(rest.live.text);

  // The settings sheet offers both modes for a vertical book.
  await openSettings(page, cdp);
  await expect(
    page.getByTestId("setting-page-turn").getByRole("button"),
  ).toHaveText(["Fast fade", "Slide"]);
});

/** Whether the two sheets of the turn under way leave any of the
 *  reader's width bare, and where each stands. (Only those two: a third
 *  rendering lying idle beneath them would hide a gap from this probe,
 *  not from the eye that knows the page.) */
interface Sheets {
  bare: boolean;
  live: number;
  ghost: number;
}

/** Put the probe in the page: `__sheets()` reads the two sheets now. */
function installSheets(page: Page) {
  return page.evaluate(() => {
    (window as any).__sheets = (): Sheets => {
      const { core, paginator } = window.__beepubReaderNG;
      const box = paginator.parentElement.getBoundingClientRect();
      const live = paginator.getBoundingClientRect();
      const ghost = (core.ghost as HTMLElement).getBoundingClientRect();
      const [a, b] = live.left <= ghost.left ? [live, ghost] : [ghost, live];
      const bare =
        a.left > box.left + 0.5 ||
        b.left > a.right + 0.5 ||
        Math.max(a.right, b.right) < box.right - 0.5;
      return {
        bare,
        live: live.left - box.left,
        ghost: ghost.left - box.left,
      };
    };
  });
}

/** Sample the sheets every frame from now until stopSampling. */
function startSampling(page: Page) {
  return page.evaluate(() => {
    const samples: Sheets[] = [];
    let on = true;
    const tick = () => {
      if (!on) return;
      try {
        samples.push((window as any).__sheets());
      } catch {
        // between two ghosts
      }
      requestAnimationFrame(tick);
    };
    tick();
    (window as any).__stopSampling = () => {
      on = false;
      return samples;
    };
  });
}

function stopSampling(page: Page): Promise<Sheets[]> {
  return page.evaluate(() => (window as any).__stopSampling());
}

for (const kind of ["horizontal", "vertical"] as const) {
  test(`the page under the sheet drifts a quarter as far, the same way, and no edge is ever bare: ${kind}`, async ({
    page,
    context,
  }) => {
    const fixture = kind === "vertical" ? CHAPTER_ANCHORS_BOOK : ANCHOR_BOOK;
    const bookId = await seedFixture(page.request, fixture);
    await openBook(
      page,
      bookId,
      kind === "vertical"
        ? { turn: "slide", font: "sans" }
        : { turn: "slide", size: "24" },
      fixture,
    );
    const cdp = await context.newCDPSession(page);
    await ghostReady(page, 1);
    const rest = await layers(page);
    test.skip(
      rest.live.pages - 2 < 3,
      "vertical fragmentation degenerate — CJK fonts missing",
    );
    const width = rest.live.width;
    const leftward = await page.evaluate(() =>
      window.__beepubReaderNG.core.advancesLeftward(),
    );
    expect(leftward).toBe(kind === "vertical");
    // The way the finger goes to turn forward, and the side the upper
    // sheet goes off at: left in a left-to-right book.
    const s = leftward ? 1 : -1;
    const DRAG = 190; // just short of half the page
    const pull = async (sign: number, px: number) => {
      const from = sign > 0 ? 50 : 340;
      await touchDown(cdp, at(from));
      await touchMove(cdp, at(from), at(from + sign * px), 10);
      return from + sign * px;
    };
    await installSheets(page);
    const sheets = (): Promise<Sheets> =>
      page.evaluate(() => (window as any).__sheets());

    // Forward, the finger held just short of half way: the page on
    // screen has gone with it, and the next page, underneath, stands
    // half of its quarter-width short of rest, on the side the sheet is
    // not — it is moving the way the sheet moves.
    let x = await pull(s, DRAG);
    let mid = await layersWhen(page, "live", s * DRAG);
    expectLeft(mid.ghost, -s * PARALLAX * (width - DRAG));
    expect(mid.ghost!.z).toBeLessThan(mid.live.z);
    expect((await sheets()).bare).toBe(false);
    // Let go there, at rest: it springs back, and both lie flat again.
    await page.waitForTimeout(250);
    await startSampling(page);
    await touchUp(cdp);
    await expect.poll(() => settled(page)).toBe(true);
    let seen = await stopSampling(page);
    expect(seen.length).toBeGreaterThan(3);
    expect(seen.filter((f) => f.bare)).toEqual([]);
    expect((await layers(page)).live.page).toBe(rest.live.page);

    // Again, and through: the page underneath comes to rest as the
    // sheet leaves, never ahead of it and never the other way.
    await ghostReady(page, 1);
    x = await pull(s, DRAG);
    await layersWhen(page, "live", s * DRAG);
    await startSampling(page);
    await touchMove(cdp, at(x), at(x + s * 100), 6);
    await touchUp(cdp);
    await expect
      .poll(async () => (await layers(page)).live.page)
      .toBe(rest.live.page + 1);
    await expect.poll(() => settled(page)).toBe(true);
    seen = await stopSampling(page);
    expect(seen.filter((f) => f.bare)).toEqual([]);
    // (Until the turn lands the ghost is the page underneath.)
    const under = seen
      .filter((f) => Math.abs(f.live) > 1)
      .map((f) => -s * f.ghost);
    expect(under.length).toBeGreaterThan(3);
    for (const offset of under) {
      expect(offset).toBeGreaterThanOrEqual(-1);
      expect(offset).toBeLessThanOrEqual(PARALLAX * (width - DRAG) + 2);
    }
    for (let i = 1; i < under.length; i++)
      expect(under[i]!).toBeLessThanOrEqual(under[i - 1]! + 1);

    // Back: the previous page comes in over the page on screen, which
    // gives way before it — half of its quarter-width by half way.
    x = await pull(-s, DRAG);
    mid = await layersWhen(page, "ghost", s * (width - DRAG));
    expectLeft(mid.live, -s * PARALLAX * DRAG);
    expect(mid.ghost!.z).toBeGreaterThan(mid.live.z);
    expect((await sheets()).bare).toBe(false);
    await page.waitForTimeout(250);
    await startSampling(page);
    await touchUp(cdp);
    await expect.poll(() => settled(page)).toBe(true);
    seen = await stopSampling(page);
    expect(seen.length).toBeGreaterThan(3);
    expect(seen.filter((f) => f.bare)).toEqual([]);
    expect((await layers(page)).live.page).toBe(rest.live.page + 1);

    x = await pull(-s, DRAG);
    await layersWhen(page, "ghost", s * (width - DRAG));
    await startSampling(page);
    await touchMove(cdp, at(x), at(x - s * 100), 6);
    await touchUp(cdp);
    await expect
      .poll(async () => (await layers(page)).live.page)
      .toBe(rest.live.page);
    await expect.poll(() => settled(page)).toBe(true);
    seen = await stopSampling(page);
    expect(seen.filter((f) => f.bare)).toEqual([]);
    expect((await layers(page)).live.text).toBe(rest.live.text);

    // Reduced motion: no sheet follows the finger, and nothing drifts.
    await page.emulateMedia({ reducedMotion: "reduce" });
    await pull(s, DRAG);
    await page.waitForTimeout(150);
    const still = await page.evaluate(() => {
      const { core, paginator } = window.__beepubReaderNG;
      return [paginator, ...(core.ghosts as HTMLElement[])].map(
        (el) =>
          `${el.style.transform}|${Math.round(el.getBoundingClientRect().left)}`,
      );
    });
    expect(still).toEqual(still.map(() => "|0"));
    await touchUp(cdp);
    await expect
      .poll(async () => (await layers(page)).live.page)
      .toBe(rest.live.page + 1);
    expect(await settled(page)).toBe(true);
  });
}

test("across a chapter boundary: forward onto the next chapter's first page, back onto the previous chapter's last", async ({
  page,
  context,
}) => {
  const bookId = await seedFixture(page.request, CHAPTER_ANCHORS_BOOK);
  await openBook(
    page,
    bookId,
    { turn: "slide", font: "sans" },
    CHAPTER_ANCHORS_BOOK,
  );
  const cdp = await context.newCDPSession(page);

  // The last page of the first chapter: the ghost holds the next
  // chapter's first page.
  await goTo(page, { index: 0, fraction: 1 });
  await expect
    .poll(async () => {
      const { live } = await layers(page);
      return live.index === 0 && live.page === live.pages - 2;
    })
    .toBe(true);
  await ghostReady(page, 1);
  const end = await layers(page);
  expect(end.ghost).toMatchObject({ index: 1, page: 1 });
  await watchTurns(page);

  await page.keyboard.press("PageDown");
  await expect.poll(async () => (await layers(page)).live.index).toBe(1);
  await expect.poll(() => settled(page)).toBe(true);
  const start = await layers(page);
  expect(start.live.page).toBe(1);
  expect(start.live.text).toBe(end.ghost!.text);
  expect(await turns(page)).toEqual(["live:slide"]);
  expect(await page.evaluate(() => window.__beepubReaderNG.core.vertical)).toBe(
    true,
  );

  // Straight back: the first chapter never left its ghost, which only
  // has to step onto the last page, and that slides in — no load, no
  // fade.
  expect((await layers(page)).ghost!.index).toBe(1);
  expect(
    await page.evaluate(() =>
      (window.__beepubReaderNG.core.ghosts as any[]).map(
        (g) => g.getContents()[0]?.index,
      ),
    ),
  ).toContain(0);
  await page.keyboard.press("PageUp");
  await expect
    .poll(async () => {
      const { live } = await layers(page);
      return live.index === 0 && live.page === live.pages - 2;
    })
    .toBe(true);
  await expect.poll(() => settled(page)).toBe(true);
  expect((await layers(page)).live.text).toBe(end.live.text);
  expect((await turns(page)).slice(1)).toEqual(["ghost:slide"]);

  // Forward again, and back with the finger at once: the ghost is on
  // the page ahead when the pull begins…
  await page.keyboard.press("PageDown");
  await expect.poll(async () => (await layers(page)).live.index).toBe(1);
  await expect.poll(() => settled(page)).toBe(true);
  await ghostReady(page, 1);
  expect((await layers(page)).ghost!.index).toBe(1);

  // …and the previous chapter's last page, on a ghost of its own, comes
  // in over the page on screen with the finger.
  await touchDown(cdp, at(330));
  await touchMove(cdp, at(330), at(180), 10);
  const back = await layersWhen(page, "ghost", end.live.width - 150);
  expectLeft(back.live, -PARALLAX * 150);
  expect(back.live.index).toBe(1);
  expect(back.ghost!.z).toBeGreaterThan(back.live.z);
  expect(back.ghost!.index).toBe(0);
  expect(back.ghost!.page).toBe(back.ghost!.pages - 2);
  expect(back.ghost!.text).toBe(end.live.text);
  // It goes on following the finger, 1:1.
  await touchMove(cdp, at(180), at(120), 4);
  await layersWhen(page, "ghost", end.live.width - 210);
  await touchMove(cdp, at(120), at(50), 4);
  await touchUp(cdp);
  await expect.poll(async () => (await layers(page)).live.index).toBe(0);
  await expect.poll(() => settled(page)).toBe(true);
  const landed = await layers(page);
  expect(landed.live.page).toBe(landed.live.pages - 2);
  expect(landed.live.text).toBe(end.live.text);
  // Not one of these turns faded.
  expect((await turns(page)).filter((t) => t.endsWith("fade"))).toEqual([]);

  // A pull that stops short springs back, the joined sheet included.
  await page.keyboard.press("PageDown");
  await expect.poll(async () => (await layers(page)).live.index).toBe(1);
  await expect.poll(() => settled(page)).toBe(true);
  await ghostReady(page, 1);
  await touchDown(cdp, at(330));
  await touchMove(cdp, at(330), at(250), 8);
  await layersWhen(page, "ghost", end.live.width - 80);
  await page.waitForTimeout(250);
  await touchUp(cdp);
  await expect.poll(() => settled(page)).toBe(true);
  expect((await layers(page)).live).toMatchObject({ index: 1, page: 1 });

  // Paging quickly out of the first chapter: the turn that crosses into
  // the second finds its page in time and slides like the ones before.
  await goTo(page, { index: 0, fraction: 1 });
  await expect.poll(async () => (await layers(page)).live.index).toBe(0);
  const back2 = Math.min(2, end.live.page - 1);
  for (let i = 1; i <= back2; i++) {
    await page.keyboard.press("PageUp");
    await expect
      .poll(async () => (await layers(page)).live.page)
      .toBe(end.live.page - i);
    await expect.poll(() => settled(page)).toBe(true);
  }
  await watchTurns(page);
  await page.evaluate(
    (count) =>
      new Promise<void>((resolve) => {
        const core = window.__beepubReaderNG.core;
        let left = count;
        const step = () => {
          core.next();
          if (--left) setTimeout(step, 140);
          else resolve();
        };
        step();
      }),
    back2 + 1,
  );
  await expect
    .poll(async () => {
      const { live } = await layers(page);
      return [live.index, live.page];
    })
    .toEqual([1, 1]);
  await expect.poll(() => settled(page)).toBe(true);
  // (The last one may be the sheet over the live page that slides away:
  // the turn before it is still being made underneath.)
  const quick = await turns(page);
  expect(quick).toHaveLength(back2 + 1);
  expect(quick.filter((t) => !t.endsWith(":slide"))).toEqual([]);
});

test("the very first turn slides, before the second rendering has loaded", async ({
  page,
}) => {
  const bookId = await seedFixture(page.request, ANCHOR_BOOK);
  await openBook(page, bookId, { turn: "slide", size: "24" }, ANCHOR_BOOK);
  const before = (await layers(page)).live;
  // A second rendering made this instant — what a reader who turns the
  // moment the book opens meets — and the turn asked for in the same
  // task: nothing has loaded into it.
  await watchTurns(page);
  const loaded = await page.evaluate(() => {
    const { core } = window.__beepubReaderNG;
    core.setPageTurn("fade");
    core.setPageTurn("slide");
    const loaded = core.ghost.getContents().length;
    void core.next();
    return loaded;
  });
  expect(loaded).toBe(0);
  await expect
    .poll(async () => (await layers(page)).live.page)
    .toBe(before.page + 1);
  await expect.poll(() => settled(page)).toBe(true);
  expect(await turns(page)).toEqual(["live:slide"]);
});

test("a page no ghost has yet: a finger lifted before it is there still gets its slide; one that takes long slides over bare paper", async ({
  page,
  context,
}) => {
  const bookId = await seedFixture(page.request, CHAPTER_ANCHORS_BOOK);
  await openBook(
    page,
    bookId,
    { turn: "slide", font: "sans" },
    CHAPTER_ANCHORS_BOOK,
  );
  const cdp = await context.newCDPSession(page);
  await goTo(page, { index: 0, fraction: 1 });
  await expect
    .poll(async () => {
      const { live } = await layers(page);
      return live.index === 0 && live.page === live.pages - 2;
    })
    .toBe(true);
  const end = (await layers(page)).live;

  /** Hold every load of the first chapter back: until `ms` after the
   *  finger lifts (touch), `ms` after it is asked for, or — "held" —
   *  until the test lets it go (`__releaseLoad`). */
  const slowFirstChapter = (ms: number, from: "lift" | "ask" | "held") =>
    page.evaluate(
      ({ ms, from }) => {
        const { core } = window.__beepubReaderNG;
        const section = core.book.sections[0];
        const load = section.load;
        window.__lift = null;
        let open: () => void = () => {};
        const lifted = new Promise<void>((resolve) => (open = resolve));
        window.__armLift = () =>
          (core.getContents()[0].doc as Document).addEventListener(
            "touchend",
            () => {
              window.__lift = {
                ghostIndex: core.ghostFor(-1)?.getContents()[0]?.index ?? null,
              };
              setTimeout(open, ms);
            },
            { capture: true, once: true },
          );
        let release: () => void = () => {};
        const released = new Promise<void>((resolve) => (release = resolve));
        window.__releaseLoad = release;
        section.load = async () => {
          if (from === "lift") await lifted;
          else if (from === "held") await released;
          else await new Promise((resolve) => setTimeout(resolve, ms));
          return load();
        };
        window.__restoreLoad = () => (section.load = load);
      },
      { ms, from },
    );
  /** A jump onto the second chapter's first page with the first chapter
   *  slow to load: the ghost sent for it does not have it yet. */
  const arrive = async (ms: number, from: "lift" | "ask" | "held") => {
    await goTo(page, { index: 2, fraction: 1 });
    await expect.poll(async () => (await layers(page)).live.index).toBe(2);
    await expect
      .poll(() =>
        page.evaluate(() =>
          (window.__beepubReaderNG.core.ghosts as any[]).every(
            (g) => g.getContents()[0]?.index !== 0,
          ),
        ),
      )
      .toBe(true);
    await slowFirstChapter(ms, from);
    await goTo(page, { index: 1, fraction: 0 });
    await expect
      .poll(async () => {
        const { live } = await layers(page);
        return live.index === 1 && live.page === 1;
      })
      .toBe(true);
    await page.evaluate(() => window.__armLift!());
    await watchTurns(page);
  };

  // The finger flicks back and is gone before the first chapter can be
  // in a ghost (its load is held until after the lift): the turn is
  // made all the same, as a slide.
  await arrive(40, "lift");
  await touchDown(cdp, at(330));
  await touchMove(cdp, at(330), at(210), 4);
  await touchUp(cdp);
  await expect.poll(async () => (await layers(page)).live.index).toBe(0);
  await expect.poll(() => settled(page)).toBe(true);
  expect(await page.evaluate(() => window.__lift)).toEqual({
    ghostIndex: null,
  });
  const landed = (await layers(page)).live;
  expect(landed.page).toBe(landed.pages - 2);
  expect(landed.text).toBe(end.text);
  expect(await turns(page)).toEqual(["ghost:slide"]);

  // A slow, short swipe — some 80px, the finger resting before it lifts
  // — that no sheet followed is the plain swipe it looked like: it turns
  // the page (a sheet under the finger would have sprung back).
  await page.evaluate(() => window.__restoreLoad!());
  await arrive(40, "lift");
  await touchDown(cdp, at(330));
  await touchMove(cdp, at(330), at(250), 8);
  await page.waitForTimeout(200);
  expect((await layers(page)).live.left).toBe(0);
  await touchUp(cdp);
  await expect.poll(async () => (await layers(page)).live.index).toBe(0);
  await expect.poll(() => settled(page)).toBe(true);
  expect(await turns(page)).toEqual(["ghost:slide"]);

  // The same by key, the chapter a little slow to load: it waits, then
  // slides.
  await page.evaluate(() => window.__restoreLoad!());
  await arrive(60, "ask");
  await page.keyboard.press("PageUp");
  await expect.poll(async () => (await layers(page)).live.index).toBe(0);
  await expect.poll(() => settled(page)).toBe(true);
  expect(await turns(page)).toEqual(["ghost:slide"]);

  // Too slow (well past the wait): the turn does not hang on the ghost
  // and does not change its kind either — it slides, a sheet of bare
  // paper standing in for the page, which comes up on it when it is
  // there. (The chapter is held until the paper has been seen lying
  // there, not for a time: a load that came "900ms after it was asked
  // for" was asked for before the swipe, and left the paper at rest for
  // a moment a slow machine's polling stepped over.)
  await page.evaluate(() => window.__restoreLoad!());
  await arrive(0, "held");
  await touchDown(cdp, at(330));
  await touchMove(cdp, at(330), at(210), 4);
  await touchUp(cdp);
  const paper = () =>
    page.evaluate(() => {
      const blank = document.querySelector<HTMLElement>("[data-beepub-blank]")!;
      return (
        getComputedStyle(blank).display !== "none" &&
        blank.getBoundingClientRect().left === 0
      );
    });
  await expect.poll(paper).toBe(true);
  expect(
    await page.evaluate(() => {
      const { core } = window.__beepubReaderNG;
      const last = core.slideLog.filter((e: any) => e.how).at(-1);
      return [last.how, last.blank];
    }),
  ).toEqual(["slide", true]);
  // Still the page it was turned from underneath, for as long as the
  // chapter does not come.
  expect((await layers(page)).live.index).toBe(1);
  await page.evaluate(() => window.__releaseLoad!());
  await expect
    .poll(async () => {
      const { live } = await layers(page);
      return [live.index, live.pages - 2 - live.page];
    })
    .toEqual([0, 0]);
  await expect.poll(() => settled(page)).toBe(true);
  expect(await paper()).toBe(false);
  expect((await layers(page)).live.text).toBe(end.text);
  expect((await turns(page)).filter((t) => t.endsWith("fade"))).toEqual([]);

  // The ghosts catch up afterwards and the next turn slides again.
  await page.evaluate(() => window.__restoreLoad!());
  await ghostReady(page, -1);
  await watchTurns(page);
  await page.keyboard.press("PageUp");
  await expect
    .poll(async () => {
      const { live } = await layers(page);
      return [live.index, live.pages - 2 - live.page];
    })
    .toEqual([0, 1]);
  await expect.poll(() => settled(page)).toBe(true);
  expect(await turns(page)).toEqual(["ghost:slide"]);
});

test("a ghost whose section never arrives is replaced, and the slide comes back", async ({
  page,
}) => {
  const bookId = await seedFixture(page.request, CHAPTER_ANCHORS_BOOK);
  await openBook(
    page,
    bookId,
    { turn: "slide", font: "sans" },
    CHAPTER_ANCHORS_BOOK,
  );
  await goTo(page, { index: 2, fraction: 1 });
  await expect.poll(async () => (await layers(page)).live.index).toBe(2);
  await expect
    .poll(() =>
      page.evaluate(() =>
        (window.__beepubReaderNG.core.ghosts as any[]).every(
          (g) => g.getContents()[0]?.index !== 0,
        ),
      ),
    )
    .toBe(true);
  // The next load of the first chapter — the ghost's, sent for it by the
  // jump below — never answers (the section itself loads as ever).
  await page.evaluate(() => {
    const { core } = window.__beepubReaderNG;
    const section = core.book.sections[0];
    const load = section.load;
    section.load = () => {
      section.load = load;
      void load();
      return new Promise(() => {});
    };
  });
  await goTo(page, { index: 1, fraction: 0 });
  await expect
    .poll(async () => {
      const { live } = await layers(page);
      return live.index === 1 && live.page === 1;
    })
    .toBe(true);
  await expect
    .poll(() =>
      page.evaluate(() => {
        const { core } = window.__beepubReaderNG;
        window.__stuckGhost = core.ghostFor(-1);
        return !!window.__stuckGhost;
      }),
    )
    .toBe(true);
  await watchTurns(page);
  await page.keyboard.press("PageUp");
  // The turn slides onto bare paper and waits there; when the step is
  // given up for lost a new ghost takes it over, and the page comes.
  // Nothing fades.
  await expect
    .poll(async () => (await layers(page)).live.index, { timeout: 20_000 })
    .toBe(0);
  await expect.poll(() => settled(page)).toBe(true);
  expect((await turns(page)).filter((t) => t.endsWith("fade"))).toEqual([]);

  // The ghost that stalled is gone…
  const before = (await layers(page)).live;
  await page.keyboard.press("PageUp");
  await expect
    .poll(async () => (await layers(page)).live.page)
    .toBe(before.page - 1);
  await expect.poll(() => settled(page)).toBe(true);
  expect(
    await page.evaluate(() => {
      const { core } = window.__beepubReaderNG;
      return [
        core.ghosts.includes(window.__stuckGhost),
        document.querySelectorAll("foliate-paginator").length -
          core.ghosts.length,
      ];
    }),
  ).toEqual([false, 1]);
  // …which finds its page, and the turns slide again.
  await ghostReady(page, -1);
  await watchTurns(page);
  await page.keyboard.press("PageUp");
  await expect
    .poll(async () => (await layers(page)).live.page)
    .toBe(before.page - 2);
  await expect.poll(() => settled(page)).toBe(true);
  expect(await turns(page)).toEqual(["ghost:slide"]);
});

test("a horizontal plate in a vertical book slides like every other page, laid out its own way", async ({
  page,
  context,
}) => {
  const bookId = await seedFixture(page.request, VERTICAL_MIXED_BOOK);
  await openBook(
    page,
    bookId,
    { turn: "slide", font: "sans" },
    VERTICAL_MIXED_BOOK,
  );
  const cdp = await context.newCDPSession(page);
  const layout = (which: "live" | "ghost") =>
    page.evaluate((which) => {
      const { core, paginator } = window.__beepubReaderNG;
      const el = which === "live" ? paginator : core.ghost;
      const doc: Document = el.getContents()[0].doc;
      return {
        writingMode: getComputedStyle(doc.body).writingMode,
        gap: el.getAttribute("gap"),
        margin: el.getAttribute("margin"),
        inline: el.getAttribute("max-inline-size"),
        block: el.getAttribute("max-block-size"),
      };
    }, which);

  await goTo(page, { index: 0, fraction: 1 });
  await expect
    .poll(async () => {
      const { live } = await layers(page);
      return live.index === 0 && live.page === live.pages - 2;
    })
    .toBe(true);
  await ghostReady(page, 1);
  // The page on screen is vertical; the plate waiting under it is not,
  // and has the gutters of a horizontal page.
  const vertical = await layout("live");
  const plate = await layout("ghost");
  expect(vertical.writingMode).toBe("vertical-rl");
  expect(plate.writingMode).toBe("horizontal-tb");
  expect([plate.gap, plate.margin]).toEqual([vertical.margin, vertical.gap]);

  // Forward is still the finger going right: the book's direction, not
  // the plate's.
  await touchDown(cdp, at(80));
  await touchMove(cdp, at(80), at(200), 10);
  const mid = await layersWhen(page, "live", 120);
  expect(mid.ghost!.index).toBe(1);
  expectLeft(mid.ghost, -PARALLAX * (mid.live.width - 120));
  await touchMove(cdp, at(200), at(340), 6);
  await touchUp(cdp);
  await expect.poll(async () => (await layers(page)).live.index).toBe(1);
  await expect.poll(() => settled(page)).toBe(true);
  // The live plate is laid out exactly as the ghost showed it.
  expect(await layout("live")).toEqual(plate);

  // And on from the plate into the next chapter, by key.
  await ghostReady(page, 1);
  expect(await layout("ghost")).toEqual(vertical);
  await watchTurns(page);
  await page.keyboard.press("PageDown");
  await expect.poll(async () => (await layers(page)).live.index).toBe(2);
  await expect.poll(() => settled(page)).toBe(true);
  expect(await turns(page)).toEqual(["live:slide"]);
  expect(await layout("live")).toEqual(vertical);
});

test("taps and keys play the slide on their own, quick paging lands every turn, reduced motion jumps", async ({
  page,
  context,
}) => {
  const bookId = await seedFixture(page.request, VERTICAL_LONG_BOOK);
  await openBook(
    page,
    bookId,
    { turn: "slide", font: "sans" },
    VERTICAL_LONG_BOOK,
  );
  const cdp = await context.newCDPSession(page);
  await ghostReady(page, 1);
  const first = (await layers(page)).live;
  test.skip(
    first.pages - 2 < 12,
    "vertical fragmentation degenerate — CJK fonts missing",
  );
  const livePage = async () => (await layers(page)).live.page;
  await watchTurns(page);

  // A key: the page on screen slides away.
  await page.keyboard.press("PageDown");
  await expect.poll(livePage).toBe(first.page + 1);
  await expect.poll(() => settled(page)).toBe(true);
  expect(await turns(page)).toEqual(["live:slide"]);
  expect((await location(page)).reason).toBe("page");

  // A tap in the forward zone (the left quarter of a leftward book).
  await touchTap(cdp, { x: 40, y: 400 }, 60);
  await expect.poll(livePage).toBe(first.page + 2);
  await expect.poll(() => settled(page)).toBe(true);
  expect(await turns(page)).toEqual(["live:slide", "live:slide"]);

  // Back by key: the previous page slides in.
  await page.keyboard.press("PageUp");
  await expect.poll(livePage).toBe(first.page + 1);
  await expect.poll(() => settled(page)).toBe(true);
  expect((await turns(page))[2]).toBe("ghost:slide");

  // Five turns asked for well inside one another's slide: each ends the
  // slide before it and follows; all five land.
  await page.evaluate(
    () =>
      new Promise<void>((resolve) => {
        const core = window.__beepubReaderNG.core;
        let left = 5;
        const step = () => {
          core.next();
          if (--left) setTimeout(step, 140);
          else resolve();
        };
        step();
      }),
  );
  await expect.poll(livePage).toBe(first.page + 6);
  await expect.poll(() => settled(page)).toBe(true);

  // A burst in one go: the one in hand and one behind it, no backlog.
  await page.evaluate(() => {
    const core = window.__beepubReaderNG.core;
    core.next();
    core.next();
    core.next();
    core.next();
  });
  await expect.poll(livePage).toBe(first.page + 8);
  await expect.poll(() => settled(page)).toBe(true);
  await page.waitForTimeout(300);
  expect(await livePage()).toBe(first.page + 8);
  expect(await settled(page)).toBe(true);
  // None of that fell back to a fade.
  expect((await turns(page)).filter((t) => t.endsWith("fade"))).toEqual([]);

  // Reduced motion: the same mode jumps, and nothing animates.
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.evaluate(() => (window.__turns = []));
  await page.keyboard.press("PageDown");
  await expect.poll(livePage).toBe(first.page + 9);
  expect(await turns(page)).toEqual([]);
  expect(await settled(page)).toBe(true);
});

/** A horizontal zh-TW novel written with ASCII numbers; forced vertical,
 *  its short numbers are stood upright by wrappers the reader adds to
 *  the rendered section (reader-ng-upright-numbers.spec.ts). */
const DIGITS_BOOK: Fixture = {
  file: "e2e-writing-mode-digits-book.epub",
  title: "鹽田守望人夜錄",
  readyText: "鹽冊甲篇第001段",
};

/**
 * The ghost has to look exactly like the page it stands in for: at the
 * end of a turn it lies over the live page, and is taken away once that
 * shows the same page. Lift it there by hand, photograph it, make the
 * turn for real and photograph the live page: the same pixels.
 */
async function ghostLooksLikeLive(
  page: Page,
  testInfo: TestInfo,
  name: string,
) {
  await ghostReady(page, 1);
  // Both documents have their fonts and have settled on them.
  await page.evaluate(async () => {
    const { core, paginator } = window.__beepubReaderNG;
    for (const el of [paginator, core.ghost])
      await (el.getContents()[0].doc as Document).fonts.ready;
  });
  await page.waitForTimeout(300);
  await ghostReady(page, 1);
  const before = (await layers(page)).live;
  const reader = page.getByTestId("book-reader");
  const lift = (z: string) =>
    page.evaluate((z) => {
      window.__beepubReaderNG.core.ghost.style.zIndex = z;
    }, z);
  await lift("4");
  const ghostShot = await reader.screenshot();
  await lift("0");
  const liveBefore = await reader.screenshot();
  await page.keyboard.press("PageDown");
  await expect
    .poll(async () => {
      const { live } = await layers(page);
      return live.index !== before.index || live.page !== before.page;
    })
    .toBe(true);
  await expect.poll(() => settled(page)).toBe(true);
  const liveShot = await reader.screenshot();
  fs.writeFileSync(testInfo.outputPath(`${name}-ghost.png`), ghostShot);
  fs.writeFileSync(testInfo.outputPath(`${name}-live.png`), liveShot);
  // The two pages differ from each other (the comparison means something)…
  expect(liveBefore.equals(liveShot)).toBe(false);
  // …and the ghost's rendering of the page is the live one's.
  expect(ghostShot.equals(liveShot)).toBe(true);
}

test("the ghost page is pixel for pixel the live page it stands in for — horizontal, after a font-size change and a rotation", async ({
  page,
  context,
}, testInfo) => {
  const bookId = await seedFixture(page.request, ANCHOR_BOOK);
  await openBook(page, bookId, { turn: "slide", size: "20" }, ANCHOR_BOOK);
  await ghostLooksLikeLive(page, testInfo, "horizontal");

  // A setting that lays every page out again.
  await page.evaluate(() => void window.__beepubReaderNG.core.goTo(0));
  await page.waitForTimeout(300);
  const cdp = await context.newCDPSession(page);
  await openSettings(page, cdp);
  await page.getByRole("button", { name: "Increase font size" }).click();
  await page.getByRole("button", { name: "Increase Side margins" }).click();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  // The chrome lies over the page: put it away again.
  const bar = page.getByRole("toolbar", { name: "Reading controls" });
  if (await bar.isVisible()) await touchTap(cdp, { x: 195, y: 420 }, 60);
  await expect(bar).toBeHidden();
  await page.waitForTimeout(400);
  await ghostLooksLikeLive(page, testInfo, "resized-text");

  // The phone turned on its side.
  await page.setViewportSize({ width: 844, height: 390 });
  await page.waitForTimeout(500);
  await ghostLooksLikeLive(page, testInfo, "rotated");
});

test("the ghost page is pixel for pixel the live page — forced vertical with upright numbers, and an illustration plate", async ({
  page,
}, testInfo) => {
  const digits = await seedFixture(page.request, DIGITS_BOOK);
  await page.goto("/");
  await page.evaluate(
    (key) => localStorage.setItem(key, "vertical"),
    `reader-writing-mode:${digits}`,
  );
  await openBook(page, digits, { turn: "slide", font: "sans" }, DIGITS_BOOK);
  expect(
    await page.evaluate(() => {
      const { core } = window.__beepubReaderNG;
      return [core.forcedWritingMode(), core.vertical];
    }),
  ).toEqual(["vertical", true]);
  await ghostReady(page, 1);
  // The ghost's section got the same wrappers as the live one.
  const wrappers = (which: "live" | "ghost") =>
    page.evaluate((which) => {
      const { core, paginator } = window.__beepubReaderNG;
      const el = which === "live" ? paginator : core.ghost;
      const doc: Document = el.getContents()[0].doc;
      return doc.querySelectorAll("beepub-tcy").length;
    }, which);
  expect(await wrappers("live")).toBeGreaterThan(0);
  expect(await wrappers("ghost")).toBe(await wrappers("live"));
  await ghostLooksLikeLive(page, testInfo, "upright-numbers");
  await page.evaluate(
    (key) => localStorage.removeItem(key),
    `reader-writing-mode:${digits}`,
  );

  // The page before a plate: the plate lies under it, sized and centred
  // as the live page will have it.
  const plates = await seedFixture(page.request, VERTICAL_PLATE_BOOK);
  await openBook(
    page,
    plates,
    { turn: "slide", size: "24" },
    VERTICAL_PLATE_BOOK,
  );
  await page.evaluate(async () => {
    const { core, paginator } = window.__beepubReaderNG;
    const { doc } = core.getContents()[0];
    const range = doc.createRange();
    range.selectNode(doc.querySelector("img")!);
    await core.goTo(core.cfiOf(0, range));
    // …and one page back from the plate's.
    const textPages = paginator.pages - 2;
    await new Promise((resolve) => setTimeout(resolve, 300));
    await core.goTo({
      index: 0,
      fraction: (paginator.page - 2) / (textPages - 1),
    });
  });
  await page.waitForTimeout(300);
  await ghostReady(page, 1);
  expect(
    await page.evaluate(() => {
      const { core } = window.__beepubReaderNG;
      const range: Range | null = core.ghostLocation.range;
      const img = core.ghost.getContents()[0].doc.querySelector("img");
      return !!range && range.intersectsNode(img);
    }),
  ).toBe(true);
  await ghostLooksLikeLive(page, testInfo, "plate");
});

test("a writing-mode switch while the ghost is loading a chapter leaves the slide working", async ({
  page,
}) => {
  const bookId = await seedFixture(page.request, CHAPTER_ANCHORS_BOOK);
  await openBook(
    page,
    bookId,
    { turn: "slide", font: "sans" },
    CHAPTER_ANCHORS_BOOK,
  );
  await ghostReady(page, 1);
  // The last page of a chapter sends the ghost off to load the next
  // one; the switch replaces the ghost before that load has reported.
  await page.evaluate(async () => {
    const core = window.__beepubReaderNG.core;
    await core.goTo({ index: 0, fraction: 1 });
    await core.setWritingMode("horizontal");
  });
  await expect
    .poll(() =>
      page.evaluate(() => {
        const { core } = window.__beepubReaderNG;
        const doc: Document | undefined = core.getContents()[0]?.doc;
        return doc?.body ? getComputedStyle(doc.body).writingMode : null;
      }),
    )
    .toBe("horizontal-tb");
  // The new ghost finds its page, written the new way…
  await ghostReady(page, 1);
  expect(
    await page.evaluate(() => {
      const doc: Document =
        window.__beepubReaderNG.core.ghost.getContents()[0].doc;
      return getComputedStyle(doc.body).writingMode;
    }),
  ).toBe("horizontal-tb");
  // …and the next turn slides.
  const before = (await layers(page)).live;
  await watchTurns(page);
  await page.keyboard.press("PageDown");
  await expect
    .poll(async () => {
      const { live } = await layers(page);
      return live.index !== before.index || live.page !== before.page;
    })
    .toBe(true);
  await expect.poll(() => settled(page)).toBe(true);
  expect(await turns(page)).toEqual(["live:slide"]);
});

test("at either end of the book nothing slides, and a swipe past the last page still ends the book", async ({
  page,
  context,
}) => {
  const bookId = await seedFixture(page.request, NOTES_BOOK);
  const resetStatus = async () => {
    const res = await page.request.put(`/api/books/${bookId}/reading-status`, {
      data: { reading_status: null, started_at: null, finished_at: null },
    });
    expect(res.ok()).toBeTruthy();
  };
  expect(
    (
      await page.request.put(`/api/books/${bookId}/metadata`, {
        data: { series: null, series_index: null },
      })
    ).ok(),
  ).toBeTruthy();
  await resetStatus();
  await openBook(page, bookId, { turn: "slide" }, NOTES_BOOK);
  const cdp = await context.newCDPSession(page);
  await ghostReady(page, 1);
  const first = (await layers(page)).live;

  // The first page: pulling the previous page in finds none. Nothing
  // moves, and the reader stays put.
  await touchDown(cdp, at(60));
  await touchMove(cdp, at(60), at(240), 10);
  await page.waitForTimeout(150);
  const pulled = await layers(page);
  expect(pulled.live.left).toBe(0);
  expect(pulled.ghost!.left).toBe(0);
  expect(pulled.ghost!.z).toBeLessThan(pulled.live.z);
  await touchUp(cdp);
  await expect.poll(() => settled(page)).toBe(true);
  expect((await layers(page)).live).toMatchObject({
    index: first.index,
    page: first.page,
  });

  // The last page: nothing to slide to either…
  await page.evaluate(() => {
    const core = window.__beepubReaderNG.core;
    void core.goTo({ index: core.lastLinearIndex(), fraction: 1 });
  });
  await expect
    .poll(() => page.evaluate(() => window.__beepubReaderNG.paginator.atEnd))
    .toBe(true);
  await page.waitForTimeout(300);
  await touchDown(cdp, at(330));
  await touchMove(cdp, at(330), at(150), 10);
  await page.waitForTimeout(150);
  expect((await layers(page)).live.left).toBe(0);
  // …and the swipe is the forward move past the end: the book is over.
  await touchUp(cdp);
  await expect(page.getByTestId("book-end")).toBeVisible();
  expect(await settled(page)).toBe(true);
  await resetStatus();
});

interface Row {
  id: string;
  cfi_range: string;
  text: string;
}

async function clearHighlights(request: APIRequestContext, bookId: string) {
  const rows: Row[] = await (
    await request.get(`/api/books/${bookId}/highlights`)
  ).json();
  for (const h of rows) {
    const res = await request.delete(`/api/books/${bookId}/highlights/${h.id}`);
    expect(res.ok()).toBeTruthy();
  }
}

/** A long word in the middle of the page on screen, and where it is. */
function wordOnPage(page: Page) {
  return page.evaluate(() => {
    const core = window.__beepubReaderNG.core;
    const doc: Document = core.getContents()[0].doc;
    const visible: Range = core.lastLocation.range;
    const frame = (
      doc.defaultView!.frameElement as HTMLIFrameElement
    ).getBoundingClientRect();
    const found: { word: string; x: number; y: number }[] = [];
    const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const node = walker.currentNode;
      if (!visible.intersectsNode(node)) continue;
      for (const m of (node.textContent ?? "").matchAll(/[A-Za-z]{7,}/g)) {
        const range = doc.createRange();
        range.setStart(node, m.index!);
        range.setEnd(node, m.index! + m[0].length);
        if (
          visible.compareBoundaryPoints(Range.START_TO_START, range) > 0 ||
          visible.compareBoundaryPoints(Range.END_TO_END, range) < 0
        )
          continue;
        const rects = range.getClientRects();
        if (rects.length !== 1) continue; // not broken across lines
        const r = rects[0]!;
        found.push({
          word: m[0],
          x: frame.left + r.left + r.width / 2,
          y: frame.top + r.top + r.height / 2,
        });
      }
    }
    return found[Math.floor(found.length / 2)] ?? null;
  });
}

/** Marks of a rendering that are on screen, as viewport x positions (a
 *  section's overlayer spans all of its pages). */
function marksOn(page: Page, which: "live" | "ghost") {
  return page.evaluate((which) => {
    const { core, paginator } = window.__beepubReaderNG;
    const el = which === "live" ? paginator : core.ghost;
    const contents = el?.getContents()[0];
    const svg: SVGSVGElement | undefined = contents?.overlayer?.element;
    if (!svg) return [];
    const host = (el as HTMLElement).getBoundingClientRect();
    return Array.from(svg.querySelectorAll("rect"))
      .map((r) => {
        const box = r.getBoundingClientRect();
        return Math.round(box.left + box.width / 2 - host.left);
      })
      .filter((x) => x >= 0 && x < host.width);
  }, which);
}

test("after a slide the live page is the only one that answers; a highlight rides along on the still page; saves carry the live position", async ({
  page,
  context,
}) => {
  const bookId = await seedFixture(page.request, ANCHOR_BOOK);
  await clearHighlights(page.request, bookId);
  await openBook(page, bookId, { turn: "slide", size: "24" }, ANCHOR_BOOK);
  const cdp = await context.newCDPSession(page);
  await ghostReady(page, 1);
  const first = (await layers(page)).live;

  // Slide to the second page; the save that follows names the live page.
  const saved = page.waitForResponse(
    (r) => r.request().method() === "PUT" && r.url().endsWith("/progress"),
    { timeout: 10_000 },
  );
  await page.keyboard.press("PageDown");
  await expect
    .poll(async () => (await layers(page)).live.page)
    .toBe(first.page + 1);
  await expect.poll(() => settled(page)).toBe(true);
  const here = await page.evaluate(() => {
    const l = window.__beepubReaderNG.core.lastLocation;
    return { cfi: l.startCfi as string, reason: l.reason as string };
  });
  expect(here.reason).toBe("page");
  expect((await saved).ok()).toBeTruthy();
  const progress = async () =>
    (await page.request.get(`/api/books/${bookId}/progress`)).json();
  await expect.poll(async () => (await progress()).cfi).toBe(here.cfi);
  expect((await progress()).section_page).toBe(first.page + 1);

  // One section answers: the core reports the live one only, and the
  // ghost takes no input.
  expect(
    await page.evaluate(() => {
      const { core, paginator } = window.__beepubReaderNG;
      const ghost = core.ghost as HTMLElement;
      return {
        contents: core.getContents().length,
        same: core.getContents()[0].doc === paginator.getContents()[0].doc,
        apart: ghost !== paginator,
        inert: ghost.inert,
        pointer: getComputedStyle(ghost).pointerEvents,
        hidden: ghost.getAttribute("aria-hidden"),
      };
    }),
  ).toEqual({
    contents: 1,
    same: true,
    apart: true,
    inert: true,
    pointer: "none",
    hidden: "true",
  });

  // Selection still works on the page just slid to: long-press a word,
  // the menu opens — and survives the ghost stepping to another page.
  const target = await wordOnPage(page);
  expect(target).toBeTruthy();
  await touchTap(cdp, target!, 900);
  const menu = page.getByTestId("highlight-menu");
  await expect(menu).toBeVisible();
  await page.evaluate(() => {
    const { core } = window.__beepubReaderNG;
    return core.ghost.goTo({
      index: core.ghost.getContents()[0].index,
      anchor: 0,
    });
  });
  await page.waitForTimeout(200);
  await expect(menu).toBeVisible();
  const created = page.waitForResponse(
    (r) => r.request().method() === "POST" && r.url().endsWith("/highlights"),
  );
  await menu.getByTitle("Highlight", { exact: true }).click();
  const highlight: Row = await (await created).json();
  expect(highlight.text).toBe(target!.word);
  await expect.poll(() => marksOn(page, "live")).toHaveLength(1);

  // Back to the first page: the highlighted page is now the one lying
  // under it, mark and all.
  await page.keyboard.press("PageUp");
  await expect
    .poll(async () => (await layers(page)).live.page)
    .toBe(first.page);
  await expect.poll(() => settled(page)).toBe(true);
  await ghostReady(page, 1);
  await expect.poll(() => marksOn(page, "ghost")).toHaveLength(1);
  expect(await marksOn(page, "live")).toHaveLength(0);
  const [ghostMark] = await marksOn(page, "ghost");
  expect(Math.abs(ghostMark! - target!.x)).toBeLessThanOrEqual(2);

  // Mid-slide the mark is there on the still page, where the word is.
  await touchDown(cdp, at(320));
  await touchMove(cdp, at(320), at(170), 10);
  const mid = await layersWhen(page, "live", -150);
  expect(await marksOn(page, "ghost")).toEqual([ghostMark]);
  await touchMove(cdp, at(170), at(50), 6);
  await touchUp(cdp);
  await expect
    .poll(async () => (await layers(page)).live.page)
    .toBe(first.page + 1);
  await expect.poll(() => settled(page)).toBe(true);
  // …and on the live page once it has landed, in the same place.
  expect(await marksOn(page, "live")).toEqual([ghostMark]);

  await clearHighlights(page.request, bookId);
});

test("the ghost page blocks the book's scripts the way the live page does", async ({
  page,
}) => {
  const bookId = await seedBook(page.request);
  await openBook(page, bookId, { turn: "slide" });
  await ghostReady(page);
  const policy = (doc: "live" | "ghost") =>
    page.evaluate((which) => {
      const { core, paginator } = window.__beepubReaderNG;
      const view = which === "live" ? paginator : core.ghost;
      const d: Document = view.getContents()[0].doc;
      return (
        d
          .querySelector('meta[http-equiv="Content-Security-Policy"]')
          ?.getAttribute("content") ?? null
      );
    }, doc);
  // The emulated iPhone counts as iOS: the live page carries the policy.
  expect(await policy("live")).toBe("script-src 'none'");
  expect(await policy("ghost")).toBe("script-src 'none'");
});

/** What the slide's own record says became of the turns since `from`:
 *  how many slid, sprang back or faded, and the sections loaded into
 *  ghosts meanwhile. */
function slideLog(page: Page, from = 0) {
  return page.evaluate((from) => {
    const log: any[] = window.__beepubReaderNG.core.slideLog.slice(from);
    const count = (how: string) => log.filter((e) => e.how === how).length;
    return {
      length: window.__beepubReaderNG.core.slideLog.length as number,
      slid: count("slide"),
      sprung: count("spring"),
      faded: log.filter((e) => e.how === "fade").map((e) => e.why as string),
      loads: log.filter((e) => "load" in e).map((e) => e.ms as number),
    };
  }, from);
}

/** The live paginator's own turns into another section since the page
 *  was armed (each one lays a whole chapter out). */
function watchLiveLoads(page: Page) {
  return page.evaluate(() => {
    const { paginator } = window.__beepubReaderNG;
    window.__liveLoads = 0;
    paginator.addEventListener("load", () => window.__liveLoads!++);
  });
}

// The owner's report, from a phone: on a chapter's first page and the
// chapter before's last, leafing back and forth quickly, some turns
// faded and some swipes did nothing. A phone is approximated by slowing
// the CPU sixfold, with chapters long enough that laying one out takes
// longer than a turn may wait (some 350ms; the live paginator's own turn
// across the boundary some 400ms). Eight turns, 300ms apart, each the
// reverse of the last.
for (const kind of ["keys", "taps", "swipes"] as const) {
  test(`back and forth over a chapter boundary on a slow phone, by ${kind}: every turn slides, none is lost, nothing is loaded`, async ({
    page,
    context,
  }) => {
    const bookId = await seedFixture(page.request, LONG_CHAPTERS_BOOK);
    await openBook(page, bookId, { turn: "slide" }, LONG_CHAPTERS_BOOK);
    const cdp = await context.newCDPSession(page);
    await goTo(page, { index: 0, fraction: 1 });
    await expect
      .poll(async () => {
        const { live } = await layers(page);
        return live.index === 0 && live.page === live.pages - 2;
      })
      .toBe(true);
    const start = (await layers(page)).live;
    expect(start.pages - 2).toBeGreaterThan(40);
    // The reader has been on the page a moment: both neighbours are
    // rendered, each in a ghost of its own.
    await ghostReady(page, 1);
    await ghostReady(page, -1);
    expect(
      await page.evaluate(() => {
        const { core } = window.__beepubReaderNG;
        return [
          core.ghosts.length,
          core.ghostFor(1).getContents()[0].index,
          core.ghostFor(-1).getContents()[0].index,
        ];
      }),
    ).toEqual([2, 1, 0]);
    await watchTurns(page);
    await watchLiveLoads(page);
    const from = (await slideLog(page)).length;

    await cdp.send("Emulation.setCPUThrottlingRate", { rate: 6 });
    try {
      const TURNS = 8;
      const t0 = Date.now();
      for (let i = 0; i < TURNS; i++) {
        const wait = t0 + i * 300 - Date.now();
        if (wait > 0) await new Promise((resolve) => setTimeout(resolve, wait));
        const forward = i % 2 === 0;
        if (kind === "keys") {
          await page.keyboard.press(forward ? "PageDown" : "PageUp");
        } else if (kind === "taps") {
          // The right quarter of a left-to-right book is "next".
          await touchTap(cdp, { x: forward ? 350 : 40, y: 400 }, 40);
        } else {
          // A flick, a medium swipe and a long one by turns; most begin
          // while the slide before is still finishing. Forward is the
          // finger going left.
          const [distance, steps] = (
            [
              [90, 4],
              [150, 8],
              [220, 10],
            ] as const
          )[i % 3]!;
          const x = forward ? 330 : 50;
          const to = x + (forward ? -distance : distance);
          await touchDown(cdp, at(x));
          await touchMove(cdp, at(x), at(to), steps);
          await touchUp(cdp);
        }
      }
      // Back where it began, and at rest.
      await expect
        .poll(
          async () => {
            const { live } = await layers(page);
            return (
              live.index === start.index &&
              live.page === start.page &&
              (await settled(page))
            );
          },
          { timeout: 20_000 },
        )
        .toBe(true);
    } finally {
      await cdp.send("Emulation.setCPUThrottlingRate", { rate: 1 });
    }
    expect((await layers(page)).live.text).toBe(start.text);
    const log = await slideLog(page, from);
    // Every turn slid: none faded, none sprang back, none went missing…
    expect(log).toMatchObject({ slid: 8, sprung: 0, faded: [] });
    expect((await turns(page)).filter((t) => t.endsWith("fade"))).toEqual([]);
    // …and nothing was loaded for any of them: no section into a ghost,
    // and the live paginator never left its chapter (the turns that undo
    // each other were played on the ghosts alone).
    expect(log.loads).toEqual([]);
    expect(await page.evaluate(() => window.__liveLoads)).toBe(0);
  });
}

test("the reader stays on a page reached over a chapter boundary: the live page catches up under the cover, and answers again", async ({
  page,
  context,
}) => {
  const bookId = await seedFixture(page.request, LONG_CHAPTERS_BOOK);
  await openBook(page, bookId, { turn: "slide" }, LONG_CHAPTERS_BOOK);
  const cdp = await context.newCDPSession(page);
  await goTo(page, { index: 0, fraction: 1 });
  await expect
    .poll(async () => {
      const { live } = await layers(page);
      return live.index === 0 && live.page === live.pages - 2;
    })
    .toBe(true);
  await ghostReady(page, 1);
  await ghostReady(page, -1);
  const ahead = await page.evaluate(() => {
    const { core } = window.__beepubReaderNG;
    return core.ghostFor(1) === core.ghost
      ? (core.ghostLocation.range.toString() as string)
      : "";
  });
  expect(ahead.length).toBeGreaterThan(40);
  await watchLiveLoads(page);

  // The turn is made on the sheets at once; the live paginator follows
  // a moment later, and then the page is the live one's: its position is
  // the one reported, a tap in the middle reaches it.
  await page.keyboard.press("PageDown");
  await expect
    .poll(async () => {
      const { live } = await layers(page);
      return [live.index, live.page];
    })
    .toEqual([1, 1]);
  await expect.poll(() => settled(page)).toBe(true);
  expect(await page.evaluate(() => window.__liveLoads)).toBe(1);
  expect((await layers(page)).live.text).toBe(ahead);
  await touchTap(cdp, { x: 195, y: 420 }, 60);
  await expect(
    page.getByRole("toolbar", { name: "Reading controls" }),
  ).toBeVisible();
  await touchTap(cdp, { x: 195, y: 420 }, 60);

  // On into the chapter by key, twice in quick succession from its first
  // page — the second turn's page is the cover's own to show, so the
  // live page is brought up at once rather than after the pause.
  await goTo(page, { index: 0, fraction: 1 });
  await expect
    .poll(async () => {
      const { live } = await layers(page);
      return live.index === 0 && live.page === live.pages - 2;
    })
    .toBe(true);
  await ghostReady(page, 1);
  await watchTurns(page);
  await page.evaluate(() => {
    const { core } = window.__beepubReaderNG;
    void core.next();
    setTimeout(() => void core.next(), 120);
  });
  await expect
    .poll(async () => {
      const { live } = await layers(page);
      return [live.index, live.page];
    })
    .toEqual([1, 2]);
  await expect.poll(() => settled(page)).toBe(true);
  expect(await turns(page)).toEqual(["live:slide", "live:slide"]);
});

test("one ghost in the middle of a chapter, a second near its edge, given back again further in; a swipe that starts in the gutter turns the page", async ({
  page,
  context,
}) => {
  const bookId = await seedFixture(page.request, LONG_CHAPTERS_BOOK);
  await openBook(page, bookId, { turn: "slide" }, LONG_CHAPTERS_BOOK);
  const cdp = await context.newCDPSession(page);
  /** The sections the ghosts hold, and the paginators in the page. */
  const renderings = () =>
    page.evaluate(() => {
      const { core } = window.__beepubReaderNG;
      return {
        ghosts: (core.ghosts as any[])
          .map((g) => g.getContents()[0]?.index ?? null)
          .sort(),
        elements: document.querySelectorAll("foliate-paginator").length,
      };
    });
  const toPage = async (index: number, page_: number) => {
    await page.evaluate(
      ({ index, page_ }) => {
        const { core, paginator } = window.__beepubReaderNG;
        const pages =
          paginator.getContents()[0].index === index ? paginator.pages - 2 : 0;
        // From the end when negative.
        const n = page_ > 0 ? page_ : pages + 1 + page_;
        void core.goTo({ index, fraction: (n - 1) / (pages - 1) });
      },
      { index, page_ },
    );
    await expect
      .poll(async () => {
        const { live } = await layers(page);
        return (
          live.index === index &&
          live.page === (page_ > 0 ? page_ : live.pages - 1 + page_)
        );
      })
      .toBe(true);
  };

  // The first page of the book: nothing lies before it, and the one
  // ghost is on page two.
  await ghostReady(page, 1);
  expect(await renderings()).toEqual({ ghosts: [0], elements: 2 });

  // The middle of the second chapter: still one.
  await goTo(page, { index: 1, fraction: 0 });
  await expect.poll(async () => (await layers(page)).live.index).toBe(1);
  await toPage(1, 30);
  await expect.poll(renderings).toEqual({ ghosts: [1], elements: 2 });

  // Three pages from its end the third chapter is brought up, in the
  // background: by the time the reader gets there it is rendered.
  await toPage(1, -5);
  await expect.poll(renderings).toEqual({ ghosts: [1], elements: 2 });
  const from = (await slideLog(page)).length;
  await page.keyboard.press("PageDown");
  await expect.poll(() => settled(page)).toBe(true);
  await expect.poll(renderings).toEqual({ ghosts: [1, 2], elements: 3 });
  await ghostReady(page, 1);
  expect((await slideLog(page, from)).loads).toHaveLength(1);

  // Paging back a little keeps it (pacing about must not build and drop
  // a chapter each time); well inside the chapter it is given up.
  await toPage(1, -7);
  await expect.poll(() => settled(page)).toBe(true);
  expect(await renderings()).toEqual({ ghosts: [1, 2], elements: 3 });
  await toPage(1, -12);
  await expect.poll(renderings).toEqual({ ghosts: [1], elements: 2 });

  // Near the chapter's start the same, for the chapter before.
  await toPage(1, 3);
  await expect.poll(renderings).toEqual({ ghosts: [0, 1], elements: 3 });
  await ghostReady(page, 1);

  // A swipe that begins in the gutter below the text (outside the
  // section's own document) is a swipe like any other.
  const before = (await layers(page)).live;
  await watchTurns(page);
  const gutter = await page.evaluate(() => {
    const y = window.innerHeight - 12;
    const el = document.elementFromPoint(320, y);
    return { y, inReader: !!el?.closest('[data-testid="book-reader"]') };
  });
  expect(gutter.inReader).toBe(true);
  await touchDown(cdp, { x: 320, y: gutter.y });
  await touchMove(cdp, { x: 320, y: gutter.y }, { x: 200, y: gutter.y }, 5);
  await touchUp(cdp);
  await expect
    .poll(async () => (await layers(page)).live.page)
    .toBe(before.page + 1);
  await expect.poll(() => settled(page)).toBe(true);
  expect(await turns(page)).toEqual(["live:slide"]);
});

/** Where the reader says it is, where the live paginator is, and
 *  whether a ghost still lies over it. */
function whereabouts(page: Page) {
  return page.evaluate(() => {
    const { core, paginator } = window.__beepubReaderNG;
    const l = core.lastLocation;
    return {
      covered: !!core.cover,
      index: l.index as number,
      startCfi: l.startCfi as string,
      liveIndex: paginator.getContents()[0]?.index as number,
      chapter:
        document
          .querySelector('[data-testid="reader-chapter"]')
          ?.textContent?.trim() ?? "",
    };
  });
}

async function savedProgress(page: Page, bookId: string) {
  return (await page.request.get(`/api/books/${bookId}/progress`)).json();
}

test("the chapter named and the position saved follow the page shown, not the live paginator still behind it", async ({
  page,
  context,
}) => {
  const bookId = await seedFixture(page.request, LONG_CHAPTERS_BOOK);
  const cdp = await context.newCDPSession(page);
  /** Open on the last page of the first chapter, both neighbours
   *  rendered; returns that page's position. */
  const toBoundary = async () => {
    await openBook(page, bookId, { turn: "slide" }, LONG_CHAPTERS_BOOK);
    await goTo(page, { index: 0, fraction: 1 });
    await expect
      .poll(async () => {
        const { live } = await layers(page);
        return live.index === 0 && live.page === live.pages - 2;
      })
      .toBe(true);
    await ghostReady(page, 1);
    await ghostReady(page, -1);
    await page.waitForTimeout(200);
    return whereabouts(page);
  };
  /** The slide into the second chapter has landed — and (`ahead`) the
   *  live paginator has not followed yet. */
  const landed = async (ahead: boolean) => {
    // Looked at in the frame the reader first says so.
    const here = await page.evaluate(
      () =>
        new Promise<{
          covered: boolean;
          startCfi: string;
          liveIndex: number;
          chapter: string;
        } | null>((resolve) => {
          const { core, paginator } = window.__beepubReaderNG;
          const started = performance.now();
          const tick = () => {
            const l = core.lastLocation;
            if (l.index === 1)
              resolve({
                covered: !!core.cover,
                startCfi: l.startCfi,
                liveIndex: paginator.getContents()[0]?.index,
                chapter:
                  document
                    .querySelector('[data-testid="reader-chapter"]')
                    ?.textContent?.trim() ?? "",
              });
            else if (performance.now() - started > 10_000) resolve(null);
            else requestAnimationFrame(tick);
          };
          tick();
        }),
    );
    expect(here).not.toBeNull();
    expect(here!.chapter).toBe("Midwater");
    if (ahead) expect(here).toMatchObject({ covered: true, liveIndex: 0 });
    return here!;
  };

  // Leave by loading another page a moment after the slide lands (the
  // unload save): the row names the new chapter, and the book reopens on
  // the page that was on screen.
  const end = await toBoundary();
  expect(end.chapter).toBe("Northgate");
  await page.keyboard.press("PageDown");
  let here = await landed(true);
  await page.goto("/");
  await expect
    .poll(async () => (await savedProgress(page, bookId)).section_index)
    .toBe(1);
  expect((await savedProgress(page, bookId)).cfi).toBe(here.startCfi);
  await openBook(
    page,
    bookId,
    { turn: "slide", restore: "1" },
    { ...LONG_CHAPTERS_BOOK, readyText: "Signal log midwater entry 0001" },
  );
  await expect
    .poll(async () => {
      const { live } = await layers(page);
      return [live.index, live.page];
    })
    .toEqual([1, 1]);
  // The live paginator's own report of that page is the same position.
  expect((await whereabouts(page)).startCfi).toBe(here.startCfi);

  // Leave through the reader's own back link (the component's last
  // save), on a slow phone.
  await toBoundary();
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: 6 });
  try {
    await page.keyboard.press("PageDown");
    here = await landed(true);
    await page.getByRole("button", { name: "Back to book detail" }).click();
    await page.waitForURL((url) => !url.pathname.endsWith("/read"));
  } finally {
    await cdp.send("Emulation.setCPUThrottlingRate", { rate: 1 });
  }
  await expect
    .poll(async () => (await savedProgress(page, bookId)).cfi)
    .toBe(here.startCfi);
  expect((await savedProgress(page, bookId)).section_index).toBe(1);

  // Forward, back, forward in quick succession, then away: the page
  // shown last is the one saved…
  await toBoundary();
  const from = (await slideLog(page)).length;
  for (const key of ["PageDown", "PageUp", "PageDown"]) {
    await page.keyboard.press(key);
    await page.waitForTimeout(150);
  }
  await expect.poll(async () => (await slideLog(page, from)).slid).toBe(3);
  here = await landed(false);
  await page.goto("/");
  await expect
    .poll(async () => (await savedProgress(page, bookId)).cfi)
    .toBe(here.startCfi);

  // …and a pair of turns that undo each other leaves it on the page it
  // began on, named as it was.
  const begun = await toBoundary();
  const pair = (await slideLog(page)).length;
  await page.keyboard.press("PageDown");
  await page.waitForTimeout(150);
  await page.keyboard.press("PageUp");
  await expect.poll(async () => (await slideLog(page, pair)).slid).toBe(2);
  await expect.poll(async () => (await whereabouts(page)).index).toBe(0);
  expect(await whereabouts(page)).toMatchObject({
    startCfi: begun.startCfi,
    chapter: "Northgate",
    liveIndex: 0,
  });
  await page.goto("/");
  await expect
    .poll(async () => (await savedProgress(page, bookId)).cfi)
    .toBe(begun.startCfi);
  expect((await savedProgress(page, bookId)).section_index).toBe(0);
});

/** Make one turn and return what the reader said of the new page while
 *  a ghost was showing it, and what it says once the live paginator has
 *  taken over. */
function turnAndCompare(page: Page, dir: 1 | -1) {
  return page.evaluate(
    (dir) =>
      new Promise<{
        shown: { index: number; startCfi: string; cfi: string } | null;
        live: { index: number; startCfi: string; cfi: string };
      }>((resolve) => {
        const { core } = window.__beepubReaderNG;
        const read = () => {
          const l = core.lastLocation;
          return { index: l.index, startCfi: l.startCfi, cfi: l.cfi };
        };
        let shown: ReturnType<typeof read> | null = null;
        const before = core.lastLocation;
        const started = performance.now();
        void (dir > 0 ? core.next() : core.prev());
        const tick = () => {
          if (core.cover && core.lastLocation !== before) shown ??= read();
          const done =
            (shown && !core.cover) || performance.now() - started > 5000;
          if (done) resolve({ shown, live: read() });
          else requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);
      }),
    dir,
  );
}

test("a ghost reports the very position the live page does — vertical text, upright numbers, an illustration plate, across a chapter", async ({
  page,
}) => {
  const compare = async (turnsToMake: (1 | -1)[]) => {
    for (const dir of turnsToMake) {
      const { shown, live } = await turnAndCompare(page, dir);
      expect(shown).not.toBeNull();
      expect(live).toEqual(shown);
      await expect.poll(() => settled(page)).toBe(true);
    }
  };

  // Forced vertical: both documents carry the wrappers that stand short
  // numbers upright, and both are read through them.
  const digits = await seedFixture(page.request, DIGITS_BOOK);
  await page.goto("/");
  await page.evaluate(
    (key) => localStorage.setItem(key, "vertical"),
    `reader-writing-mode:${digits}`,
  );
  await openBook(page, digits, { turn: "slide", font: "sans" }, DIGITS_BOOK);
  expect(
    await page.evaluate(
      () =>
        window.__beepubReaderNG.core
          .getContents()[0]
          .doc.querySelectorAll("beepub-tcy").length,
    ),
  ).toBeGreaterThan(0);
  await ghostReady(page, 1);
  await compare([1, 1, -1, 1]);
  await page.evaluate(
    (key) => localStorage.removeItem(key),
    `reader-writing-mode:${digits}`,
  );

  // A chapter with a marked plate: onto the plate's page and past it.
  const plates = await seedFixture(page.request, VERTICAL_PLATE_BOOK);
  await openBook(
    page,
    plates,
    { turn: "slide", size: "24" },
    VERTICAL_PLATE_BOOK,
  );
  await ghostReady(page, 1);
  const pages = (await layers(page)).live.pages - 2;
  await compare(Array(Math.min(pages - 1, 8)).fill(1));
  await compare([-1, -1]);

  // Across a chapter boundary and back (the live paginator loads the
  // chapter the ghost already showed).
  const chapters = await seedFixture(page.request, CHAPTER_ANCHORS_BOOK);
  await openBook(
    page,
    chapters,
    { turn: "slide", font: "sans" },
    CHAPTER_ANCHORS_BOOK,
  );
  await goTo(page, { index: 0, fraction: 1 });
  await expect.poll(async () => (await layers(page)).live.index).toBe(0);
  await ghostReady(page, 1);
  await compare([1]);
  expect((await layers(page)).live.index).toBe(1);
  await ghostReady(page, -1);
  await compare([-1]);
  expect((await layers(page)).live.index).toBe(0);
});

test("just after a slide, a tap on a link of the page shown turns nothing", async ({
  page,
  context,
}) => {
  const bookId = await seedFixture(page.request, LONG_CHAPTERS_BOOK);
  await openBook(page, bookId, { turn: "slide" }, LONG_CHAPTERS_BOOK);
  const cdp = await context.newCDPSession(page);
  await goTo(page, { index: 0, fraction: 1 });
  await expect
    .poll(async () => {
      const { live } = await layers(page);
      return live.index === 0 && live.page === live.pages - 2;
    })
    .toBe(true);
  await ghostReady(page, 1);
  // The next chapter's heading, in the ghost that will show it, made a
  // link: it lies in the tap zone that turns back.
  const at = await page.evaluate(() => {
    const { core } = window.__beepubReaderNG;
    const ghost = core.ghostFor(1);
    const doc: Document = ghost.getContents()[0].doc;
    const h1 = doc.querySelector("h1")!;
    h1.innerHTML = `<a href="#nowhere">${h1.textContent}</a>`;
    const frame = (
      doc.defaultView!.frameElement as HTMLIFrameElement
    ).getBoundingClientRect();
    const r = h1.querySelector("a")!.getBoundingClientRect();
    return { x: frame.left + r.left + 12, y: frame.top + r.top + r.height / 2 };
  });
  expect(at.x).toBeLessThan(90);
  const from = (await slideLog(page)).length;
  await page.keyboard.press("PageDown");
  // (Looked for closely: the cover is up for a moment only.)
  await expect
    .poll(async () => (await whereabouts(page)).index, { intervals: [40] })
    .toBe(1);
  expect((await whereabouts(page)).covered).toBe(true);
  await touchTap(cdp, at, 40);
  // Nothing turned; the live page was brought up for the next tap.
  await expect.poll(() => settled(page)).toBe(true);
  expect((await layers(page)).live).toMatchObject({ index: 1, page: 1 });
  expect(await slideLog(page, from)).toMatchObject({ slid: 1, sprung: 0 });
  await page.waitForTimeout(400);
  expect((await layers(page)).live).toMatchObject({ index: 1, page: 1 });
});

test("the fade mode builds no second rendering, and switching modes builds and removes it", async ({
  page,
  context,
}) => {
  const bookId = await seedFixture(page.request, ANCHOR_BOOK);
  await openBook(page, bookId, { turn: "" }, ANCHOR_BOOK);
  const renderings = () =>
    page.evaluate(() => ({
      ghost: !!window.__beepubReaderNG.core.ghost,
      // The paginators are light-DOM children of the reader's container:
      // the live one, and the ghosts.
      elements:
        document.querySelectorAll("foliate-paginator").length -
        window.__beepubReaderNG.core.ghosts.length,
      lock: window.__beepubReaderNG.paginator.hasAttribute("no-turn-lock"),
    }));
  expect(await page.evaluate(() => window.__beepubReaderNG.core.pageTurn)).toBe(
    "fade",
  );
  expect(await renderings()).toEqual({
    ghost: false,
    elements: 1,
    lock: false,
  });
  const paginators = () =>
    page.evaluate(() => document.querySelectorAll("foliate-paginator").length);
  expect(await paginators()).toBe(1);

  const cdp = await context.newCDPSession(page);
  await openSettings(page, cdp);
  const row = page.getByTestId("setting-page-turn");
  await row.getByRole("button", { name: "Slide" }).click();
  await expect
    .poll(renderings)
    .toEqual({ ghost: true, elements: 1, lock: true });
  await ghostReady(page, 1);
  expect(await paginators()).toBeGreaterThan(1);

  await row.getByRole("button", { name: "Fast fade" }).click();
  await expect
    .poll(renderings)
    .toEqual({ ghost: false, elements: 1, lock: false });
  expect(await paginators()).toBe(1);
  expect(await settled(page)).toBe(true);
});
