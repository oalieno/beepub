// The bee in the bookshelf.
//
// It came in ahead of you (ShelfIntro) and lives here, a thing in the
// room like the books: it stands on a book's head, rides along as the
// shelf is slid, takes wing when its book leaves the window or is taken
// down. Now and then it flies to another book of its own accord; and
// it is shy of the pointer — reach for the book it is on and it is off
// to another. Asked (a click on the bee itself), it turns about and
// goes to pick a book out for you.
import * as THREE from "three";
import { makeBee } from "./bee3d";

/** What the bee knows of the shelf it lives on. */
export interface BeeWorld {
  /** What it is drawn in: it is lit as the books are. */
  room: THREE.Object3D;
  /** The shelf's scrolling host; where the bee is, on the screen, is
   *  written on it (`data-bee`) for a test to find it by. */
  host: HTMLElement;
  reduced: boolean;
  /** A duration, or none under reduced motion. */
  T(ms: number): number;
  /** The top of what is seen, and of the tallest book (world units). */
  top: number;
  tallest: number;
  /** Where the eye stands along the shelf, and how much it sees. */
  camX(): number;
  worldW(): number;
  scale(): number;
  cssW(): number;
  scrolled(): number;
  /** How many books there are; a standing one's place and height. */
  count(): number;
  book(i: number): { x: number; h: number } | null;
  standing(): Iterable<{ i: number; x: number }>;
  /** The book under the pointer, and the one in hand (-1: none). */
  hover(): number;
  held(): number;
  /** A point on the screen, in the room; a ray from the eye through it. */
  inRoom(sx: number, sy: number): { x: number; y: number };
  rayAt(e: MouseEvent): THREE.Raycaster | null;
  /** Slide the shelf to a book and take it down. */
  seek(i: number): Promise<void>;
  /** Something moved: draw again. */
  redraw(): void;
}

