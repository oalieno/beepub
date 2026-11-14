// The bookshelf view: one long shelf of standing books, drawn as a real 3D
// scene and slid along sideways.
//
// The shelf's host scrolls horizontally; the canvas stays put in it and
// the eye moves along the shelf with the scroll, so what is in front of
// you is always seen square on. Only the books near the window hold
// meshes and textures.
//
// Taking a book down moves the book itself — the same object, under the
// same lamp — onto a canvas that covers the screen, whose camera stands
// exactly where the shelf's does. Nothing is swapped for a stand-in.
import * as THREE from "three";
import {
  DIVE_MS,
  SURFACE_MS,
  breathAt,
  diveAmount,
  driftAt,
  scaleAt,
  surfaceAmount,
} from "./portal";
import { createBeeFlight } from "./beeFlight";
import {
  PAPER,
  hash,
  hex,
  inkOn,
  lengthOf,
  lookOf,
  lum,
  plainCover,
  raw,
  spineCanvas,
  spinePlan,
  srgb,
  std,
  titleParts,
  type Look,
  type RGB,
} from "./bookArt";

export interface ShelfBook {
  id: string;
  title: string;
  author: string;
  cover: string | null;
  words: number | null;
  /** Books of one series stand at one height. */
  series: string | null;
}

export interface ShelfEls {
  /** Where the shelves go. */
  host: HTMLElement;
  /** The full-screen layer a book in hand is shown on. */
  stage: HTMLElement;
  scrim: HTMLElement;
  /** Receives the stage's canvas. */
  glHost: HTMLElement;
  /** The words beside the closed book. */
  cap: HTMLElement;
  /** The two pages' words, laid over the opened book. */
  left: HTMLElement;
  right: HTMLElement;
}

export interface ShelfHooks {
  /** The book now in hand (its index), or null once it is back. */
  held(index: number | null): void;
  /** The far end of the shelf is near: more books are wanted. */
  end(): void;
  /** WebGL is not to be had. */
  failed(): void;
}

export interface Part {
  b: ShelfBook;
  i: number;
  h: number;
  w: number;
  d: number;
  who: string;
  look: Look | null;
  group: THREE.Group | null;
  /** Its look is being fetched, or it waits its turn to be built. */
  pending: boolean;
  x: number;
  out: number;
}
type Pose = Record<
  "x" | "y" | "z" | "rx" | "ry" | "rz" | "lid" | "art",
  number
>;

// ---- sizes (world units are CSS px at the plane of the spines) --------
const PLANK = 34;
const FRONT = 110;
const TALLEST = 424; // just under the plank above
const BACK = -332; // behind the deepest book there can be
const EYE_Y = 410;
const EYE_Z = 2500;
const BOARD = 5;
const DIP = 8;
const EDGE = 26;
const GAP = 2;
// What is in the picture, at the plane of the spines: the shelf's books,
// wall above them and the plank's face and its shadow below.
const VIEW_TOP = 540;
const VIEW_BOTTOM = -120;
const VIEW_H = VIEW_TOP - VIEW_BOTTOM;
const WALL_H = 1100;

// A book hooked out by its head: forward a little, its head tipped out —
// straight, not turned to show its cover.
const TIP = { z: 34, rx: 0.2 };
const STIR = { z: 7, rx: 0.055 }; // under the pointer
const REACH = 1.05; // the turn (radians) either side of face on that is approached, never reached

