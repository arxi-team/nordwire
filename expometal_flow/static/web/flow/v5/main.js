// v5 · Linha de produção. Same state/inputs as the other versions (shared modules), different view:
// a horizontal line with four stations, read right to left (Ordens de Trabalho on the right, Entregue on the left);
// when a button is pressed a light capsule carries the lot to the next station.
import { STAGES, stageIndex } from '/expometal_flow/static/web/flow/stages.js';
import { createStore } from '/expometal_flow/static/web/flow/store.js';
import { connectInputs } from '/expometal_flow/static/web/flow/inputs.js';
import { mountFunnel } from '/expometal_flow/static/web/flow/funnel.js';
import { mountWorkorders, clock as hms, morph } from '/expometal_flow/static/web/flow/workorders.js';
import { mountSummary } from '/expometal_flow/static/web/flow/summary.js';
import { deliveriesHtml } from '/expometal_flow/static/web/flow/deliveries.js';
import { ICONS } from '/expometal_flow/static/web/flow/icons.js';
import { createFx } from '/expometal_flow/static/web/flow/fx.js';
import { roll } from '/expometal_flow/static/web/flow/view.js';
import { PI } from '/expometal_flow/static/web/flow/device.js';
import { mountSheet } from '/expometal_flow/static/web/flow/sheet.js';

const app = document.getElementById('app');
const $ = (k) => app.querySelector(`[data-el=${k}]`);
if (new URLSearchParams(location.search).has('clean')) app.classList.add('-clean');
app.classList.add('-intro'); setTimeout(() => app.classList.remove('-intro'), 2000);

const X = (i) => 87.5 - i * 25; // station centre (% of width), right to left, aligned with the lists below
// on the Raspberry Pi no canvas runs per frame: line.css draws the ambient light and the active glow once, in CSS
const fx = PI ? { layout() {}, setActive() {}, setColor() {} } : createFx($('fx'));
const stations = STAGES.map((s, i) => {
  const el = document.createElement('div'); el.className = 'st'; el.style.left = `${X(i)}%`; el.style.setProperty('--c', s.color);
  el.innerHTML = `<div class="st__disc"><span class="st__halo"></span>${ICONS[s.id]}<span class="st__count" data-k="count"></span></div><div><div class="st__name">${s.name}</div></div>`;
  $('stations').appendChild(el); return el;
});
// Torragem / Embalagem: a 3D roaster and packer inside the disc (the line icon stays as the fallback without WebGL).
// The Pi plays them as pre-rendered flipbooks (sheet.js); only the PC loads the 3D library and renders them live.
stations.forEach((el, i) => {
  const s = STAGES[i]; if (s.id !== 'roasting' && s.id !== 'packaging') return;
  // the machine works only while Odoo has a work order running there (-busy), never just because the station is in focus
  const disc = el.querySelector('.st__disc'), working = () => el.classList.contains('-busy');
  if (PI) return mountSheet(disc, `/expometal_flow/static/web/flow/machines/${s.id}.webp`, working);
  import('/expometal_flow/static/web/flow/machines.js').then(({ mountMachine }) => {
    const cv = document.createElement('canvas'); cv.className = 'st__m'; cv.setAttribute('aria-hidden', 'true');
    try { disc.appendChild(cv); mountMachine(cv, s.id, s.color, working); el.classList.add('-machine'); }
    catch { cv.remove(); }
  });
});
const lists = STAGES.map((s) => { const el = document.createElement('div'); el.className = 'll'; el.dataset.st = s.id; el.style.setProperty('--c', s.color); $('lists').prepend(el); return el; });
// the line runs only through production (Torragem → Embalamento → Entregue); Ordens de Trabalho is the intake,
// on the other side of a separator, where new work orders fall in from the top
$('track').style.left = '4%'; $('track').style.right = '27%';
const TRACK_R = 73; // right end of the track, % of the stage width
const sep = document.createElement('div'); sep.className = 'ln__sep'; sep.setAttribute('aria-hidden', 'true');
app.appendChild(sep);
// Ordens de Trabalho: a column of cards (no station disc, no list); new ones fall in from the top
const oq = document.createElement('section'); oq.className = 'oq'; oq.style.setProperty('--c', STAGES[0].color); oq.setAttribute('aria-label', STAGES[0].name);
oq.innerHTML = `<header><span class="oq__name">${STAGES[0].name}</span><b class="oq__n">0</b></header>
  <span class="st__in" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></span><div class="oq__list"></div>`;
