// Small 3D machines for the stations: a drum roaster (Torragem) and a vertical form-fill-seal packer (Embalagem).
// Clean product-shot style: brushed steel, dark body, one accent light in the stage colour. The machine works
// (drum turns, cooling arm stirs, bags come out) while `working()` is true; otherwise it stands still and dims.
import * as THREE from 'three';
import { SHEET } from './sheet.js';

const steel = () => new THREE.MeshStandardMaterial({ color: 0xb8c0c6, metalness: 0.85, roughness: 0.28 });
const body = () => new THREE.MeshStandardMaterial({ color: 0x2b2522, metalness: 0.35, roughness: 0.55 });
const dark = () => new THREE.MeshStandardMaterial({ color: 0x15120f, metalness: 0.2, roughness: 0.7 });

function add(parent, geo, mat, x = 0, y = 0, z = 0) { const m = new THREE.Mesh(geo, mat); m.position.set(x, y, z); parent.add(m); return m; }

function roaster(g, accent) {
  const s = steel(), b = body(), d = dark();
  const glow = new THREE.MeshBasicMaterial({ color: accent, transparent: true, opacity: 0.2 });
  add(g, new THREE.BoxGeometry(2.2, 1.2, 1.5), b, 0, 0.6, 0);                                   // cabinet
  add(g, new THREE.BoxGeometry(2.26, 0.06, 1.56), s, 0, 1.2, 0);                                 // top trim
  const drum = add(g, new THREE.CylinderGeometry(0.62, 0.62, 1.5, 48), s, 0, 1.75, 0); drum.rotation.z = Math.PI / 2; // drum (axis along x)
  for (const x of [-0.5, -0.1, 0.3]) { const r = add(g, new THREE.TorusGeometry(0.625, 0.018, 8, 48), d, x, 1.75, 0); r.rotation.y = Math.PI / 2; } // drum bands (turn with the drum)
  const face = add(g, new THREE.CylinderGeometry(0.68, 0.68, 0.08, 48), b, 0.78, 1.75, 0); face.rotation.z = Math.PI / 2; // front plate
  const door = add(g, new THREE.TorusGeometry(0.34, 0.05, 12, 40), s, 0.84, 1.75, 0); door.rotation.y = Math.PI / 2;
  const win = add(g, new THREE.CircleGeometry(0.3, 40), glow, 0.83, 1.75, 0); win.rotation.y = Math.PI / 2; win.userData.keep = true;  // sight glass: glows while roasting
  add(g, new THREE.CylinderGeometry(0.42, 0.12, 0.62, 32), s, -0.15, 2.72, 0);                   // hopper
  add(g, new THREE.CylinderGeometry(0.12, 0.12, 0.2, 20), s, -0.15, 2.33, 0);
  add(g, new THREE.CylinderGeometry(0.11, 0.11, 2.3, 20), s, -0.9, 2.15, -0.45);                 // chimney
  add(g, new THREE.CylinderGeometry(0.15, 0.11, 0.18, 20), s, -0.9, 3.35, -0.45);
  const panel = add(g, new THREE.BoxGeometry(0.06, 0.5, 0.42), d, 1.13, 0.75, 0.4);             // control panel
  { const scr = add(g, new THREE.PlaneGeometry(0.34, 0.22), new THREE.MeshBasicMaterial({ color: accent, transparent: true, opacity: 0.5 }), 1.165, 0.82, 0.4); scr.rotation.y = Math.PI / 2; scr.userData.keep = true; }
  // cooling tray in front, with a stirring arm
  add(g, new THREE.CylinderGeometry(0.7, 0.7, 0.16, 48), s, 1.55, 0.55, -0.15);
  add(g, new THREE.CylinderGeometry(0.64, 0.64, 0.02, 48), new THREE.MeshStandardMaterial({ color: 0x4a2e1a, roughness: 0.9 }), 1.55, 0.635, -0.15); // beans
  add(g, new THREE.CylinderGeometry(0.06, 0.06, 0.55, 12), b, 1.55, 0.25, -0.15);
  const arm = new THREE.Group(); arm.position.set(1.55, 0.7, -0.15); g.add(arm);
  add(arm, new THREE.BoxGeometry(1.2, 0.04, 0.06), s); add(arm, new THREE.CylinderGeometry(0.05, 0.05, 0.25, 12), s, 0, 0.1, 0);
  add(g, new THREE.BoxGeometry(0.5, 0.08, 0.2), s, 1.0, 1.2, -0.1).rotation.z = -0.5;             // chute drum → tray
  const drumSpin = [drum, ...g.children.filter((c) => c.geometry?.type === 'TorusGeometry' && c !== door)];
  return (t, on, dt) => {
    // arm: 1.5 turns per 5 s, glow: 1 pulse per second — so the Pi's baked 5 s loop closes without a jump
    if (on) { for (const m of drumSpin) m.rotation.x += 0.05 * dt; arm.rotation.y += (Math.PI / 100) * dt; }
    glow.opacity += ((on ? 0.55 + Math.sin(t * Math.PI * 2) * 0.15 : 0.12) - glow.opacity) * 0.08;
    void panel;
  };
}

