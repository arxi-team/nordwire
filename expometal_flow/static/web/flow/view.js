// Rendering. Three layers of emphasis when a step is triggered:
//   1. stage moment (takeover): the step's name fills the screen for ~1.5 s, with the lot that just entered
//   2. the active column widens; the others step back
//   3. a hero panel in the active column: animated line illustration, progress ring, live timer
// Cards are keyed by order id and animated with FLIP when they move between columns.
import { STAGES, stageIndex } from './stages.js';
import { createFx } from './fx.js';
import { ICONS } from './icons.js';

const $ = (root, sel) => root.querySelector(sel);
const hhmm = (t) => new Date(t).toLocaleTimeString('pt-PT', { hour: '2-digit', minute: '2-digit' });
const mmss = (ms) => { const s = Math.max(0, Math.floor(ms / 1000)); return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`; };
const ago = (t) => { const s = Math.max(0, Math.round((Date.now() - t) / 1000)); return s < 60 ? `há ${s} s` : `há ${Math.round(s / 60)} min`; };
const STATE_TXT = { orders: 'Planeada', roasting: 'Em torragem', packaging: 'A embalar', delivered: 'Expedido' };
const COL_STATE = { orders: 'Ordem recebida', roasting: 'Torra em curso', packaging: 'Embalamento ativo', delivered: 'Picking expedido' };
const HERO_VERB = { orders: 'Nova ordem de trabalho', roasting: 'Em torragem agora', packaging: 'A embalar agora', delivered: 'Acabou de sair' };
const RING = 2 * Math.PI * 44;

// rolling number: the old value slides up and out, the new one comes from below
export function roll(el, value, animate = true) {
  const v = String(value); if (el.dataset.v === v) return; const first = el.dataset.v == null; el.dataset.v = v;
  if (first || !animate) { el.innerHTML = `<span class="roll"><span>${v}</span></span>`; return; }
  const box = el.querySelector('.roll') || el; const old = box.lastElementChild;
  box.querySelectorAll('.-old').forEach((x) => x.remove());
  if (old) old.className = '-old';
  const n = document.createElement('span'); n.className = '-new'; n.textContent = v; box.appendChild(n);
  setTimeout(() => { if (old?.isConnected) old.remove(); }, 700);
}

export function createView(app) {
  const board = $(app, '[data-el=board]'), rail = $(app, '[data-el=rail]'), railFill = $(app, '[data-el=railFill]'), take = $(app, '[data-el=take]');
  const cols = new Map(), cards = new Map();
  const fx = createFx($(app, '[data-el=fx]'));
  let heroOrder = null, lastState = null;

  STAGES.forEach((s, i) => {
    const col = document.createElement('section'); col.className = 'col'; col.dataset.stage = s.id;
    col.innerHTML = `<span class="col__ring"></span>
      <header class="col__head"><div><div class="col__step">0${i + 1}</div><div class="col__name">${s.name}</div><div class="col__state"></div></div><div class="col__count">0</div></header>
      <div class="hero"><div class="hero__art">${ICONS[s.id]}</div><div class="hero__body"></div></div>
      <div class="col__cards"></div>`;
    col.style.setProperty('--c', s.color); board.appendChild(col); cols.set(s.id, col);
    const node = document.createElement('i'); node.className = 'fl__node'; node.style.setProperty('--c', s.color); node.style.left = `${(i / (STAGES.length - 1)) * 100}%`; rail.appendChild(node); col._node = node;
  });

  function cardHtml(o) {
    const wip = o.stage === 'roasting' || o.stage === 'packaging';
    const bar = wip ? `<div class="card__bar"><i style="width:${Math.round(o.progress * 100)}%"></i></div>` : '';
    const right = wip ? `${Math.round(o.progress * 100)}%` : o.stage === 'delivered' ? `WH/OUT/${o.id.slice(3)}` : `${o.kg} kg`;
    return `<div class="card__top"><span class="card__id">${o.id}</span><span class="card__time">${hhmm(o.enteredAt)}</span></div>
      <div class="card__name">Lote ${o.product}</div>${bar}
      <div class="card__meta"><span class="card__tag">${STATE_TXT[o.stage]}</span><span>${right}</span></div>`;
  }

  // ---------- hero panel of the active step ----------
  function heroHtml(o, stage) {
    if (!o) return `<div class="hero__verb">${HERO_VERB[stage]}</div><div class="hero__lot">Sem lotes nesta etapa</div>`;
    const wip = stage === 'roasting' || stage === 'packaging';
    const metric = wip
      ? `<div class="hero__ring"><svg viewBox="0 0 100 100"><circle cx="50" cy="50" r="44" class="-track"/><circle cx="50" cy="50" r="44" class="-val" style="stroke-dasharray:${RING};stroke-dashoffset:${RING * (1 - o.progress)}"/></svg><b data-k="pct">${Math.round(o.progress * 100)}<small>%</small></b></div>`
      : stage === 'orders' ? `<div class="hero__big"><b>${o.kg}</b><small>kg</small></div>` : `<div class="hero__big -ok"><b>✓</b></div>`;
    const sub = wip ? `<span data-k="timer">${mmss(Date.now() - o.enteredAt)}</span> em curso` : stage === 'orders' ? `Planeada às ${hhmm(o.enteredAt)}` : `WH/OUT/${o.id.slice(3)} · ${hhmm(o.enteredAt)}`;
    return `<div class="hero__verb">${HERO_VERB[stage]}</div><div class="hero__id">${o.id}</div><div class="hero__lot">Lote ${o.product}</div><div class="hero__origin">${o.origin} · ${o.kg} kg</div>
      <div class="hero__row">${metric}<div class="hero__sub">${sub}</div></div>`;
  }
  function pickHero(state) {
    const items = state.orders.filter((o) => o.stage === state.active);
    return items.find((o) => o.id === state.lastMove) || items.sort((a, b) => b.enteredAt - a.enteredAt)[0] || null;
  }
  // light update every second (timer, ring) without rebuilding the panel
  function tickHero(state) {
    const col = cols.get(state.active); if (!col || !heroOrder) return;
    const o = state.orders.find((x) => x.id === heroOrder); if (!o || o.stage !== state.active) return;
    const t = col.querySelector('[data-k=timer]'); if (t) t.textContent = mmss(Date.now() - o.enteredAt);
    const p = col.querySelector('[data-k=pct]'); if (p) p.innerHTML = `${Math.round(o.progress * 100)}<small>%</small>`;
    const v = col.querySelector('.hero__ring .-val'); if (v) v.style.strokeDashoffset = RING * (1 - o.progress);
  }

  // ---------- stage moment ----------
  let takeTimer = 0;
  function stageMoment(stage, order) {
    const i = stageIndex(stage), s = STAGES[i];
    const letters = [...s.short].map((ch, k) => `<span style="--k:${k}">${ch === ' ' ? '&nbsp;' : ch}</span>`).join('');
    take.innerHTML = `<div class="take__in"><div class="take__step">Etapa 0${i + 1} · ${s.name}</div><div class="take__name">${letters}</div>
      ${order ? `<div class="take__lot"><b>${order.id}</b> Lote ${order.product}</div>` : ''}</div><i class="take__blade"></i>`;
    take.classList.remove('-on', '-out'); void take.offsetWidth; take.classList.add('-on');
    clearTimeout(takeTimer); clearTimeout(take._out);
    take._out = setTimeout(() => take.classList.add('-out'), 1300);          // camera push-through
    takeTimer = setTimeout(() => take.classList.remove('-on', '-out'), 1720);
  }

  function render(state, why) {
    lastState = state;
    const before = new Map([...cards].map(([id, el]) => [id, el.getBoundingClientRect()]));
    const alive = new Set(state.orders.map((o) => o.id));
    for (const [id, el] of cards) if (!alive.has(id)) { el.remove(); cards.delete(id); }

    // grid weights: the active step takes the stage
    const ai = stageIndex(state.active);
    board.style.gridTemplateColumns = STAGES.map((_, k) => (ai < 0 ? '1fr' : k === ai ? '1.9fr' : '1fr')).join(' ');

    for (const s of STAGES) {
      const col = cols.get(s.id), list = $(col, '.col__cards');
      const items = state.orders.filter((o) => o.stage === s.id).sort((a, b) => b.enteredAt - a.enteredAt);
      const on = state.active === s.id;
      const hero = on ? pickHero(state) : null;
      const shown = on && hero ? items.filter((o) => o.id !== hero.id) : items; // the hero lot is not repeated as a card
      for (const o of items) if (on && hero && o.id === hero.id) { const el = cards.get(o.id); if (el) { el.remove(); cards.delete(o.id); } }
      shown.forEach((o, idx) => {
        let el = cards.get(o.id);
        if (!el) { el = document.createElement('article'); el.className = 'card'; cards.set(o.id, el); }
        el.dataset.stage = o.stage; el.innerHTML = cardHtml(o); el.style.setProperty('--i', idx);
        if (list.children[idx] !== el) list.insertBefore(el, list.children[idx] || null);
      });
      [...list.querySelectorAll('.col__empty')].forEach((e) => e.remove());
      if (!items.length) list.insertAdjacentHTML('beforeend', '<div class="col__empty">Sem lotes nesta etapa</div>');
      const cnt = $(col, '.col__count'); if (cnt.dataset.v !== String(items.length)) roll(cnt, items.length, why !== 'init');
      col.classList.toggle('-on', on);
      $(col, '.col__state').textContent = on ? COL_STATE[s.id] : '';
      if (on && (why?.type === 'activate' || why?.type === 'data' || why === 'init' || heroOrder !== hero?.id)) {
        heroOrder = hero?.id || null; const body = $(col, '.hero__body'); body.innerHTML = heroHtml(hero, s.id);
        const heroEl = col.querySelector('.hero'); heroEl.classList.remove('-in');
        const ring = heroEl.querySelector('.hero__ring .-val'); const target = ring?.style.strokeDashoffset;
        if (ring) { ring.style.transition = 'none'; ring.style.strokeDashoffset = RING; }
        clearTimeout(heroEl._t);
        heroEl._t = setTimeout(() => {
          void heroEl.offsetWidth; heroEl.classList.add('-in');
          if (ring) { void ring.getBoundingClientRect(); ring.style.transition = 'stroke-dashoffset 1200ms var(--e-spring)'; ring.style.strokeDashoffset = target; setTimeout(() => { ring.style.transition = ''; }, 1300); }
        }, why?.type === 'activate' ? 1250 : 60);
      }
    }

    // FLIP for cards that moved
    for (const [id, el] of cards) {
      const a = before.get(id), b = el.getBoundingClientRect();
      if (!a) continue;
      const dx = a.left - b.left, dy = a.top - b.top; if (!dx && !dy) continue;
      el.style.transition = 'none'; el.style.transform = `translate(${dx}px, ${dy}px)`;
      requestAnimationFrame(() => { el.style.transition = ''; el.style.transform = ''; });
    }

    app.dataset.active = state.active || '';
    if (ai >= 0) { app.style.setProperty('--acc', STAGES[ai].color); fx.setColor(STAGES[ai].color); }
    if (why?.type === 'activate') {
      const moved = state.orders.find((o) => o.id === state.lastMove);
      stageMoment(state.active, moved);
      // after the moment: the light carries the lot from the previous step into the hero panel
      const from = before.get(state.lastMove);
      setTimeout(() => {
        layoutFx();
        const h = cols.get(state.active)?.querySelector('.hero__art')?.getBoundingClientRect();
        if (h) fx.comet(from ? { x: from.left + from.width / 2, y: from.top + from.height / 2 } : { x: h.left + h.width / 2, y: h.top - 140 }, { x: h.left + h.width / 2, y: h.top + h.height / 2 });
      }, 1250);
    }
    railFill.style.setProperty('--dot', ai >= 0 ? '1' : '0');
    STAGES.forEach((s, k) => { cols.get(s.id)._node.className = `fl__node${k < ai ? ' -done' : ''}${k === ai ? ' -on' : ''}`; });
    fx.setActive(ai);
    setTimeout(layoutFx, 950); // after the columns finished resizing
    renderKpis(state); renderTicker(state);
    $(app, '[data-el=source]').textContent = state.source === 'odoo' ? 'Odoo · ao vivo' : 'Dados simulados';
  }

  // rail nodes follow the column centres; the particle layer gets the same geometry
  function layoutFx() {
    const rr = rail.getBoundingClientRect(); const ai = stageIndex(lastState?.active);
    const nodes = STAGES.map((s) => { const r = cols.get(s.id).getBoundingClientRect(); return { x: r.left + r.width / 2, y: rr.top + rr.height / 2 }; });
    STAGES.forEach((s, k) => { cols.get(s.id)._node.style.left = `${nodes[k].x - rr.left}px`; });
    railFill.style.setProperty('--fill', ai >= 0 ? `${nodes[ai].x - rr.left}px` : '0px');
    fx.layout({ rail: { x0: rr.left, x1: rr.right, y: rr.top + rr.height / 2 }, nodes, cols: STAGES.map((s) => { const r = cols.get(s.id).getBoundingClientRect(); return { x: r.left, y: r.top, w: r.width, h: r.height }; }) });
  }

  function renderKpis(state) {
    const n = (st) => state.orders.filter((o) => o.stage === st).length;
    const k = [['Total de ordens', state.orders.length, 'orders'], ['Em torragem', n('roasting'), 'roasting'], ['Em embalagem', n('packaging'), 'packaging'], ['Entregues', n('delivered'), 'delivered']];
    const box = $(app, '[data-el=kpis]');
    if (!box.children.length) box.innerHTML = k.map(([l]) => `<div class="kpi2"><b></b><span>${l}</span></div>`).join('');
    k.forEach(([, v, st], j) => { const d = box.children[j]; d.classList.toggle('-acc', state.active === st); roll(d.querySelector('b'), v); });
  }
  let lastTicker = '';
  function renderTicker(state) {
    const e = state.events[0]; const el = $(app, '[data-el=ticker]');
    if (!e) { el.innerHTML = '<span style="color:var(--creme-4)">À espera do próximo evento</span>'; return; }
    if (`${e.at}` !== lastTicker) { lastTicker = `${e.at}`; el.innerHTML = `<span class="-in"><b>${e.text.split(' · ')[0]}</b>${e.text.split(' · ')[1]}<i data-ago>${ago(e.at)}</i></span>`; }
    else { const a = el.querySelector('[data-ago]'); if (a) a.textContent = ago(e.at); }
  }

  addEventListener('resize', () => { if (lastState) { render(lastState, 'resize'); layoutFx(); } });
  return {
    render(s, why) { if (why?.type === 'tick') { tickHero(s); for (const [id, el] of cards) { const o = s.orders.find((x) => x.id === id); if (o && (o.stage === 'roasting' || o.stage === 'packaging')) { const i = el.querySelector('.card__bar i'); if (i) i.style.width = `${Math.round(o.progress * 100)}%`; const r = el.querySelector('.card__meta span:last-child'); if (r) r.textContent = `${Math.round(o.progress * 100)}%`; } } renderTicker(s); return; } render(s, why); },
    tickHero: () => lastState && tickHero(lastState),
    intro() { const box = $(app, '[data-el=kpis]'); [...box.querySelectorAll('b')].forEach((b) => { const v = b.dataset.v; roll(b, 0, false); setTimeout(() => roll(b, v), 1150); }); },
  };
}