app.appendChild(oq);
const WAIT_LIMIT_D = 7; // an order waiting over a week without being started is flagged
function renderQueue(items, seen, hot) {
  roll(oq.querySelector('.oq__n'), items.length, !firstRender);
  oq.querySelector('.oq__list').innerHTML = items.slice(0, 10).map((o, k) => `<article class="oq__c${!seen || !seen.has(o.id) ? ' -drop' : ''}${o.id === hot ? ' -hot' : ''}" style="--k:${k}">
    <div class="oq__t"><b>${o.id}</b><span>${o.kg} kg</span></div><div class="oq__p">${o.product}</div><div class="oq__o">${o.origin || ''}${Date.now() - (o.createdAt ?? o.enteredAt) > WAIT_LIMIT_D * 864e5 ? `<em class="oq__w">à espera há ${Math.floor((Date.now() - (o.createdAt ?? o.enteredAt)) / 864e5)} dias</em>` : ''}</div></article>`).join('')
    || '<div class="ll__idle">Sem ordens de trabalho em espera</div>';
}

const pct = (o) => (o.progress == null ? '—' : `${Math.round(o.progress * 100)}%`); // no planned time in Odoo → no %
const right = (o) => (o.stage === 'roasting' || o.stage === 'packaging' ? pct(o) : o.stage === 'delivered' ? (o.picking || `WH/OUT/${o.id.slice(3)}`) : `${o.kg} kg`);

function layoutFx(active) {
  const tr = $('track').getBoundingClientRect();
  const nodes = stations.map((el) => { const r = el.querySelector('.st__disc').getBoundingClientRect(); return { x: r.left + r.width / 2, y: tr.top + 1 }; });
  fx.layout({ rail: { x0: tr.right, x1: tr.left, y: tr.top + 1 }, nodes, cols: stations.map((el) => { const r = el.querySelector('.st__disc').getBoundingClientRect(); return { x: r.left, y: r.top, w: r.width, h: r.height }; }) });
  fx.setActive(active === 0 ? -1 : active); // Ordens has no station disc: no halo/embers there
  // separator between the intake (Ordens) and production: from the top of the stage to the bottom of the lists
  const ar = app.getBoundingClientRect(), sr = $('stations').getBoundingClientRect(), lr = $('lists').getBoundingClientRect(), top = app.querySelector('.fl__top').getBoundingClientRect().bottom + 8;
  const sx = sr.left - ar.left + sr.width * 0.75;
  Object.assign(sep.style, { left: `${sx}px`, top: `${top - ar.top}px`, height: `${lr.bottom - top}px` });
  Object.assign(oq.style, { left: `${sx + 28}px`, width: `${lr.right - ar.left - sx - 28}px`, top: `${top - ar.top}px`, height: `${lr.bottom - top}px` });
}

let seenOrders = null, seenDelivered = null, lastSource;
const dl = () => lists[3];
// Entregue: the pickings Ready to ship (a closed production order feeds them) stay on the board until Odoo validates them,
// then slide off
const readyDone = () => store.state.orders.filter((o) => o.stage === 'delivered');
function drawDone() { dl().innerHTML = deliveriesHtml(readyDone(), seenDelivered, 5, 'À espera da próxima entrega'); } // whole cards only, no half card at the bottom
setInterval(() => {
  const keep = new Set(readyDone().map((o) => o.picking || o.id));
  for (const b of dl().querySelectorAll('.dl__r:not(.-out) [data-dl-close]')) if (!keep.has(b.dataset.dlClose)) {
    const row = b.closest('.dl__r'); row.classList.add('-out'); row.addEventListener('animationend', drawDone, { once: true });
  }
  roll(stations[3].querySelector('[data-k=count]'), keep.size); // the Entregue count is what the list shows
}, 1000);
function travel(fromI, toI, order) {
  const tr = $('track').getBoundingClientRect(), W = app.getBoundingClientRect().width;
  const x0 = fromI < 0 ? tr.right + 40 : (X(fromI) / 100) * W, x1 = (X(toI) / 100) * W;
  const cap = document.createElement('div'); cap.className = 'cap'; cap.style.setProperty('--c', STAGES[toI].color);
  cap.innerHTML = `<b>${order.id}</b>${order.product}`; $('caps').appendChild(cap);
  const w = cap.getBoundingClientRect().width;
  cap.animate([{ transform: `translateX(${x0 - w / 2}px) scale(.8)`, opacity: 0 }, { transform: `translateX(${x0 - w / 2 - 30}px) scale(1)`, opacity: 1, offset: 0.12 },
    { transform: `translateX(${x1 - w / 2}px) scale(1)`, opacity: 1, offset: 0.85 }, { transform: `translateX(${x1 - w / 2}px) scale(.6)`, opacity: 0 }],
  { duration: 1700, easing: 'cubic-bezier(.65,0,.35,1)', fill: 'forwards' }).finished.then(() => cap.remove());
}