// Embalamento: an SK Coffee stand-up pouch being filled with roasted beans. Beans pour from the doser into the
// open pouch, the level rises behind the front window, the top is sealed, the pouch slides out and an empty one comes in.
function pouch(g, accent) {
  const s = steel();
  const beanMat = new THREE.MeshBasicMaterial({ color: accent });
  const kraft = new THREE.MeshStandardMaterial({ color: 0xa47a4f, roughness: 0.85 });
  // front face artwork (kraft, SK label, window showing the fill level), redrawn while it fills
  const cv = document.createElement('canvas'); cv.width = 512; cv.height = 732; const x = cv.getContext('2d');
  const tex = new THREE.CanvasTexture(cv); tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = 4;
  const front = new THREE.MeshBasicMaterial({ map: tex });
  const dots = Array.from({ length: 260 }, () => [Math.random(), Math.random(), 5 + Math.random() * 5, Math.random() * Math.PI]);
  const WIN = [126, 390, 260, 290]; // x, y, w, h of the window on the canvas
  // line-art front (same drawing language as the station icons): outline label with SK, window, fill level hatched
  const ink = '#' + accent.getHexString();
  function art(level, sealed) {
    x.clearRect(0, 0, 512, 732); x.fillStyle = '#15120f'; x.fillRect(0, 0, 512, 732);
    x.strokeStyle = ink; x.fillStyle = ink; x.lineWidth = 7; x.lineJoin = 'round';
    x.globalAlpha = sealed ? 1 : 0.45; x.beginPath(); x.moveTo(30, 36); x.lineTo(482, 36); x.stroke(); x.globalAlpha = 1;
    x.strokeRect(70, 150, 372, 170);
    x.textAlign = 'center'; x.font = '600 92px Georgia, serif'; x.fillText('SK', 256, 252); x.font = '600 28px Montserrat, Inter, sans-serif'; x.fillText('C O F F E E', 256, 296);
    const [wx, wy, ww, wh] = WIN; x.beginPath(); x.roundRect(wx, wy, ww, wh, 26); x.stroke();
    x.save(); x.beginPath(); x.roundRect(wx, wy, ww, wh, 26); x.clip();
    const top = wy + wh * (1 - level); x.lineWidth = 5; x.globalAlpha = 0.9;
    for (let k = -wh; k < ww + wh; k += 22) { x.beginPath(); x.moveTo(wx + k, wy + wh); x.lineTo(wx + k + wh, wy); x.stroke(); }
    x.globalCompositeOperation = 'destination-over'; x.restore();
    x.fillStyle = '#15120f'; x.fillRect(wx + 4, wy + 4, ww - 8, Math.max(0, top - wy - 4)); x.beginPath(); x.moveTo(wx, top); x.lineTo(wx + ww, top); x.lineWidth = 7; x.stroke();
    x.globalAlpha = 1; tex.needsUpdate = true;
  }
  // pillow-shaped pouch (box with the faces bulged), open at the top while filling
  const W = 1.4, H = 2.0, D = 0.56;
  const geo = new THREE.BoxGeometry(W, H, D, 24, 32, 4), P = geo.attributes.position;
  for (let i = 0; i < P.count; i++) { const nx = P.getX(i) / (W / 2), ny = P.getY(i) / (H / 2); const tz = (1 - nx ** 4 * 0.8) * (ny < -0.7 ? 1 : 1 - ((ny + 0.7) / 1.7) ** 2 * 0.6); P.setZ(i, P.getZ(i) * tz); }
  geo.computeVertexNormals();
  const bag = new THREE.Group(); g.add(bag);
  const body = new THREE.Mesh(geo, [kraft, kraft, kraft, kraft, front, kraft]); body.position.y = H / 2; body.userData.front = front; bag.add(body);
  const mouth = add(bag, new THREE.CircleGeometry(0.5, 32), new THREE.MeshBasicMaterial({ color: 0x0d0907 }), 0, H + 0.002, 0); mouth.userData.keep = true; mouth.rotation.x = -Math.PI / 2; mouth.scale.set(1.15, 0.2, 1);
  const seal = add(bag, new THREE.BoxGeometry(W * 0.98, 0.07, 0.1), new THREE.MeshStandardMaterial({ color: 0x7c5934, roughness: 0.7 }), 0, H - 0.02, 0);
  // doser above: a steel funnel and spout
  add(g, new THREE.CylinderGeometry(0.42, 0.1, 0.5, 32), s, 0, 2.95, 0);
  add(g, new THREE.CylinderGeometry(0.08, 0.08, 0.32, 16), s, 0, 2.55, 0);
  const lamp = add(g, new THREE.TorusGeometry(0.43, 0.025, 8, 40), new THREE.MeshBasicMaterial({ color: accent, transparent: true, opacity: 0.3 }), 0, 3.2, 0); lamp.rotation.x = Math.PI / 2; lamp.userData.keep = true;
  // falling beans (instanced)
  const N = 54, beans = new THREE.InstancedMesh(new THREE.SphereGeometry(0.062, 10, 8), beanMat, N); g.add(beans);
  const bs = Array.from({ length: N }, (_, k) => ({ u: k / N, x: (Math.random() - 0.5) * 0.14, z: (Math.random() - 0.5) * 0.08, r: Math.random() * 6 }));
  const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), e = new THREE.Euler(), sc = new THREE.Vector3(), pos = new THREE.Vector3();
  let cyc = 0, lastLevel = -1, lastSeal = null;
  art(0, false);
  return (t, on, dt) => {
    if (on) cyc = (cyc + dt / 300) % 1;                     // ≈ 5 s per pouch at 60 fps
    const filling = on && cyc >= 0.06 && cyc < 0.66, sealed = cyc >= 0.74, level = Math.max(0, Math.min(cyc, 0.66) - 0.06) / 0.6 * 0.92; // 0–0.08 the empty pouch slides in
    if (Math.abs(level - lastLevel) > 0.015 || sealed !== lastSeal) // ~1 px of the window on screen: redraw + texture upload only then { art(level, sealed); lastLevel = level; lastSeal = sealed; }
    mouth.visible = !sealed; seal.visible = sealed;
    // out to the right after sealing, an empty pouch comes in from the left
    bag.position.x = cyc > 0.9 ? (cyc - 0.9) / 0.1 * 2.3 : cyc > 0 && cyc < 0.06 ? -2.3 * (1 - cyc / 0.06) ** 2 : 0;
    for (let k = 0; k < N; k++) { const b = bs[k]; if (filling) b.u = (b.u + 0.03 * dt) % 1;
      pos.set(b.x * (0.5 + b.u), 2.4 - b.u * 0.45, b.z); q.setFromEuler(e.set(b.r + t * 3, b.r, 0)); sc.set(1, 0.7, 0.8).multiplyScalar(filling ? 1 : 1e-4);
      beans.setMatrixAt(k, m4.compose(pos, q, sc)); }
    beans.instanceMatrix.needsUpdate = true;
    lamp.material.opacity += ((on ? 1 : 0.3) - lamp.material.opacity) * 0.08;
  };
}

