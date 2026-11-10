// Input sources. Each one only calls store.activate(stage). Adding the real hardware later is just
// another source: the Nordwire button module POSTs /api/flow/press {stage} and the screens pick the
// resulting "flow" moment up from /api/flow/data (already wired below).
import { STAGES } from './stages.js';
import { initialOrders } from './mock.js';

export function connectInputs(store, app, { onLink } = {}) {
  // 1) on-screen test buttons (the "simulated physical buttons")
  const dock = app.querySelector('[data-el=dock]');
  dock.innerHTML = STAGES.map((s) => `<button type="button" data-stage="${s.id}" style="--c:${s.color}" title="Botão ${s.button} (tecla ${s.key})"><kbd>${s.key}</kbd>${s.short}</button>`).join('') + '<button type="button" data-auto>Auto</button>';
  dock.addEventListener('click', (e) => { const b = e.target.closest('button'); if (!b) return; if (b.dataset.auto != null) return toggleAuto(); press(b.dataset.stage, 'ecrã'); });

  // 2) keyboard: 1–4 = buttons · A = auto demo · H = hide test buttons · Esc = clear focus
  addEventListener('keydown', (e) => {
    const s = STAGES.find((x) => x.key === e.key); if (s) return press(s.id, 'teclado');
    if (e.key === 'a' || e.key === 'A') toggleAuto();
    if (e.key === 'h' || e.key === 'H') app.classList.toggle('-clean');
    if (e.key === 'Escape') store.clearFocus();
  });

  // 3) physical buttons and Odoo data through the stand server (/api/flow/data). Flow moment: { stage, source, focus }
  // Inside Odoo (the expometal_flow addon) there is no SSE server: the page sets window.FLOW_CFG = { data, poll } and
  // the snapshot is polled from Odoo; Odoo changes become flow events here, by comparing two snapshots.
  const CFG = window.FLOW_CFG || null;
  const applyOdoo = (d) => { if (!d.orders) return; store.replaceOrders(d.orders, 'odoo', d.funnel); dispatchEvent(new CustomEvent('flow:odoo', { detail: d })); };
  let prevSets = null;
  const changes = (d) => {
    // a work order counts while it produces (an open work session): starting and resuming are moments, like on the stand server
    const o = d.orders, set = (st, k) => new Set(o.filter((x) => x.stage === st && (k !== 'woId' || x.running)).map((x) => x[k]));
    const now = { orders: set('orders', 'odooId'), roasting: set('roasting', 'woId'), packaging: set('packaging', 'woId'), delivered: set('delivered', 'odooId') };
    const ev = [];
    if (prevSets) for (const st of Object.keys(now)) {
      const id = [...now[st]].find((x) => !prevSets[st].has(x)); if (id == null) continue;
      const c = o.find((x) => x.stage === st && (st === 'roasting' || st === 'packaging' ? x.woId === id : x.odooId === id)); if (c) ev.push({ stage: st, focus: c.focusKey ?? c.id });
    }
    prevSets = now; return ev;
  };
  if (CFG) {
    // the cards are redrawn only when Odoo data changed; a delivery validated since the last ask opens its order's summary
    let last = '', shipped = null;
    const poll = () => fetch(CFG.data, { credentials: 'same-origin', cache: 'no-store' }).then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((d) => {
        onLink?.(true);
        const key = JSON.stringify([d.orders, d.workorders, d.funnel]); if (key !== last) { last = key; applyOdoo(d); for (const e of changes(d)) press(e.stage, 'Odoo', true, e.focus); }
        const ids = (d.shipped || []).map((p) => p.id), fresh = shipped && ids.find((id) => !shipped.has(id)); shipped = new Set(ids);
        if (fresh && CFG.summary) fetch(`${CFG.summary}?picking=${fresh}`, { credentials: 'same-origin' }).then((r) => r.json()).then((x) => x && dispatchEvent(new CustomEvent('flow:summary', { detail: x }))).catch(() => {});
      })
      .catch(() => onLink?.(false)).finally(() => setTimeout(poll, CFG.poll || 5000));
    poll();
  }
  // Stand server: the page loads once and only runs the motion; the data comes from /api/flow/data, asked every few seconds
  // (?poll=ms, default 3 s). 204 = nothing new, the page does no work; otherwise the Odoo snapshot when it changed
  // (replaces the cards on every screen) and the moments since the last ask: a step that happened in Odoo or a physical
  // button (the board reacts) and a finished order's summary (summary.js). The first answer only sets where we are:
  // moments from before the page opened are not replayed.
  const POLL = Number(new URLSearchParams(location.search).get('poll')) || 3000;
  // a new build on the server (a deploy) reloads the page once, a few seconds later; data alone never reloads it
  let ver = '', seq = -1, build = '';
  const pull = () => fetch(`/api/flow/data?v=${ver}&since=${seq}`, { cache: 'no-store' })
    .then((r) => {
      if (!r.ok) throw r.status; onLink?.(true);
      const b = r.headers.get('X-Flow-Build'); if (b && b !== build) { if (build) setTimeout(() => location.reload(), 1000 + Math.random() * 3000); build = b; }
      return r.status === 204 ? null : r.json();
    })
    .then((d) => {
      if (!d) return;
      if (d.odoo && d.v !== ver) applyOdoo(d.odoo);
      if (seq >= 0) for (const e of d.events) {
        if (e.type === 'summary' && e.data) dispatchEvent(new CustomEvent('flow:summary', { detail: e.data }));
        if (e.type === 'flow' && e.data?.stage) press(e.data.stage, e.data.source || 'botão', true, e.data.focus);
      }
      ver = d.v; seq = d.seq;
    })
    .catch(() => onLink?.(false))
    .finally(() => setTimeout(pull, POLL));
  if (!CFG) pull();

  // 4) attract mode: after 25 s without presses, the board runs the flow by itself, one step every 6 s
  let lastPress = Date.now() - 22000, auto = new URLSearchParams(location.search).get('auto') !== '0', step = 0;
  // Odoo mode: the board follows Odoo only. No attract demo, no simulated orders, and screen/keyboard presses do
  // nothing; the only flow events are the changes the server (or the poll below) detects in Odoo.
  let odooMode = !!CFG;
  // one badge while connecting to Odoo (never "Dados simulados" on an Odoo screen); funnel.js switches it to "ao vivo"
  const badgeOdoo = () => { const src = app.querySelector('[data-el=source]'), l = app.querySelector('[data-el=link]'); if (src) src.style.display = 'none'; if (l && store.state.source !== 'odoo') l.innerHTML = '<b></b>Odoo · a ligar'; };
  const enterOdoo = () => { odooMode = true; setAuto(false); dock.hidden = true; badgeOdoo(); if (store.state.source !== 'odoo') store.replaceOrders([], 'odoo'); };
  const demo = () => { const src = app.querySelector('[data-el=source]'); if (src) src.textContent = 'Dados simulados'; store.replaceOrders(initialOrders(), 'simulado'); };
  if (CFG) queueMicrotask(enterOdoo);
  else fetch('/api/flow/health').then((r) => r.json()).then((h) => { if (h.configured) enterOdoo(); else demo(); }).catch(demo);
  function press(stage, origin, external = false, focus = null) {
    // Odoo mode: a touch/key only looks at a stage (camera + card); it never pretends something happened
    if (odooMode && !external) { lastPress = Date.now(); store.activate(stage, { origin, view: true }); updateDock(stage); return; }
    // with Odoo connected, the screen/keyboard buttons behave like the physical ones: they go through the server,
    // which acts on Odoo and sends the 'flow' event back to every screen
    lastPress = Date.now(); store.activate(stage, { origin, focus });
    if (external && auto) setAuto(false); // a real button takes over from the demo
    updateDock(stage);
  }
  function setAuto(on) { auto = on; dock.querySelector('[data-auto]').setAttribute('aria-pressed', String(on)); }
  function toggleAuto() { setAuto(!auto); lastPress = 0; }
  function updateDock(stage) { dock.querySelectorAll('[data-stage]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.stage === stage))); }
  setAuto(auto);
  setInterval(() => {
    if (!auto || odooMode || Date.now() - lastPress < 25000) return;
    const s = STAGES[step++ % STAGES.length]; store.activate(s.id, { origin: 'auto' }); updateDock(s.id); lastPress = Date.now() - 16000; // next in ~9 s (stage moment + time to read)
  }, 1000);

  // public hook for integrations/tests: window.flow.press('roasting')
  window.flow = { press: (stage) => press(stage, 'api'), store };
}
