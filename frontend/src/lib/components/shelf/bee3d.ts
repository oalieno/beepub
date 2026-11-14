// The bee, in the round. The logo's bee is a box of a bee already, so it
// is built as one — and drawn the way the logo is drawn: flat colour in
// two tones, a dark line round every part — so that on the shelf it is
// still that bee, only with a back to it and a shadow.
//
// One unit is the width of its body.
import * as THREE from "three";
import { RoundedBoxGeometry } from "three/examples/jsm/geometries/RoundedBoxGeometry.js";

const YELLOW = "#edbb4a";
const BROWN = "#5e3d25";
const LINE = "#4a2f1c";
const WING = "#cfdbe1";
const WING_LINE = "#8ea3ad";

export type Face = "glad" | "calm" | "blink" | "startled" | "eager";

function skin(face: Face | null) {
  const c = document.createElement("canvas");
  // As tall to its width as the body is, so the face is not stretched.
  c.width = 256;
  c.height = 294;
  const g = c.getContext("2d")!;
  g.fillStyle = YELLOW;
  g.fillRect(0, 0, 256, 294);
  g.fillStyle = BROWN;
  g.fillRect(0, 160, 256, 32);
  g.fillRect(0, 216, 256, 32);
  g.translate(0, 10);
  if (face) {
    const ink = "#1c130c";
    g.strokeStyle = g.fillStyle = ink;
    g.lineWidth = 10;
    g.lineCap = g.lineJoin = "round";
    const eyes = (draw: (x: number, s: number) => void) => {
      draw(84, 1);
      draw(172, -1);
    };
    const smile = () => {
      g.beginPath();
      g.arc(128, 100, 18, Math.PI * 0.1, Math.PI * 0.9);
      g.stroke();
    };
    if (face === "glad") {
      // The logo's own face — eyes shut tight in a smile: > <
      eyes((x, s) => {
        g.beginPath();
        g.moveTo(x - s * 18, 58);
        g.lineTo(x + s * 16, 76);
        g.lineTo(x - s * 18, 94);
        g.stroke();
      });
      smile();
    } else if (face === "calm" || face === "blink") {
      eyes((x) => {
        g.beginPath();
        if (face === "calm") {
          g.arc(x, 76, 11, 0, Math.PI * 2);
          g.fill();
        } else {
          g.moveTo(x - 14, 78);
          g.lineTo(x + 14, 78);
          g.stroke();
        }
      });
      smile();
    } else if (face === "startled") {
      // Wide eyes, a small round mouth.
      eyes((x) => {
        g.beginPath();
        g.arc(x, 74, 17, 0, Math.PI * 2);
        g.fillStyle = "#fffaf0";
        g.fill();
        g.stroke();
        g.beginPath();
        g.arc(x, 74, 6, 0, Math.PI * 2);
        g.fillStyle = ink;
        g.fill();
      });
      g.beginPath();
      g.arc(128, 116, 9, 0, Math.PI * 2);
      g.stroke();
    } else {
      // Eager: bright eyes, the mouth open in a grin.
      eyes((x) => {
        g.beginPath();
        g.arc(x, 76, 13, 0, Math.PI * 2);
        g.fill();
        g.beginPath();
        g.arc(x + 4, 71, 4, 0, Math.PI * 2);
        g.fillStyle = "#fffaf0";
        g.fill();
        g.fillStyle = ink;
      });
      g.beginPath();
      g.arc(128, 100, 20, 0, Math.PI);
      g.closePath();
      g.fill();
    }
  }
  const tx = new THREE.CanvasTexture(c);
  tx.colorSpace = THREE.SRGBColorSpace;
  return tx;
}

function wingSkin() {
  const c = document.createElement("canvas");
  c.width = c.height = 128;
  const g = c.getContext("2d")!;
  g.fillStyle = WING_LINE;
  g.fillRect(0, 0, 128, 128);
  g.fillStyle = WING;
  g.beginPath();
  g.arc(64, 64, 54, 0, Math.PI * 2);
  g.fill();
  g.strokeStyle = WING_LINE;
  g.lineWidth = 6;
  g.lineCap = "round";
  g.beginPath();
  g.moveTo(22, 64);
  g.lineTo(84, 64);
  g.moveTo(52, 64);
  g.lineTo(78, 40);
  g.moveTo(52, 64);
  g.lineTo(78, 88);
  g.stroke();
  const tx = new THREE.CanvasTexture(c);
  tx.colorSpace = THREE.SRGBColorSpace;
  return tx;
}

