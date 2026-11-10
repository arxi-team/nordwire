// Ambient motion layer (one canvas behind the board). Sober palette, one accent, but always alive:
//   · aurora: two warm light fields drifting very slowly
//   · the light running along the process line is CSS now (line.css .ln__track::after): the particles were the heavy part
//   · embers: sparks rising inside the active column (heat of the step that is happening now)
//   · shockwave: a ring when a step is triggered
//   · comet: a light carrying a lot from one column to the next
let ACC = [242, 194, 90]; const target = [242, 194, 90]; // follows the active stage colour

export function createFx(canvas) {
  const g = canvas.getContext('2d');
  let W = 0, H = 0, dpr = 1;
  const st = { nodes: [], cols: [], active: -1, rail: null, t0: performance.now(), activeAt: 0 };
  const embers = [], waves = [], comets = [];
  const rnd = (a, b) => a + Math.random() * (b - a);
  // radial light sprites, rendered once and scaled with drawImage (cheap) instead of a gradient per frame
  const sprites = new Map();
  const sprite = (col0) => {
    const col = col0.split(',').map((v) => Math.round(v / 12) * 12).join(','); // quantised: colour transitions reuse sprites
    if (sprites.has(col)) return sprites.get(col); if (sprites.size > 80) sprites.clear();
    const c = document.createElement('canvas'); c.width = c.height = 256; const x = c.getContext('2d');
    const gr = x.createRadialGradient(128, 128, 0, 128, 128, 128); gr.addColorStop(0, `rgba(${col},1)`); gr.addColorStop(0.45, `rgba(${col},.35)`); gr.addColorStop(1, `rgba(${col},0)`);
    x.fillStyle = gr; x.fillRect(0, 0, 256, 256); sprites.set(col, c); return c;
  };

  function resize() {
    dpr = 1; W = innerWidth; H = innerHeight; // soft light: native resolution is plenty and keeps 60 fps on integrated GPUs
    canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr); canvas.style.width = `${W}px`; canvas.style.height = `${H}px`;
  }
  resize(); addEventListener('resize', resize);

  // ---- public API (positions come from the DOM, in CSS pixels) ----
  const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const api = {
    setColor(h) { const [r, g2, b] = hex(h); target[0] = Math.round(r + (255 - r) * 0.25); target[1] = Math.round(g2 + (255 - g2) * 0.25); target[2] = Math.round(b + (255 - b) * 0.25); },
    layout({ nodes, cols, rail }) { st.nodes = nodes; st.cols = cols; st.rail = rail; },
    setActive(i) { if (i !== st.active) { st.active = i; st.activeAt = performance.now(); } },
    shock(x, y) { waves.push({ x, y, r: 0, life: 1 }); for (let k = 0; k < 26; k++) { const a = rnd(0, Math.PI * 2), v = rnd(1.5, 5.5); embers.push({ x, y, vx: Math.cos(a) * v, vy: Math.sin(a) * v - 1, life: 1, decay: rnd(0.012, 0.025), r: rnd(0.8, 2.2), free: true }); } },
    comet(from, to) { comets.push({ from, to, t: 0, trail: [] }); },
  };

  function spawnEmber() {
    const c = st.cols[st.active]; if (!c) return;
    embers.push({ x: rnd(c.x + 16, c.x + c.w - 16), y: c.y + c.h - rnd(0, 30), vx: rnd(-0.15, 0.15), vy: rnd(-1.4, -0.5), life: 1, decay: rnd(0.004, 0.009), r: rnd(0.6, 1.8), tw: rnd(0, 6) });
  }

  let last = performance.now();
  function frame(now) {
    const t = (now - st.t0) / 1000; const dt = Math.min(4, (now - last) / 16.67); last = now;
    ACC = ACC.map((v, k) => v + (target[k] - v) * Math.min(1, 0.05 * dt)); const A = ACC.map(Math.round).join(',');
    g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, W, H);

    // aurora (two slow warm fields + a cool counter-light, very low alpha)
    g.globalCompositeOperation = 'lighter';
    const blob = (x, y, r, col, a) => { if (a <= 0.002) return; g.globalAlpha = Math.min(1, a); g.drawImage(sprite(col), x - r, y - r, r * 2, r * 2); g.globalAlpha = 1; };
    blob(W * (0.25 + 0.12 * Math.sin(t * 0.05)), H * (0.25 + 0.08 * Math.cos(t * 0.07)), W * 0.42, A, 0.045);
    blob(W * (0.78 + 0.1 * Math.cos(t * 0.04)), H * (0.8 + 0.06 * Math.sin(t * 0.06)), W * 0.38, '200,72,42', 0.03);
    blob(W * (0.6 + 0.15 * Math.sin(t * 0.03)), H * 0.1, W * 0.3, '120,140,200', 0.018);

    // active column glow breathing behind the glass
    const c = st.cols[st.active];
    if (c) { const k = Math.min(1, (now - st.activeAt) / 700); blob(c.x + c.w / 2, c.y + c.h * 0.35, c.w * 0.95, A, (0.07 + 0.025 * Math.sin(t * 2.2)) * k); }

    g.lineCap = 'round';
    if (st.rail) {
      // halo on the active node, pulsing like a heartbeat
      const n = st.nodes[st.active];
      if (n) { const beat = (t * 1.1) % 1, e = 1 - Math.pow(1 - beat, 3); g.strokeStyle = `rgba(${A},${0.5 * (1 - beat)})`; g.lineWidth = 1.2; g.beginPath(); g.arc(n.x, n.y, 6 + e * 26, 0, Math.PI * 2); g.stroke(); blob(n.x, n.y, 40, A, 0.35); }
    }

    // embers rising in the active column
    for (let i = embers.length - 1; i >= 0; i--) {
      const e = embers[i]; e.x += (e.vx + (e.free ? 0 : Math.sin(t * 2 + e.tw) * 0.15)) * dt; e.y += e.vy * dt; if (e.free) { e.vx *= 0.96; e.vy = e.vy * 0.96 - 0.02; }
      e.life -= e.decay * dt; if (e.life <= 0) { embers.splice(i, 1); continue; }
      const a = Math.min(1, e.life * 1.4) * (0.55 + 0.45 * Math.sin(t * 6 + (e.tw || 0)));
      g.fillStyle = `rgba(${A},${a * 0.8})`; g.beginPath(); g.arc(e.x, e.y, e.r, 0, Math.PI * 2); g.fill();
    }

    // shockwaves
    for (let i = waves.length - 1; i >= 0; i--) {
      const w = waves[i]; w.r += (240 - w.r) * 0.06 * dt; w.life -= 0.022 * dt; if (w.life <= 0) { waves.splice(i, 1); continue; }
      g.strokeStyle = `rgba(${A},${0.3 * w.life})`; g.lineWidth = 2 * w.life + 0.5; g.beginPath(); g.arc(w.x, w.y, w.r, 0, Math.PI * 2); g.stroke();
    }

    // comets (lot moving to the next column): eased arc with a fading trail
    for (let i = comets.length - 1; i >= 0; i--) {
      const m = comets[i]; m.t += 0.022 * dt; const u = Math.min(1, m.t), e = u < 0.5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2;
      const x = m.from.x + (m.to.x - m.from.x) * e, y = m.from.y + (m.to.y - m.from.y) * e - Math.sin(e * Math.PI) * 90;
      m.trail.push({ x, y }); if (m.trail.length > 26) m.trail.shift();
      for (let k = 1; k < m.trail.length; k++) { const a = k / m.trail.length; g.strokeStyle = `rgba(${A},${a * 0.8 * (1 - Math.max(0, m.t - 1) * 3)})`; g.lineWidth = a * 4; g.beginPath(); g.moveTo(m.trail[k - 1].x, m.trail[k - 1].y); g.lineTo(m.trail[k].x, m.trail[k].y); g.stroke(); }
      blob(x, y, 26, A, 0.5 * (1 - Math.max(0, m.t - 1) * 3));
      if (m.t > 1.33) comets.splice(i, 1);
    }
    g.globalCompositeOperation = 'source-over';
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
  return api;
}