export function createShelf(els: ShelfEls, hooks: ShelfHooks) {
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const T = (ms: number) => (reduced ? 1 : ms);

  let gl: THREE.WebGLRenderer;
  try {
    gl = new THREE.WebGLRenderer({
      antialias: true,
      preserveDrawingBuffer: true,
    });
  } catch {
    hooks.failed();
    return null;
  }
  gl.shadowMap.enabled = true;
  gl.shadowMap.type = THREE.PCFShadowMap;
  gl.setClearColor(0x0e0a07);

  let dead = false;
  let parts: Part[] = [];
  let scale = 1; // screen px per world unit at the plane of the spines
  let cssW = 0; // the window onto the shelf, CSS px
  let worldW = 0; // the same, world units
  let rowH = VIEW_H;
  let total = 0; // the whole shelf's length, world units
  let camX = 0; // where along the shelf the eye stands
  let hover = -1;
  let dirty = true;
  let asked = -1; // the shelf length more books were last asked at
  const built = new Set<Part>();
  const queue: Part[] = []; // looks known, meshes not yet made

  // The host scrolls sideways; the canvas stays in its window and a strip
  // as long as the shelf gives it something to scroll.
  const view = gl.domElement;
  view.style.cssText = "position:sticky;left:0;display:block";
  const strip = document.createElement("div");
  strip.style.cssText = "height:1px;margin-top:-1px;pointer-events:none";
  els.host.append(view, strip);

  // ---- the room: plank, wall and lamp go along with the eye -------------
  const room = new THREE.Scene();
  const shelf = new THREE.Group(); // the books
  const fixtures = new THREE.Group();
  room.add(shelf, fixtures);
  room.add(
    new THREE.HemisphereLight(raw(0xfff2e0), raw(0x2a1b10), 0.4 * Math.PI),
  );
  const lamp = new THREE.DirectionalLight(raw(0xffe6c4), 0.86 * Math.PI);
  lamp.castShadow = true;
  lamp.shadow.mapSize.set(2048, 2048);
  lamp.shadow.radius = 9;
  lamp.shadow.bias = -0.0015;
  lamp.shadow.normalBias = 2;
  room.add(lamp, lamp.target);
  const camera = new THREE.PerspectiveCamera();

  const wood = std([74, 53, 38], 0.75);
  // A lamp somewhere above washes the wall behind the books and dies
  // away toward the ceiling and the floor.
  const glow = document.createElement("canvas");
  glow.width = 4;
  glow.height = 256;
  {
    const g = glow.getContext("2d")!;
    const grad = g.createLinearGradient(0, 0, 0, 256);
    grad.addColorStop(0, "#1a110a");
    grad.addColorStop(0.2, "#5d4028");
    grad.addColorStop(0.36, "#8a6038");
    grad.addColorStop(0.6, "#3a2717");
    grad.addColorStop(0.78, "#150d07");
    grad.addColorStop(1, "#090604");
    g.fillStyle = grad;
    g.fillRect(0, 0, 4, 256);
  }
  const glowTx = new THREE.CanvasTexture(glow);
  glowTx.colorSpace = THREE.SRGBColorSpace;
  const wallMat = new THREE.MeshStandardMaterial({
    color: srgb([70, 51, 37]),
    roughness: 1,
    emissive: 0xffffff,
    emissiveMap: glowTx,
    emissiveIntensity: 0.5,
  });

  function furnish() {
    for (const o of fixtures.children) (o as THREE.Mesh).geometry.dispose();
    fixtures.clear();
    const box = (
      w: number,
      h: number,
      d: number,
      mat: THREE.Material,
      y: number,
      z: number,
      cast = true,
    ) => {
      const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat);
      m.position.set(0, y, z);
      m.castShadow = cast;
      m.receiveShadow = true;
      fixtures.add(m);
    };
    const depth = FRONT - BACK;
    const midZ = (FRONT + BACK) / 2;
    // One plank, thick enough to be seen as one: its top in front of the
    // books, its face, and its shadow on the wall under it.
    box(worldW + 900, PLANK, depth, wood, -PLANK / 2, midZ);
    const wall = new THREE.Mesh(
      new THREE.PlaneGeometry(worldW * 1.3 + 900, WALL_H),
      wallMat,
    );
    wall.position.set(0, (VIEW_TOP + VIEW_BOTTOM) / 2, BACK + 1);
    wall.receiveShadow = true;
    fixtures.add(wall);

    const sc = lamp.shadow.camera;
    sc.left = -worldW / 2 - 260;
    sc.right = worldW / 2 + 260;
    sc.top = 620;
    sc.bottom = -620;
    sc.near = 200;
    sc.far = 3600;
    sc.updateProjectionMatrix();

    // The eye a little above the middle of the shelf and far enough back
    // to be gentle; the frustum cut so the plane of the spines maps one
    // to one onto the canvas.
    const n = 300;
    const f = 5000;
    const s = n / EYE_Z;
    camera.projectionMatrix.makePerspective(
      (-worldW / 2) * s,
      (worldW / 2) * s,
      (VIEW_TOP - EYE_Y) * s,
      (VIEW_BOTTOM - EYE_Y) * s,
      n,
      f,
    );
    camera.projectionMatrixInverse.copy(camera.projectionMatrix).invert();
  }

  // Stand the eye where the scroll says.
  function aim(at = els.host.scrollLeft) {
    camX = at / scale + worldW / 2;
    camera.position.set(camX, EYE_Y, EYE_Z);
    camera.updateMatrixWorld();
    fixtures.position.x = camX;
    lamp.position.set(camX - 700, 900, 1300);
    lamp.target.position.set(camX, 190, -60);
    dirty = true;
  }

  // ---- a book -----------------------------------------------------------
  function bookMesh(p: Part) {
    const c = p.look!.cloth;
    const d = p.d;
    const clothMat = std(c, 0.92);
    const paperMat = std(PAPER, 1);
    const group = new THREE.Group();
    const add = (
      geo: THREE.BufferGeometry,
      mat: THREE.Material,
      x: number,
      y: number,
      z: number,
      parent: THREE.Object3D = group,
    ) => {
      const m = new THREE.Mesh(geo, mat);
      m.position.set(x, y, z);
      m.castShadow = m.receiveShadow = true;
      m.userData.book = p.i;
      parent.add(m);
      return m;
    };
    // The back board, as tall as the spine.
    const board = new THREE.BoxGeometry(BOARD, p.h, d - 6);
    add(board, clothMat, -p.w / 2 + BOARD / 2, p.h / 2, -6 - (d - 6) / 2);
    // The front board is a lid, hinged where it meets the spine: outside
    // it carries the cover, inside it is paper.
    const lid = new THREE.Group();
    lid.position.set(p.w / 2, 0, -6);
    group.add(lid);
    const lidBoard = add(
      board,
      clothMat,
      -BOARD / 2,
      p.h / 2,
      -(d - 6) / 2,
      lid,
    );
    // The cover's picture is only fetched when the book is taken down.
    const coverTx = new THREE.Texture();
    coverTx.colorSpace = THREE.SRGBColorSpace;
    const side = new THREE.PlaneGeometry(d - 6, p.h);
    const artMat = new THREE.MeshStandardMaterial({
      map: coverTx,
      roughness: 0.85,
      metalness: 0,
      transparent: true,
      opacity: 0,
      emissive: 0xffffff,
      emissiveMap: coverTx,
      emissiveIntensity: 0.1,
    });
    const art = add(side, artMat, 0.4, p.h / 2, -(d - 6) / 2, lid);
    art.rotation.y = Math.PI / 2;
    art.castShadow = false;
    art.visible = false; // on the shelf the board is plain cloth
    const inner = add(side, paperMat, -BOARD - 0.4, p.h / 2, -(d - 6) / 2, lid);
    inner.rotation.y = -Math.PI / 2;
    inner.castShadow = false;
    // The block of pages: lower than the boards, in from them, short of
    // the fore edge.
    const block = add(
      new THREE.BoxGeometry(p.w - BOARD * 2 - 1, p.h - DIP * 2, d - 14),
      paperMat,
      0,
      p.h / 2,
      -BOARD - (d - 14) / 2,
    );
    // The spine: solid, flat, its two long edges eased round.
    const ease = 4.5;
    const half = p.w / 2;
    const sec = new THREE.Shape();
    sec.moveTo(-half, 6.5);
    sec.lineTo(-half, ease);
    sec.absarc(-half + ease, ease, ease, Math.PI, Math.PI * 1.5, false);
    sec.lineTo(half - ease, 0);
    sec.absarc(half - ease, ease, ease, Math.PI * 1.5, Math.PI * 2, false);
    sec.lineTo(half, 6.5);
    sec.closePath();
    const solid = new THREE.ExtrudeGeometry(sec, {
      depth: p.h,
      bevelEnabled: false,
      curveSegments: 8,
    });
    solid.rotateX(-Math.PI / 2); // the section lies flat, the spine rises from it
    add(solid, clothMat, 0, 0, 0);
    // Over it, the face that carries the title, following the same curve.
    const face = new THREE.PlaneGeometry(p.w, p.h, 32, 1);
    const pos = face.attributes.position;
    const uv = face.attributes.uv;
    for (let v = 0; v < pos.count; v++) {
      // Points gathered toward the two edges, where the curve turns
      // fastest; the title's image follows them, so it is not stretched.
      const t = pos.getX(v) / half;
      const u = Math.sin((t * Math.PI) / 2);
      pos.setX(v, u * half);
      const r = Math.min(1, ((1 - Math.abs(u)) * half) / ease);
      pos.setZ(v, -ease * (1 - Math.sqrt(1 - (1 - r) * (1 - r))));
      uv.setX(v, (u + 1) / 2);
    }
    face.computeVertexNormals();
    const tx = new THREE.CanvasTexture(spineCanvas(p));
    tx.colorSpace = THREE.SRGBColorSpace;
    tx.anisotropy = gl.capabilities.getMaxAnisotropy();
    add(
      face,
      new THREE.MeshStandardMaterial({
        map: tx,
        roughness: 0.92,
        metalness: 0,
        polygonOffset: true,
        polygonOffsetFactor: -2,
        polygonOffsetUnits: -2,
      }),
      0,
      p.h / 2,
      0.05,
    ).castShadow = false;
    group.userData = { lid, art, lidBoard, block, coverTx, covered: false };
    return group;
  }

  function scrap(p: Part) {
    const g = p.group;
    if (!g) return;
    g.removeFromParent();
    g.traverse((o) => {
      const m = o as THREE.Mesh;
      if (!m.isMesh) return;
      m.geometry.dispose();
      const mat = m.material as THREE.MeshStandardMaterial;
      mat.map?.dispose();
      mat.dispose();
    });
    p.group = null;
    p.out = 0;
    built.delete(p);
    dirty = true;
  }

  // ---- the shelf -------------------------------------------------------
  function sizeOf(b: ShelfBook, i: number) {
    const n = hash(b.series ? `series:${b.series}` : b.id);
    // A book is seven to ten times as tall as it is thick. Heights differ
    // a little; now and then one is clearly shorter. The volumes of a
    // series stand at one height.
    const base = n % 7 === 4 ? 326 : 356 + ((n >>> 3) % 6) * 7;
    // Thickness follows the book's length, within what a shelf of novels
    // looks like. A count of next to nothing (a book of pictures) says
    // nothing about it.
    const words = b.words && b.words > 3000 ? b.words : 60000;
    const thick = Math.max(30, Math.min(68, Math.round(26 + words / 9000)));
    const w = Math.round(34 + (thick - 30) * 0.6);
    // A long foreign name goes on the spine by its surname.
    const sep = /[．·‧・]/;
    // The name as on a spine: no bracketed original name after it.
    const name =
      b.author.replace(/\s*[（(【\[][^）)】\]]*[）)】\]]?\s*/g, "").trim() ||
      b.author;
    const who =
      name.length > 5 && sep.test(name) ? name.split(sep).pop()! : name;
    // A long title gets a taller book, as far as the shelf has headroom,
    // so it can be read at a fair size. In a series the volume number is
    // left out of the reckoning (two figures' room is allowed instead),
    // so "9" and "10" come out the same height.
    const plan = spinePlan(base, w, who, b.title);
    const t = [...plan.tokens];
    const numbered =
      !!b.series && t.length > 1 && /^[0-9.]+$/.test(t[t.length - 1]);
    if (numbered) t.pop();
    // A subtitle is set at a little over half the title's size.
    const [main, sub] = titleParts(t);
    const len =
      (sub.length
        ? lengthOf(main) + 0.5 + lengthOf(sub) * 0.58
        : lengthOf(main)) + (numbered ? 1.4 : 0);
    const authorLen = base - 40 - plan.authorTop;
    const need = Math.ceil((len * 1.12 * 15 + 62 + authorLen) / 0.9);
    const h = Math.min(TALLEST, Math.max(base, need));
    return { b, i, h, w, who };
  }

  function setBooks(next: ShelfBook[]) {
    if (dead) return;
    if (held) putBack();
    const old = new Map(parts.map((p) => [p.b.id, p]));
    parts = next.map((b, i) => {
      const was = old.get(b.id);
      // The same book in the same place keeps what was built for it.
      if (
        was &&
        was.i === i &&
        was.b.title === b.title &&
        was.b.author === b.author &&
        was.b.cover === b.cover &&
        was.b.words === b.words &&
        was.b.series === b.series
      ) {
        old.delete(b.id);
        was.b = b;
        return was;
      }
      return {
        ...sizeOf(b, i),
        d: 0,
        look: null,
        group: null,
        pending: false,
        x: 0,
        out: 0,
      };
    });
    for (const p of old.values()) scrap(p);
    queue.length = 0;
    for (const p of parts) if (!p.group) p.pending = false;
    layout();
  }

  // The picture fills its host: the whole screen.
  function tall() {
    return Math.max(320, els.host.clientHeight || innerHeight);
  }

  function layout() {
    if (dead) return;
    const width = els.host.clientWidth;
    if (!width) return;
    if (held) putBack();
    if (width !== cssW || tall() !== rowH) {
      cssW = width;
      // One shelf, as tall as the screen has room for.
      rowH = tall();
      scale = rowH / VIEW_H;
      worldW = cssW / scale;
      gl.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
      gl.setSize(cssW, rowH, false);
      view.style.width = `${cssW}px`;
      view.style.height = `${rowH}px`;
      furnish();
    }
    let x = EDGE;
    for (const p of parts) {
      p.x = x + p.w / 2;
      x += p.w + GAP;
      if (p.group && !(held && held.g === p.group)) p.group.position.x = p.x;
    }
    total = x - GAP + EDGE;
    strip.style.width = `${Math.max(total, worldW) * scale}px`;
    els.host.dataset.books = String(parts.length);
    aim();
    sync();
  }

  // Build the books near the window; let go of the ones far from it; ask
  // for more when the end of the shelf comes near.
  function sync() {
    if (dead) return;
    const near0 = camX - worldW * 1.7;
    const near1 = camX + worldW * 1.7;
    const far0 = camX - worldW * 3.5;
    const far1 = camX + worldW * 3.5;
    for (const p of parts) {
      if (p.x > near0 && p.x < near1) {
        if (!p.group && !p.pending) want(p);
      } else if (
        (p.x < far0 || p.x > far1) &&
        p.group &&
        !(held && held.i === p.i)
      )
        scrap(p);
    }
    if (parts.length && camX + worldW * 2 > total && asked !== parts.length) {
      asked = parts.length;
      hooks.end();
    }
  }

  function want(p: Part) {
    p.pending = true;
    lookOf(p.b).then((look) => {
      if (dead || parts[p.i] !== p || !p.pending) return;
      p.look = look;
      // As deep as its cover is wide.
      p.d = Math.round(p.h / look.ratio);
      queue.push(p);
    });
  }

  function make(p: Part) {
    p.pending = false;
    if (parts[p.i] !== p || p.group) return;
    p.group = bookMesh(p);
    p.group.position.set(p.x, 0, 0);
    shelf.add(p.group);
    built.add(p);
    dirty = true;
  }

  // Resolves once this book stands on the shelf (or will not).
  function standing(p: Part) {
    return new Promise<void>((done) => {
      const t0 = performance.now();
      const look = () => {
        if (
          dead ||
          parts[p.i] !== p ||
          p.group ||
          performance.now() - t0 > 8000
        )
          return done();
        if (!p.pending) want(p);
        requestAnimationFrame(look);
      };
      look();
    });
  }

  let raf = 0;
  function frame() {
    raf = requestAnimationFrame(frame);
    if (glide !== null) {
      const now = performance.now();
      const t = Math.min(0.05, Math.max(0, (now - glideTime) / 1000));
      glideTime = now;
      const off = pos - glide;
      const pull = speed + STIFF * off;
      const decay = Math.exp(-STIFF * t);
      pos = glide + (off + pull * t) * decay;
      speed = (speed - STIFF * pull * t) * decay;
      if (Math.abs(pos - glide) < 0.5 && Math.abs(speed) < 8) {
        pos = glide;
        glide = null;
      }
      els.host.scrollLeft = pos;
      aim(pos);
      sync();
    }
    flight.frame(performance.now());
    // A few books a frame: a shelf-full at once would stall the scroll.
    for (let n = 0; n < 5 && queue.length; n++) make(queue.shift()!);
    for (const p of built) {
      if (!p.group || (held && held.i === p.i)) continue; // in hand: moved by its own animation
      // Under the pointer a book only stirs: its head tips out a touch.
      // Taking it down is what the click does.
      const want = p.i === hover && !held ? 1 : 0;
      if (p.out === want) continue;
      const next = reduced ? want : p.out + (want - p.out) * 0.16;
      p.out = Math.abs(next - want) < 0.004 ? want : next;
      const e = p.out * p.out * (3 - 2 * p.out);
      p.group.position.z = e * STIR.z;
      p.group.rotation.set(e * STIR.rx, 0, 0);
      dirty = true;
    }
    if (dirty && cssW) {
      dirty = false;
      gl.render(room, camera);
      els.host.dataset.drawn = String(built.size);
    }
    if (held && stage) stage.gl.render(stage.scene, stage.cam);
  }

  // Which book is under the pointer.
  const ray = new THREE.Raycaster();
  /** A ray from the eye through where the pointer is (none: off the
   *  picture). */
  function rayAt(e: MouseEvent) {
    const box = view.getBoundingClientRect();
    const ndc = new THREE.Vector2(
      ((e.clientX - box.left) / box.width) * 2 - 1,
      -((e.clientY - box.top) / box.height) * 2 + 1,
    );
    if (Math.abs(ndc.x) > 1 || Math.abs(ndc.y) > 1) return null;
    ray.setFromCamera(ndc, camera);
    return ray;
  }
  function pick(e: PointerEvent | MouseEvent) {
    if (!rayAt(e)) return -1;
    shelf.updateMatrixWorld(true);
    const hit = ray
      .intersectObjects(shelf.children, true)
      .find((h) => h.object.userData.book !== undefined && h.object.visible);
    return hit ? (hit.object.userData.book as number) : -1;
  }

  // ---- the book in hand -------------------------------------------------
  interface Held {
    i: number;
    g: THREE.Group;
    at: "shelf" | "hand" | "open";
    busy: boolean;
    away: boolean; // on the stage, not in its shelf's picture
    from: Pose;
    home: Pose;
    out: Pose;
    clear: Pose;
    hand: Pose;
    open: Pose;
  }
  let held: Held | null = null;
  let stage: {
    gl: THREE.WebGLRenderer;
    scene: THREE.Scene;
    cam: THREE.PerspectiveCamera;
    lamp: THREE.DirectionalLight;
  } | null = null;
  const ray2 = new THREE.Raycaster();

  function stageOf() {
    if (stage) return stage;
    const sgl = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    sgl.setClearColor(0x000000, 0);
    const scene = new THREE.Scene();
    scene.add(
      new THREE.HemisphereLight(raw(0xfff2e0), raw(0x2a1b10), 0.4 * Math.PI),
    );
    const slamp = new THREE.DirectionalLight(raw(0xffe6c4), 0.86 * Math.PI);
    scene.add(slamp, slamp.target);
    const cam = new THREE.PerspectiveCamera();
    els.glHost.appendChild(sgl.domElement);
    return (stage = { gl: sgl, scene, cam, lamp: slamp });
  }

  const easeInOut = (t: number) =>
    t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2;
  const easeSine = (t: number) => 0.5 - Math.cos(Math.PI * t) / 2;
  function tween(ms: number, step: (t: number) => void, ease = easeInOut) {
    return new Promise<void>((done) => {
      const t0 = performance.now();
      const d = T(ms);
      const tick = () => {
        if (dead) return done();
        const t = Math.min(1, (performance.now() - t0) / d);
        step(ease(t));
        if (t < 1) requestAnimationFrame(tick);
        else done();
      };
      tick();
    });
  }
  // A path through several poses, as one curve (Catmull-Rom): the book
  // passes through each without stopping at it.
  function along(poses: Pose[], times: number[]) {
    const keys = Object.keys(poses[0]) as (keyof Pose)[];
    return (t: number) => {
      let i = 0;
      while (i < times.length - 2 && t > times[i + 1]) i++;
      const u = (t - times[i]) / (times[i + 1] - times[i]);
      const p0 = poses[Math.max(0, i - 1)];
      const p1 = poses[i];
      const p2 = poses[i + 1];
      const p3 = poses[Math.min(poses.length - 1, i + 2)];
      const out = {} as Pose;
      for (const k of keys) {
        const a = p0[k];
        const b = p1[k];
        const c = p2[k];
        const d = p3[k];
        out[k] =
          0.5 *
          (2 * b +
            (c - a) * u +
            (2 * a - 5 * b + 4 * c - d) * u * u +
            (3 * b - a - 3 * c + d) * u * u * u);
      }
      out.art = Math.min(1, Math.max(0, out.art));
      return out;
    };
  }
  const mixPose = (a: Pose, b: Pose, t: number) =>
    Object.fromEntries(
      (Object.keys(a) as (keyof Pose)[]).map((k) => [
        k,
        a[k] + (b[k] - a[k]) * t,
      ]),
    ) as Pose;
  function pose(g: THREE.Group, p: Pose) {
    g.position.set(p.x, p.y, p.z);
    g.rotation.set(p.rx, p.ry, p.rz);
    g.userData.lid.rotation.y = p.lid;
    g.userData.art.material.opacity = p.art;
  }

  // The cover's picture, put on the lid when the book is first taken down.
  function cover(p: Part) {
    const u = p.group!.userData;
    if (u.covered) return;
    u.covered = true;
    const tx = u.coverTx as THREE.Texture;
    const set = (image: HTMLImageElement | HTMLCanvasElement) => {
      tx.image = image;
      tx.needsUpdate = true;
    };
    if (!p.b.cover) return set(plainCover(p));
    const img = new Image();
    img.onload = () => set(img);
    img.onerror = () => set(plainCover(p));
    img.src = p.b.cover;
  }

  function build(i: number): Held {
    const p = parts[i];
    const g = p.group!;
    const c = p.look!.cloth;
    const strong: RGB = lum(c) < 0.5 ? c : [44, 36, 27];
    const vw = innerWidth;
    const vh = innerHeight;
    const narrow = vw < 760;
    const box = view.getBoundingClientRect();
    // The shelf's eye, on the screen.
    const ex = box.left + box.width / 2;
    const ey = box.top + (VIEW_TOP - EYE_Y) * scale;
    const st = stageOf();
    st.gl.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
    st.gl.setSize(vw, vh, false);
    const n = 300;
    const f = 6000;
    const sc = n / EYE_Z / scale;
    st.cam.position.set(camX, EYE_Y, EYE_Z);
    st.cam.updateMatrixWorld();
    st.cam.projectionMatrix.makePerspective(
      -ex * sc,
      (vw - ex) * sc,
      ey * sc,
      (ey - vh) * sc,
      n,
      f,
    );
    st.cam.projectionMatrixInverse.copy(st.cam.projectionMatrix).invert();
    st.lamp.position.set(camX - 700, 900, 1300);
    st.lamp.target.position.set(camX, 190, -60);

    // Where the book must stand in the room for its cover — face on, its
    // hinge at screen x, its foot at screen y — to be seen at k screen px
    // to the unit.
    const place = (sx: number, syFoot: number, k: number) => ({
      x: camX + (sx - ex) / k - 6,
      y: EYE_Y - (syFoot - ey) / k,
      z: EYE_Z * (1 - scale / k) - p.w / 2,
    });
    const coverW = p.d - 6;
    let hand: { x: number; y: number; z: number };
    let capCss: string;
    if (narrow) {
      const k = Math.min((vh * 0.46) / p.h, (vw * 0.6) / coverW);
      const top = Math.max(56, vh * 0.09);
      hand = place(vw / 2 - (coverW * k) / 2 + (p.w * k) / 4, top + p.h * k, k);
      capCss = `left:24px;right:24px;top:${top + p.h * k + 28}px`;
    } else {
      const k = Math.min(520, vh - 220) / p.h;
      const sx = vw / 2 + 70;
      hand = place(sx, (vh - 50) / 2 + (p.h * k) / 2, k);
      const capW = Math.min(400, sx - 150);
      capCss = `left:${sx - 110 - capW}px;width:${capW}px;top:50%;transform:translateY(-58%)`;
    }
    // Open: the hinge mid-screen, a page on each side.
    const pageW = Math.min(520, (vw - 48) / 2, ((vh - 130) * coverW) / p.h);
    const k2 = pageW / coverW;
    const foot2 = (vh - 60) / 2 + (p.h * k2) / 2;
    const openAt = place(vw / 2, foot2, k2);

    const s = els.stage.style;
    s.setProperty("--cloth", hex(c));
    s.setProperty("--strong", hex(strong));
    s.setProperty("--on-strong", inkOn(strong));
    els.cap.style.cssText = capCss;
    els.cap.classList.toggle("center", narrow);
    els.stage.classList.remove("shown", "inhand", "opened");
    els.stage.hidden = false;

    const TURN = -Math.PI / 2;
    return {
      i,
      g,
      at: "shelf",
      busy: true,
      away: false,
      // As it stands (or leans, under the pointer) on the shelf.
      from: {
        x: g.position.x,
        y: g.position.y,
        z: g.position.z,
        rx: g.rotation.x,
        ry: g.rotation.y,
        rz: g.rotation.z,
        lid: 0,
        art: 0,
      },
      home: { x: p.x, y: 0, z: 0, rx: 0, ry: 0, rz: 0, lid: 0, art: 0 },
      // Hooked out by its head.
      out: { x: p.x, y: 0, z: TIP.z, rx: TIP.rx, ry: 0, rz: 0, lid: 0, art: 0 },
      // Slid out along the shelf until it is clear of it, coming upright.
      clear: {
        x: p.x,
        y: 4,
        z: FRONT + 120,
        rx: 0.05,
        ry: 0,
        rz: 0,
        lid: 0,
        art: 0.6,
      },
      // In hand: the cover toward you, the spine still in view.
      hand: { ...hand, rx: 0, ry: TURN * 0.8, rz: 0, lid: 0, art: 1 },
      open: { ...openAt, rx: 0, ry: TURN, rz: 0, lid: -Math.PI, art: 1 },
    };
  }

  async function open(i: number) {
    const p = parts[i];
    if (held || dead || !p) return;
    if (!p.group) {
      await standing(p);
      if (held || dead || !parts[i]?.group) return;
    }
    hover = -1;
    const h = (held = build(i));
    hooks.held(i);
    cover(p);
    h.g.userData.art.visible = true;
    // Tipped out, slid out, carried over: three beats of one movement.
    // Among its neighbours the book stays in its shelf's picture, where
    // they can hide it; once clear of the shelf it is carried to the stage.
    const path = along([h.from, h.out, h.clear, h.hand], [0, 0.2, 0.5, 1]);
    await tween(
      1500,
      (t) => {
        if (held !== h) return;
        if (!h.away && t >= 0.5) {
          h.away = true;
          stage!.scene.add(h.g);
          els.stage.classList.add("shown");
        }
        pose(h.g, path(t));
        dirty = true;
      },
      easeSine,
    );
    if (held !== h) return;
    els.stage.classList.add("inhand");
    h.at = "hand";
    h.busy = false;
  }

  // In hand the book can be turned about with the pointer. It turns on
  // its own middle, not on its spine.
  let drag: {
    x: number;
    y: number;
    lx: number;
    ly: number;
    at: THREE.Vector3;
  } | null = null;
  let dragged = false;
  const middle = (p: Part, g: THREE.Group) =>
    new THREE.Vector3(0, p.h / 2, -p.d / 2).applyEuler(g.rotation);
  const onBook = (e: MouseEvent) => {
    ray2.setFromCamera(
      new THREE.Vector2(
        (e.clientX / innerWidth) * 2 - 1,
        -(e.clientY / innerHeight) * 2 + 1,
      ),
      stage!.cam,
    );
    return ray2.intersectObject(held!.g, true).length > 0;
  };
  function grab(e: PointerEvent) {
    const h = held;
    if (!h || h.busy || h.at !== "hand" || !onBook(e)) return;
    drag = {
      x: e.clientX,
      y: e.clientY,
      lx: e.clientX,
      ly: e.clientY,
      at: h.g.position.clone().add(middle(parts[h.i], h.g)),
    };
    dragged = false;
    els.scrim.setPointerCapture(e.pointerId);
  }
  // No hard stop: the further round it is, the less each pull turns it,
  // until it will not go further; a pull back the other way turns it
  // freely at once. The back is never reached.
  const soft = (now: number, by: number, mid: number, reach: number) => {
    const off = (now - mid) / reach;
    const away = by * off > 0;
    return now + (away ? by * Math.max(0, 1 - off * off) ** 1.5 : by);
  };
  function turn(e: PointerEvent) {
    const h = held;
    if (!drag || !h) return;
    if (!dragged && Math.hypot(e.clientX - drag.x, e.clientY - drag.y) < 5)
      return;
    if (!dragged) {
      drag.lx = e.clientX;
      drag.ly = e.clientY;
    }
    dragged = true;
    const mx = e.clientX - drag.lx;
    const my = e.clientY - drag.ly;
    drag.lx = e.clientX;
    drag.ly = e.clientY;
    h.g.rotation.set(
      soft(h.g.rotation.x, my * 0.006, 0, 0.5),
      soft(h.g.rotation.y, mx * 0.011, -Math.PI / 2, REACH),
      0,
    );
    h.g.position.copy(drag.at).sub(middle(parts[h.i], h.g));
    Object.assign(h.hand, {
      x: h.g.position.x,
      y: h.g.position.y,
      z: h.g.position.z,
      rx: h.g.rotation.x,
      ry: h.g.rotation.y,
    });
  }
  const drop = () => {
    drag = null;
  };
  // However far round it was turned, it goes on from the nearest face of
  // that turn.
  function unturn(h: Held) {
    const full = Math.PI * 2;
    const want = -Math.PI / 2;
    h.hand.ry =
      ((((h.hand.ry - want + Math.PI) % full) + full) % full) - Math.PI + want;
  }

  // Where a part of the book in hand is on the screen: the pages' words
  // are laid exactly over the opened cover and the block of pages, as the
  // camera sees them — not where arithmetic says they ought to be.
  function onScreen(mesh: THREE.Mesh) {
    mesh.geometry.computeBoundingBox();
    const bb = mesh.geometry.boundingBox!;
    const v = new THREE.Vector3();
    let x0 = Infinity;
    let y0 = Infinity;
    let x1 = -Infinity;
    let y1 = -Infinity;
    for (const x of [bb.min.x, bb.max.x])
      for (const y of [bb.min.y, bb.max.y])
        for (const z of [bb.min.z, bb.max.z]) {
          v.set(x, y, z).applyMatrix4(mesh.matrixWorld).project(stage!.cam);
          const sx = ((v.x + 1) / 2) * innerWidth;
          const sy = ((1 - v.y) / 2) * innerHeight;
          x0 = Math.min(x0, sx);
          x1 = Math.max(x1, sx);
          y0 = Math.min(y0, sy);
          y1 = Math.max(y1, sy);
        }
    return { x0, y0, x1, y1 };
  }
  function layPages(h: Held) {
    h.g.updateMatrixWorld(true);
    const u = h.g.userData;
    const l = onScreen(u.lidBoard);
    const r = onScreen(u.block);
    const hinge = (l.x1 + r.x0) / 2;
    const put = (
      el: HTMLElement,
      x0: number,
      y0: number,
      x1: number,
      y1: number,
    ) => {
      el.style.cssText = `left:${x0}px;top:${y0}px;width:${x1 - x0}px;height:${y1 - y0}px`;
    };
    put(els.left, l.x0 - 1, l.y0 - 1, hinge, l.y1 + 1);
    put(els.right, hinge, r.y0, r.x1, r.y1);
    els.stage.style.setProperty("--pw", `${hinge - l.x0}px`);
    els.stage.style.setProperty(
      "--fs",
      `${Math.max(9, (hinge - l.x0) / 21)}px`,
    );
    // The description shows as many whole lines as the page has room for
    // above its foot — never half of one.
    const blurb = els.right.querySelector<HTMLElement>(".blurb");
    const foot = els.right.querySelector<HTMLElement>(".foot");
    if (blurb && foot) {
      blurb.style.setProperty("-webkit-line-clamp", "1");
      blurb.style.setProperty("line-clamp", "1");
      const line = parseFloat(getComputedStyle(blurb).lineHeight) || 20;
      const room =
        foot.getBoundingClientRect().top -
        blurb.getBoundingClientRect().top -
        line * 0.5;
      const lines = String(Math.max(1, Math.floor(room / line)));
      blurb.style.setProperty("-webkit-line-clamp", lines);
      blurb.style.setProperty("line-clamp", lines);
    }
  }

  async function flip() {
    const h = held;
    if (!h || h.busy || h.at !== "hand") return;
    h.busy = true;
    els.stage.classList.remove("inhand");
    unturn(h);
    await tween(760, (t) => pose(h.g, mixPose(h.hand, h.open, t)));
    if (held !== h) return;
    layPages(h);
    els.stage.classList.add("opened");
    h.at = "open";
    h.busy = false;
  }

  async function shut() {
    const h = held;
    if (!h || h.busy || h.at !== "open") return;
    h.busy = true;
    els.stage.classList.remove("opened");
    await new Promise((r) => setTimeout(r, T(160)));
    await tween(560, (t) => pose(h.g, mixPose(h.open, h.hand, t)));
    if (held !== h) return;
    els.stage.classList.add("inhand");
    h.at = "hand";
    h.busy = false;
  }

  function putBack() {
    const h = held;
    if (!h) return;
    const p = parts[h.i];
    held = null;
    h.away = false;
    h.g.removeFromParent();
    if (p?.group === h.g) {
      shelf.add(h.g);
      pose(h.g, h.home);
      h.g.userData.art.visible = false;
      h.g.userData.art.material.opacity = 0;
      p.out = 0;
      dirty = true;
    }
    els.stage.classList.remove("shown", "inhand", "opened", "diving");
    els.stage.style.transform = "";
    els.stage.hidden = true;
    stage?.gl.clear();
    // The page may have changed width while the book was out.
    if (!dead && (els.host.clientWidth !== cssW || tall() !== rowH))
      queueMicrotask(layout);
    drag = null;
    hooks.held(null);
  }

  async function close() {
    const h = held;
    if (!h || h.busy) return;
    h.busy = true;
    if (h.at === "open") {
      els.stage.classList.remove("opened");
      await new Promise((r) => setTimeout(r, T(160)));
      await tween(520, (t) => pose(h.g, mixPose(h.open, h.hand, t)));
    }
    if (held !== h) return;
    els.stage.classList.remove("inhand", "shown");
    unturn(h);
    const path = along([h.hand, h.clear, h.out, h.home], [0, 0.52, 0.8, 1]);
    await tween(
      1250,
      (t) => {
        if (held !== h) return;
        // Back in its shelf before it reaches its neighbours: they hide
        // it again.
        if (h.away && t >= 0.52) {
          h.away = false;
          shelf.add(h.g);
        }
        pose(h.g, path(t));
        if (!h.away) dirty = true;
      },
      easeSine,
    );
    if (held === h) putBack();
  }

  async function step(d: number) {
    const h = held;
    if (!h || h.busy || parts.length < 2) return;
    const next = (h.i + d + parts.length) % parts.length;
    await close();
    if (dead || held) return;
    // Bring the next one into the window before it is taken.
    const p = parts[next];
    const at = (p.x - camX) * scale;
    if (Math.abs(at) > cssW / 2 - 60 * scale) {
      els.host.scrollLeft = (p.x - worldW / 2) * scale;
      aim();
      sync();
    }
    await standing(p);
    open(next);
  }

  // ---- into the book, and out of it -------------------------------------
  // Reading starts by going in through the open book's page (portal.ts
  // draws the light; here the book comes at the eye). The whole stage is
  // scaled about that page, the words on it with it.
  function focus() {
    const h = held;
    if (!h || h.at !== "open") return null;
    h.g.updateMatrixWorld(true);
    const r = onScreen(h.g.userData.block);
    return { x: (r.x0 + r.x1) / 2, y: (r.y0 + r.y1) / 2 };
  }
  const clothOf = (i: number): RGB => parts[i]?.look?.cloth ?? [120, 90, 60];
  const linear = (t: number) => t;
  // The page gone in through comes to the middle of the screen on the way.
  const toMiddle = (at: { x: number; y: number }, amount: number) => {
    const d = driftAt(amount);
    return `translate(${(innerWidth / 2 - at.x) * d}px, ${(innerHeight / 2 - at.y) * d}px)`;
  };

  /** The book in hand, open, rushes at the eye. Resolves true once it has. */
  async function dive() {
    const h = held;
    const at = focus();
    if (!h || h.busy || !at) return false;
    h.busy = true;
    els.stage.classList.add("diving");
    if (!reduced) {
      els.stage.style.transformOrigin = `${at.x}px ${at.y}px`;
      await tween(
        DIVE_MS,
        (t) => {
          const u = diveAmount(t);
          const k = breathAt(t) ?? 0.965 * scaleAt(u);
          els.stage.style.transform = `${toMiddle(at, u)} scale(${k})`;
        },
        linear,
      );
    }
    return held === h;
  }

  /** Book `i` open in hand with no taking down, seen from inside its page
   *  and drawing back. `ready` is told where that page is, just before. */
  async function surface(
    i: number,
    ready: (at: { x: number; y: number }, tint: RGB) => void,
  ) {
    const p = parts[i];
    if (held || dead || !p) return false;
    els.host.scrollLeft = Math.max(0, (p.x - worldW / 2) * scale);
    aim();
    sync();
    await standing(p);
    if (held || dead || !parts[i]?.group) return false;
    hover = -1;
    const h = (held = build(i));
    hooks.held(i);
    cover(p);
    h.g.userData.art.visible = true;
    h.away = true;
    stage!.scene.add(h.g);
    pose(h.g, h.open);
    els.stage.classList.add("shown", "diving");
    // The page's words are put there by the component: give it a frame.
    await new Promise((r) =>
      requestAnimationFrame(() => requestAnimationFrame(r)),
    );
    if (held !== h) return false;
    layPages(h);
    els.stage.classList.add("opened");
    h.at = "open";
    const at = focus()!;
    if (!reduced) {
      els.stage.style.transformOrigin = `${at.x}px ${at.y}px`;
      els.stage.style.transform = `${toMiddle(at, 1)} scale(${scaleAt(1)})`;
    }
    ready(at, p.look!.cloth);
    if (!reduced)
      await tween(
        SURFACE_MS,
        (t) => {
          const u = surfaceAmount(t);
          els.stage.style.transform = `${toMiddle(at, u)} scale(${scaleAt(u)})`;
        },
        linear,
      );
    if (held !== h) return true;
    els.stage.style.transform = "";
    els.stage.classList.remove("diving");
    h.busy = false;
    return true;
  }

  // ---- the bee (beeFlight.ts) -----------------------------------------
  const flight = createBeeFlight({
    room,
    host: els.host,
    reduced,
    T,
    top: VIEW_TOP,
    tallest: TALLEST,
    camX: () => camX,
    worldW: () => worldW,
    scale: () => scale,
    cssW: () => cssW,
    scrolled: () => els.host.scrollLeft,
    count: () => parts.length,
    book: (i) => (parts[i]?.group ? parts[i] : null),
    *standing() {
      for (const p of built) if (p.group) yield p;
    },
    hover: () => hover,
    held: () => held?.i ?? -1,
    inRoom: (sx, sy) => {
      const box = view.getBoundingClientRect();
      return {
        x: camX + (sx - box.left - cssW / 2) / scale,
        y: VIEW_TOP - (sy - box.top) / scale,
      };
    },
    rayAt,
    seek: (i) => seek(i),
    redraw: () => (dirty = true),
  });

  /** Slide the shelf along to book `i` and take it down. */
  async function seek(i: number) {
    const p = parts[i];
    if (!p || held || dead) return;
    const max = els.host.scrollWidth - els.host.clientWidth;
    const to = Math.max(0, Math.min(max, (p.x - worldW / 2) * scale));
    if (reduced) {
      els.host.scrollLeft = to;
      aim();
      sync();
    } else {
      if (glide === null) {
        pos = els.host.scrollLeft;
        speed = 0;
        glideTime = performance.now();
      }
      glide = to;
      await new Promise<void>((done) => {
        const wait = () =>
          dead || glide === null ? done() : requestAnimationFrame(wait);
        wait();
      });
    }
    if (dead || held) return;
    await standing(p);
    // A moment for the bee to come down on it.
    await new Promise((r) => setTimeout(r, T(450)));
    if (!dead && !held && parts[i] === p) void open(i);
  }

  // ---- wiring -----------------------------------------------------------
  const onMove = (e: PointerEvent) => {
    if (e.pointerType === "touch" || held) return;
    const onBee = flight.over(e);
    hover = onBee ? -1 : pick(e);
    els.host.style.cursor = hover >= 0 || onBee ? "pointer" : "";
  };
  const onLeave = () => {
    hover = -1;
  };
  const onClick = (e: MouseEvent) => {
    if (flight.over(e)) return flight.pick();
    const i = pick(e);
    if (i >= 0) open(i);
  };
  const onScrim = (e: MouseEvent) => {
    if (!held) return;
    if (dragged) {
      dragged = false; // that was a turn, not a click
      return;
    }
    // A click on the book itself opens it; anywhere else puts it back.
    if (held.at === "hand" && onBook(e)) flip();
    else close();
  };
  const onKey = (e: KeyboardEvent) => {
    if (!held) return;
    if (e.key === "Escape") {
      e.preventDefault();
      close();
    }
    // The page stays where it is under a book in hand.
    if (
      [
        " ",
        "PageDown",
        "PageUp",
        "Home",
        "End",
        "ArrowUp",
        "ArrowDown",
      ].includes(e.key)
    ) {
      const t = e.target as HTMLElement | null;
      if (!t?.closest?.("button")) e.preventDefault();
    }
    if (e.key === "ArrowLeft") step(-1);
    if (e.key === "ArrowRight") step(1);
  };
  const still = (e: Event) => e.preventDefault();
  // A mouse wheel turns the shelf along, as it would turn a page down —
  // moved as the reader's scrolling pages are: a critically damped spring
  // toward where the wheel has asked it to be. Its speed carries over
  // from one notch to the next and dies away at the end: no restart at
  // each notch, no sudden stop. Every wheel goes through it, fine-stepped
  // or coarse.
  const STIFF = 8;
  let glide: number | null = null; // where the shelf has been asked to be
  let pos = 0;
  let speed = 0;
  let glideTime = 0;
  const onWheel = (e: WheelEvent) => {
    if (e.ctrlKey || Math.abs(e.deltaX) >= Math.abs(e.deltaY)) return;
    const max = els.host.scrollWidth - els.host.clientWidth;
    if (max <= 0) return;
    e.preventDefault();
    const by = e.deltaMode === 1 ? e.deltaY * 40 : e.deltaY;
    if (reduced) {
      els.host.scrollLeft += by;
      return;
    }
    if (glide === null) {
      pos = els.host.scrollLeft;
      speed = 0;
      glideTime = performance.now();
    }
    glide = Math.max(0, Math.min(max, (glide ?? pos) + by * 1.6));
  };
  const stopGlide = () => {
    glide = null;
  };
  let waiting = 0;
  const onScroll = () => {
    if (waiting) return;
    waiting = requestAnimationFrame(() => {
      waiting = 0;
      if (glide !== null) return; // the glide stands the eye itself
      aim();
      sync();
    });
  };
  let timer: ReturnType<typeof setTimeout>;
  const watch = new ResizeObserver(() => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      // Not under a book in flight: it is laid out again once that is back.
      if (!held && (els.host.clientWidth !== cssW || tall() !== rowH)) layout();
    }, 120);
  });

  els.host.addEventListener("pointermove", onMove);
  els.host.addEventListener("pointerleave", onLeave);
  els.host.addEventListener("click", onClick);
  els.host.addEventListener("wheel", onWheel, { passive: false });
  els.host.addEventListener("pointerdown", stopGlide);
  els.host.addEventListener("scroll", onScroll, { passive: true });
  els.scrim.addEventListener("pointerdown", grab);
  els.scrim.addEventListener("click", onScrim);
  els.stage.addEventListener("wheel", still, { passive: false });
  els.stage.addEventListener("touchmove", still, { passive: false });
  document.addEventListener("pointermove", turn);
  document.addEventListener("pointerup", drop);
  document.addEventListener("pointercancel", drop);
  document.addEventListener("keydown", onKey);
  addEventListener("resize", onScroll);
  watch.observe(els.host);
  frame();

  function destroy() {
    if (held) putBack();
    dead = true;
    cancelAnimationFrame(raf);
    cancelAnimationFrame(waiting);
    clearTimeout(timer);
    watch.disconnect();
    els.host.removeEventListener("pointermove", onMove);
    els.host.removeEventListener("pointerleave", onLeave);
    els.host.removeEventListener("click", onClick);
    els.host.removeEventListener("wheel", onWheel);
    els.host.removeEventListener("pointerdown", stopGlide);
    els.host.removeEventListener("scroll", onScroll);
    els.scrim.removeEventListener("pointerdown", grab);
    els.scrim.removeEventListener("click", onScrim);
    els.stage.removeEventListener("wheel", still);
    els.stage.removeEventListener("touchmove", still);
    document.removeEventListener("pointermove", turn);
    document.removeEventListener("pointerup", drop);
    document.removeEventListener("pointercancel", drop);
    document.removeEventListener("keydown", onKey);
    removeEventListener("resize", onScroll);
    for (const p of parts) scrap(p);
    view.remove();
    strip.remove();
    for (const o of fixtures.children) (o as THREE.Mesh).geometry.dispose();
    flight.dispose();
    glowTx.dispose();
    gl.dispose();
    gl.forceContextLoss();
    if (stage) {
      stage.gl.dispose();
      stage.gl.forceContextLoss();
      stage.gl.domElement.remove();
    }
    parts = [];
  }

  return {
    setBooks,
    open,
    flip,
    shut,
    close,
    step,
    focus,
    clothOf,
    dive,
    surface,
    beeEnter: flight.enter,
    beeLeave: flight.leave,
    beeHide: flight.hide,
    beePick: flight.pick,
    seek,
    destroy,
  };
}

export type Shelf = NonNullable<ReturnType<typeof createShelf>>;