export function makeBee() {
  const owned: { dispose(): void }[] = [];
  const keep = <T extends { dispose(): void }>(x: T) => {
    owned.push(x);
    return x;
  };
  // Two tones: lit, and turned from the lamp.
  const steps = keep(
    new THREE.DataTexture(new Uint8Array([196, 255]), 2, 1, THREE.RedFormat),
  );
  steps.minFilter = steps.magFilter = THREE.NearestFilter;
  steps.needsUpdate = true;
  const toon = (o: THREE.MeshToonMaterialParameters) =>
    keep(new THREE.MeshToonMaterial({ gradientMap: steps, ...o }));
  const line = keep(
    new THREE.MeshBasicMaterial({ color: LINE, side: THREE.BackSide }),
  );

  const group = new THREE.Group();
  // Turned a little, as the logo has it: the face and one side in view.
  const body = new THREE.Group();
  body.rotation.set(0.04, 0.42, 0);
  group.add(body);
  const add = (
    geo: THREE.BufferGeometry,
    m: THREE.Material | THREE.Material[],
    parent: THREE.Object3D = body,
    outline = 0,
  ) => {
    const mesh = new THREE.Mesh(keep(geo), m);
    mesh.castShadow = true;
    parent.add(mesh);
    if (outline) {
      // The line round it: the same shape a little larger, seen from
      // inside.
      const hull = new THREE.Mesh(geo, line);
      hull.scale.setScalar(1 + outline);
      mesh.add(hull);
    }
    return mesh;
  };

  // The shelf's lamp is strong and warm: under it the logo's colours
  // would burn to orange. They are held back to come out as drawn.
  const HOLD = 0.8;
  const held = (c: string) => new THREE.Color(c).multiplyScalar(HOLD);
  const side = toon({ map: keep(skin(null)), color: held("#ffffff") });
  // Its faces, each drawn the first time it is worn.
  const faces = new Map<Face, THREE.Texture>();
  const wear = (f: Face) => {
    let tx = faces.get(f);
    if (!tx) faces.set(f, (tx = keep(skin(f))));
    return tx;
  };
  let worn: Face = "glad";
  const front = toon({ map: wear(worn), color: held("#ffffff") });
  const yellow = toon({ color: held(YELLOW) });
  const brown = toon({ color: held(BROWN) });
  // +x, -x, +y, -y, +z (the face), -z
  add(
    new RoundedBoxGeometry(1, 1.15, 0.84, 6, 0.2),
    [side, side, yellow, yellow, front, side],
    body,
    0.07,
  );
  for (const s of [-1, 1]) {
    add(
      new THREE.BoxGeometry(0.17, 0.26, 0.17),
      yellow,
      body,
      0.2,
    ).position.set(s * 0.23, -0.675, 0.02);
    const curve = new THREE.QuadraticBezierCurve3(
      new THREE.Vector3(s * 0.15, 0.535, 0.05),
      new THREE.Vector3(s * 0.12, 0.975, 0.05),
      new THREE.Vector3(s * 0.34, 0.975, 0.1),
    );
    add(new THREE.TubeGeometry(curve, 12, 0.05, 8), brown);
    add(
      new THREE.SphereGeometry(0.105, 14, 12),
      brown,
      body,
      0.14,
    ).position.set(s * 0.34, 0.975, 0.1);
  }
  const pale = keep(
    new THREE.MeshBasicMaterial({
      map: keep(wingSkin()),
      side: THREE.DoubleSide,
    }),
  );
  const wings = [-1, 1].map((s) => {
    const hinge = new THREE.Group();
    hinge.position.set(s * 0.46, 0.25, -0.16);
    body.add(hinge);
    const w = add(new THREE.CircleGeometry(0.36, 28), pale, hinge);
    w.scale.set(1.2 * s, 0.84, 1);
    w.position.x = s * 0.36;
    return hinge;
  });

  return {
    group,
    /** The wings, `open` from at rest (0) to beating (1), at `beat` (-1..1). */
    flap(open: number, beat: number) {
      wings.forEach((h, i) => {
        const s = i === 0 ? -1 : 1;
        h.rotation.z = s * (0.18 + open * beat * 0.55);
      });
    },
    /** Its expression. True if that changed it. */
    face(f: Face) {
      if (f === worn) return false;
      worn = f;
      front.map = wear(f);
      return true;
    },
    dispose() {
      for (const o of owned) o.dispose();
    },
  };
}