// One machine's scene, drawn into `canvas` · kind: 'roasting' | 'packaging' · accent: '#rrggbb'
function machine(canvas, kind, accent) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.outputColorSpace = THREE.SRGBColorSpace; renderer.toneMapping = THREE.NoToneMapping;
  const scene = new THREE.Scene();
  const col = new THREE.Color(accent);
  scene.add(new THREE.HemisphereLight(0xfff1dc, 0x1a1512, 0.7));
  const key = new THREE.DirectionalLight(0xffffff, 2.2); key.position.set(4, 6, 5); scene.add(key);
  const rim = new THREE.DirectionalLight(col, 2.5); rim.position.set(-5, 3, -4); scene.add(rim);
  const g = new THREE.Group(); scene.add(g);
  const step = kind === 'roasting' ? roaster(g, col) : pouch(g, col);
  // line style (like the station icons): every part drawn as its edges in the stage colour over a dark fill that hides
  // the lines behind it; a few parts (sight glass, screen, beans, front artwork) keep their own accent material
  const fillMat = new THREE.MeshBasicMaterial({ color: 0x15120f, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 });
  const lineMat = new THREE.LineBasicMaterial({ color: col, transparent: true, opacity: 0.95 });
  g.traverse((o) => {
    if (!o.isMesh || o.isInstancedMesh || o.userData.keep) return;
    o.add(new THREE.LineSegments(new THREE.EdgesGeometry(o.geometry, 28), lineMat));
    o.material = Array.isArray(o.material) ? o.material.map((m) => (m === o.userData.front ? m : fillMat)) : fillMat;
  });
  // centre the machine and frame it
  const box = new THREE.Box3().setFromObject(g), size = box.getSize(new THREE.Vector3()), mid = box.getCenter(new THREE.Vector3());
  g.position.sub(mid); const pivot = new THREE.Group(); scene.remove(g); pivot.add(g); scene.add(pivot);
  const camera = new THREE.PerspectiveCamera(26, 1, 0.1, 100); const r = Math.max(size.x, size.y, size.z);
  if (kind === 'roasting') { camera.position.set(0, r * 0.6, r * 3.05); camera.lookAt(0, -r * 0.03, 0); }
  else { camera.position.set(0, r * 0.35, r * 2.9); camera.lookAt(0, -r * 0.04, 0); }
  const sway = (t, f = 0.25, k = 1) => (kind === 'roasting' ? -0.6 + Math.sin(t * f) * 0.45 * k : -0.3 + Math.sin(t * f) * 0.3 * k); // slow product-shot sway
  return { renderer, scene, camera, pivot, step, lineMat, sway };
}