let firstRender = true;
function render(state, why) {
  const ai = stageIndex(state.active);
  app.dataset.active = state.active || '';
  if (ai >= 0) { app.style.setProperty('--acc', STAGES[ai].color); fx.setColor(STAGES[ai].color); }
  STAGES.forEach((s, i) => {
    const items = state.orders.filter((o) => o.stage === s.id).sort((a, b) => b.enteredAt - a.enteredAt);
    stations[i].classList.toggle('-on', i === ai);
    // Torragem / Embalagem work (lit, animated) while their work centre has work: a work order started there, producing or
    // paused; with none the machine stands still
    if (s.id === 'roasting' || s.id === 'packaging') stations[i].classList.toggle('-busy', items.length > 0);
    // Entregue: the Ready pickings on the board, the same as its list
    const count = s.id === 'delivered' ? readyDone().length : state.source === 'odoo' && s.id !== 'orders' ? items.filter((o) => o.running).length : items.length; // with Odoo: lots really being produced
    roll(stations[i].querySelector('[data-k=count]'), count, !firstRender);
    const shown = items.slice(0, 4);
    lists[i].classList.toggle('-on', i === ai);
    if (s.id === 'orders') return; // drawn as the card column (renderQueue)
    if (s.id === 'delivered') return; // its own list: completed deliveries pass through and leave (see below)
    lists[i].innerHTML = shown.map((o) => `<div class="ll__row${o.id === state.lastMove && why?.type === 'activate' ? ' -new' : ''}"><b>${o.id}</b><span>${o.product}</span><i data-id="${o.id}">${right(o)}</i></div>`).join('')
      + (items.length > 4 ? `<div class="ll__more">+ ${items.length - 4} lotes</div>` : '') + (items.length ? '' : '<div class="ll__more">Sem lotes nesta etapa</div>');
  });
  // switching data source (demo → Odoo) is not news: reset what counts as "new" and clear the passing deliveries
  if (state.source !== lastSource) { lastSource = state.source; seenOrders = seenDelivered = null; }
  drawDone();
  seenDelivered = new Set(state.orders.filter((o) => o.stage === 'delivered').map((o) => o.id));
  const inOrders = state.orders.filter((o) => o.stage === 'orders').sort((a, b) => (a.createdAt ?? a.enteredAt) - (b.createdAt ?? b.enteredAt)); // oldest first
  oq.classList.toggle('-on', ai === 0);
  renderQueue(inOrders, seenOrders, ai === 0 ? state.lastMove : null);
  seenOrders = new Set(inOrders.map((o) => o.id));
  $('fill').style.setProperty('--fill', ai >= 1 ? `${((TRACK_R - X(ai)) / (TRACK_R - 4)) * 100}%` : '0%');
  if (why?.type === 'activate') {
    const o = state.orders.find((x) => x.id === state.lastMove && x.stage === state.active) || state.orders.find((x) => x.id === state.lastMove);
    if (o && ai > 0) travel(ai - 1, ai, o);
  }
  // KPIs + ticker (same footer as the other versions)
  const n = (st) => state.orders.filter((o) => o.stage === st).length;
  const k = [['Total de ordens', state.orders.length, 'orders'], ['Em torragem', n('roasting'), 'roasting'], ['Em embalagem', n('packaging'), 'packaging'], ['Entregues', n('delivered'), 'delivered']];
  if (!$('kpis').children.length) $('kpis').innerHTML = k.map(([l]) => `<div class="kpi2"><b></b><span>${l}</span></div>`).join('');
  k.forEach(([, v, st], j) => { const d = $('kpis').children[j]; d.classList.toggle('-acc', state.active === st); roll(d.querySelector('b'), v, !firstRender); });
  const e = state.events[0];
  $('ticker').innerHTML = e ? `<span class="-in"><b>${e.text.split(' · ')[0]}</b>${e.text.split(' · ')[1]}</span>` : '<span style="color:var(--creme-4)">À espera do próximo evento</span>';
  setTimeout(() => layoutFx(ai), firstRender ? 1200 : 950);
  firstRender = false;
}