export function createBeeFlight(w: BeeWorld) {
  const BEE = 15; // its body's width, world units
  const FEET = 0.805 * BEE; // its middle above what it stands on
  const bee = makeBee();
  bee.group.visible = false;
  bee.group.scale.setScalar(BEE);
  w.room.add(bee.group);
  const at3 = new THREE.Vector3();
  let beeIn = false;
  let beeBig = 1; // its size, beside its own
  let beeBigTo = 1;
  let perch = -1; // the book it stands on, or is going to
  let landedOn = -1;
  let sent = -1; // the book it was sent to fetch
  let away: { x: number; y: number } | null = null; // on its way out
  let arrived: (() => void) | null = null;
  let restless = 0; // when it next flies off of its own accord
  let startled = 0; // until when it looks it
  let yaw = 0; // which way it is turned, from how the logo stands
  let yawTo = 0;
  let standYaw = -1.15 + Math.random() * 1.6; // how it will next stand
  let nearing = false; // coming in to land
  let wasLanded = false;
  let turnAt = 0; // when it next turns about where it stands
  let roll = 0; // what is left of a roll in flight
  let tumble = 0; // and of a somersault
  let blink = 0; // when it next blinks
  let beeScroll = 0;
  let stirred = 0; // when the shelf last moved
  let wingsOpen = 1;
  let spin = 0; // what is left of a turn about
  let beeTime = 0;
  let beeLast = 0;
  let beeCam = 0; // where the eye stood, the frame before

  const headOf = (i: number) => {
    const p = w.book(i);
    if (!p || w.held() === i) return null;
    return { x: p.x, y: p.h + FEET, z: -22 };
  };
  const inWindow = (x: number) => Math.abs(x - w.camX()) < w.worldW() / 2 - 24;
  // The standing book nearest to x along the shelf.
  function nearest(x: number) {
    let best = -1;
    let gap = Infinity;
    for (const p of w.standing()) {
      if (w.held() === p.i || !inWindow(p.x)) continue;
      const d = Math.abs(p.x - x);
      if (d < gap) {
        gap = d;
        best = p.i;
      }
    }
    return best;
  }
  // Some other standing book in the window, not too near the one left.
  function another(not: number, nor: number) {
    const from = w.book(not)?.x ?? w.camX();
    const all: number[] = [];
    const farther: number[] = [];
    for (const p of w.standing()) {
      if (p.i === not || p.i === nor || !inWindow(p.x)) continue;
      if (w.held() === p.i) continue;
      all.push(p.i);
      if (Math.abs(p.x - from) > 110) farther.push(p.i);
    }
    const of = farther.length ? farther : all;
    return of.length ? of[Math.floor(Math.random() * of.length)] : -1;
  }
  /** In, from where the ring opened (a point on the screen). */
  function enter(sx: number, sy: number) {
    if (beeIn) return;
    const from = w.inRoom(sx, sy);
    at3.set(from.x, from.y, 30);
    beeBig = w.reduced ? 1 : 0.12;
    beeBigTo = 1;
    away = null;
    perch = landedOn = sent = -1;
    beeIn = true;
    bee.group.visible = true;
    beeLast = performance.now();
    beeCam = w.camX();
    restless = beeLast + 6000 + Math.random() * 6000;
    w.redraw();
  }
  /** Out: up and away over the top of the window. (It is next seen at
   *  the door, coming up from below, as the logo — the two are never in
   *  view together.) */
  function leave() {
    if (!beeIn) return Promise.resolve();
    away = { x: at3.x + (at3.x < w.camX() ? -40 : 40), y: w.top + 3 * BEE };
    landedOn = -1;
    return new Promise<void>((done) => {
      arrived = done;
      setTimeout(done, w.T(520));
    });
  }
  /** Gone at once (it was switched off). */
  function hide() {
    beeIn = false;
    away = null;
    perch = landedOn = sent = -1;
    bee.group.visible = false;
    delete w.host.dataset.bee;
    w.redraw();
  }
  /** It turns about and fetches a book of its own choosing. */
  function pick() {
    if (!beeIn || w.held() >= 0 || sent >= 0 || away || w.count() < 2) return;
    let i = Math.floor(Math.random() * w.count());
    if (i === perch) i = (i + 1) % w.count();
    sent = i;
    landedOn = -1;
    spin = Math.PI * 2;
    setTimeout(() => {
      void w.seek(i).finally(() => (sent = -1));
    }, w.T(420));
  }
  function over(e: PointerEvent | MouseEvent) {
    if (!beeIn) return false;
    const ray = w.rayAt(e);
    if (!ray) return false;
    bee.group.updateMatrixWorld(true);
    return ray.intersectObject(bee.group, true).length > 0;
  }

  function frame(now: number) {
    if (!beeIn) return;
    const dt = Math.min(0.05, (now - beeLast) / 1000);
    beeLast = now;
    beeTime += dt;
    const sl = w.scrolled();
    if (sl !== beeScroll) {
      beeScroll = sl;
      stirred = now;
    }

    const pointed = w.hover();
    let to: { x: number; y: number; z: number };
    let spot: ReturnType<typeof headOf> = null;
    if (away) to = { ...away, z: 34 };
    else {
      if (sent >= 0) perch = sent;
      // Reached for, or restless: off to another head.
      else if (
        perch >= 0 &&
        (pointed === perch || (landedOn === perch && now > restless))
      ) {
        const next = another(perch, pointed);
        if (next >= 0) {
          perch = next;
          landedOn = -1;
          // Some of its flights it rolls over, or turns head over heels.
          const whim = Math.random();
          if (whim < 0.3) roll = Math.PI * 2 * (Math.random() < 0.5 ? 1 : -1);
          else if (whim < 0.5) tumble = Math.PI * 2;
        }
        if (pointed >= 0) startled = now + 900;
        restless = now + 7000 + Math.random() * 9000;
      }
      if (perch === w.held()) perch = -1;
      spot = perch >= 0 ? headOf(perch) : null;
      if (spot && !inWindow(spot.x)) {
        // Out of the window. (Sent for a book, it waits for it to come.)
        if (sent < 0) perch = -1;
        spot = null;
      }
      if (!spot && sent < 0 && now - stirred > 380) {
        // The shelf is still: down onto the nearest head.
        perch = nearest(
          Math.max(
            w.camX() - w.worldW() / 2 + 60,
            Math.min(w.camX() + w.worldW() / 2 - 60, at3.x),
          ),
        );
        spot = perch >= 0 ? headOf(perch) : null;
      }
      // On the wing: above the books, keeping to its side of the window.
      to = spot ?? {
        x: w.camX() + (sent >= 0 ? 0 : -0.3) * w.worldW(),
        y: w.tallest + 38 + Math.sin(beeTime * 3.1) * 5,
        z: 30,
      };
    }

    const landed = !!spot && landedOn === perch;
    // On the wing with no book to make for, it keeps its place in the
    // window: the shelf slides by under it.
    if (!spot && !away) at3.x += w.camX() - beeCam;
    beeCam = w.camX();
    const before = at3.x;
    if (landed)
      at3.set(to.x, to.y, to.z); // it rides its book
    else {
      // From one head to the next it flies: up, over, and down.
      const dx = to.x - at3.x;
      const dy = to.y - at3.y;
      const far = Math.hypot(dx, dy);
      nearing = !!spot && far < 90;
      const k = w.reduced ? 1 : 1 - Math.exp(-dt * (away ? 7 : 5.5));
      const lift = spot ? Math.min(46, far * 0.5) : 0;
      at3.x += dx * k;
      at3.y += (dy + lift) * k;
      at3.z += ((far > 14 ? 34 : to.z) - at3.z) * k;
      if (far < 1.2) {
        if (spot) landedOn = perch;
      }
    }
    const k2 = w.reduced ? 1 : 1 - Math.exp(-dt * 6);
    beeBig += (beeBigTo - beeBig) * k2;
    if (away && arrived && at3.y > w.top + 1.6 * BEE) {
      arrived();
      arrived = null;
    }
    wingsOpen += ((landed ? 0 : 1) - wingsOpen) * (1 - Math.exp(-dt * 10));
    spin *= Math.exp(-dt * 7);
    if (spin < 0.01) spin = 0;
    roll *= Math.exp(-dt * 5);
    if (Math.abs(roll) < 0.01) roll = 0;
    tumble *= Math.exp(-dt * 5);
    if (tumble < 0.01) tumble = 0;
    // Where it stands it does not keep the one pose: it looks to one
    // side, to the other — its face always in view, never its back.
    // Nor does it come down the same way twice: each landing has its own
    // turn, taken up as it comes in. (Upright always: it does not lean.)
    const stance = () => {
      standYaw =
        Math.random() < 0.14
          ? 0 // as the logo stands
          : -1.15 + Math.random() * 1.6;
    };
    if (!landed) {
      if (wasLanded) stance(); // taking off: how it will stand next
      yawTo = nearing ? standYaw : 0;
      turnAt = now + 2600 + Math.random() * 5200;
    } else if (now > turnAt) {
      stance();
      yawTo = standYaw;
      turnAt = now + 2600 + Math.random() * 5200;
    }
    wasLanded = landed;
    if (landed) nearing = false;
    yaw += (yawTo - yaw) * (1 - Math.exp(-dt * 5));
    const vx = (at3.x - before) / Math.max(dt, 0.001);
    const lean = landed ? 0 : Math.max(-1, Math.min(1, vx / 420));
    bee.group.position.copy(at3);
    bee.group.rotation.set(tumble, yaw + lean * 0.7 + spin, -lean * 0.3 + roll);
    bee.group.scale.setScalar(BEE * beeBig);
    bee.flap(wingsOpen, Math.sin(beeTime * 58));
    // Its face: startled off a book reached for; eager on an errand; the
    // logo's glad face on the wing; at rest, eyes open, blinking now and
    // then.
    if (landed && now > blink + 150) blink = now + 2200 + Math.random() * 3800;
    if (
      bee.face(
        away
          ? "glad"
          : now < startled
            ? "startled"
            : sent >= 0 || spin > 0
              ? "eager"
              : !landed
                ? "glad"
                : now > blink
                  ? "blink"
                  : "calm",
      )
    )
      w.redraw();
    // Where it is on the screen, for a test to find it by.
    w.host.dataset.bee = `${Math.round((at3.x - w.camX()) * w.scale() + w.cssW() / 2)},${Math.round((w.top - at3.y) * w.scale())},${landed ? "landed" : "flying"}`;
    if (
      !landed ||
      wingsOpen > 0.01 ||
      spin > 0 ||
      roll !== 0 ||
      tumble > 0 ||
      Math.abs(yaw - yawTo) > 0.004 ||
      Math.abs(beeBig - beeBigTo) > 0.002
    )
      w.redraw();
  }

  return {
    enter,
    leave,
    hide,
    pick,
    over,
    frame,
    dispose: () => bee.dispose(),
  };
}