// Live machine (PC): canvas = the element to draw into · working(): is the machine busy now
export function mountMachine(canvas, kind, accent, working) {
  const { renderer, scene, camera, pivot, step, lineMat, sway } = machine(canvas, kind, accent);
  function resize() { const w = canvas.clientWidth, h = canvas.clientHeight; if (!w || !h) return; renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 1.5)); renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); }
  new ResizeObserver(resize).observe(canvas); resize();
  let last = performance.now(), dim = 1;
  (function frame(now) {
    const dt = Math.min(3, (now - last) / 16.67), t = now / 1000, on = !!working(); last = now;
    pivot.rotation.y = sway(t);
    step(t, on, dt);
    dim += ((on ? 1 : 0.45) - dim) * 0.05; lineMat.opacity = 0.95 * dim;
    renderer.render(scene, camera); requestAnimationFrame(frame);
  })(last);
}

// The Raspberry Pi plays the machines as flipbooks (sheet.js) rendered here, once, by tools/bake-machines.mjs: the working
// loop (one pouch filled and sealed, 1.5 turns of the cooling arm, the sway there and back) as a grid of px-sized frames
// with the PC's glow drawn in
export function bakeMachine(kind, accent, px) {
  const { renderer, scene, camera, pivot, step, sway } = machine(document.createElement('canvas'), kind, accent);
  const { loop, cols: C } = SHEET, N = C * C, dt = (loop * 60) / N; // step() counts 60 fps frames
  renderer.setPixelRatio(1); renderer.setSize(px, px, false); camera.aspect = 1; camera.updateProjectionMatrix();
  const sheet = document.createElement('canvas'); sheet.width = sheet.height = px * C; const x = sheet.getContext('2d');
  x.filter = `drop-shadow(0 0 .7px ${accent}) drop-shadow(0 0 .7px ${accent}) drop-shadow(0 0 8px ${accent}73)`; // = .st__m on the PC
  for (let k = -N; k < N; k++) { // one loop first, unseen, so the eased glows settle
    const t = (k * loop) / N; pivot.rotation.y = sway(t, (Math.PI * 2) / loop, 0.45); step(t, true, dt);
    if (k >= 0) { renderer.render(scene, camera); x.drawImage(renderer.domElement, (k % C) * px, Math.floor(k / C) * px, px, px); }
  }
  renderer.dispose(); renderer.forceContextLoss();
  return sheet;
}