const store = createStore();
store.subscribe((s, why) => {
  if (why?.type === 'tick') { for (const o of s.orders) { const el = app.querySelector(`[data-id="${o.id}"]`); if (el) el.textContent = right(o); } return; }
  render(s, why);
});
mountFunnel(app);
mountSummary(app);
// with Odoo, each phase shows its own work orders (expected vs real time) in place of its list
// each work centre lists only what was pulled in and started there
lists[1].before(mountWorkorders(app, { max: 3, stage: 'roasting', onlyStarted: true, compact: true, single: true }));
lists[2].before(mountWorkorders(app, { max: 3, stage: 'packaging', onlyStarted: true, compact: true, single: true }));
// at each working machine: the work order running now — start (green), stop (red) and its totals, ticking every second
const live = Object.fromEntries(['roasting', 'packaging'].map((id) => { const el = document.createElement('div'); el.className = 'st__live'; stations[STAGES.findIndex((s) => s.id === id)].appendChild(el); return [id, el]; }));
// every station gets the same block below its name (empty where nothing runs), so the discs line up on the track
stations.forEach((st) => { if (!st.querySelector('.st__live')) { const e = document.createElement('div'); e.className = 'st__live'; st.appendChild(e); } });
let liveWos = [];
const hm2 = (ms) => new Date(ms).toLocaleTimeString('pt-PT', { hour: '2-digit', minute: '2-digit', second: '2-digit' }); // time only, to the second
function drawLive() {
  const now = Date.now();
  for (const [id, el] of Object.entries(live)) {
    const ws = liveWos.filter((w) => w.stage === id && w.state === 'progress').sort((a, b) => (b.running - a.running) || (Math.max(...b.sessions.map((q) => q.s)) - Math.max(...a.sessions.map((q) => q.s))));
    const w = ws[0]; if (!w || !w.sessions.length) { el.innerHTML = ''; continue; }
    // at the machine, a stopwatch pair: Start = the latest production session (runs while producing), Stop = the stop running
    // now — an open stop session (a Paragem in Odoo) or the gap since the last session closed
    const q = w.sessions[w.sessions.length - 1], qw = w.sessions.findLast((x) => x.work), stopFrom = q.e ?? (q.work ? null : q.s);
    morph(el, `<b>${w.mo}</b>
      <div class="-ss"><span class="-go">▶ Start: <b class="-tk">${qw ? hms(((qw.e ?? now) - qw.s) / 6e4) : '—'}</b></span><span class="-stop">■ Stop: <b class="-tk">${stopFrom ? hms((now - stopFrom) / 6e4) : '—'}</b></span></div>`);
  }
}
addEventListener('flow:odoo', (e) => { liveWos = e.detail.workorders || []; drawLive(); });
setInterval(drawLive, 1000);
connectInputs(store, app, { onLink: (on) => ($('link').dataset.on = String(on)) });
// the Ordens column and the divider are placed from the measured layout: place them as soon as anything moves (first
// paint, fonts, Odoo data arriving, window size) and keep them hidden until then, so a refresh never shows them out of place
const relayout = () => requestAnimationFrame(() => { layoutFx(stageIndex(store.state.active)); app.classList.add('-laid'); });
new ResizeObserver(relayout).observe(app);
for (const el of [$('stations'), $('lists'), app.querySelector('.fl__top')]) new ResizeObserver(relayout).observe(el);
document.fonts?.ready.then(relayout);
relayout();

const clock = $('clock');
setInterval(() => { const d = new Date(), p = (x) => String(x).padStart(2, '0'); clock.innerHTML = `${p(d.getHours())}<i style="opacity:${d.getSeconds() % 2 ? 0.35 : 1}">:</i>${p(d.getMinutes())}<small>${p(d.getSeconds())}</small><small class="tz">PT</small>`; }, 1000);
let t = performance.now(); setInterval(() => { const now = performance.now(); store.tick(now - t); t = now; }, 1000);
