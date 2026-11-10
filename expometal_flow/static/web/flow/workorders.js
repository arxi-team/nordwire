// Work-order tracking, live from Odoo only: every work order at Torragem / Embalagem that is in progress, to do,
// blocked or finished in the last 24 h — expected vs real time, state, operator. Several can run at once.
// Real time = Odoo `duration` (closed sessions) + time since the open session started; it ticks every second here.
// Hidden while there is no Odoo data (no simulated work orders).
import { STAGES } from './stages.js';
const C = Object.fromEntries(STAGES.map((s) => [s.id, s.color]));
const STATE = { progress: 'A produzir', ready: 'Por fazer', blocked: 'Bloqueada', done: 'Concluída' };

const p2 = (n) => String(Math.floor(n)).padStart(2, '0');
// running clock to the second: h:mm:ss, then "N d HH:MM:SS"
export function clock(min) { const s = Math.max(0, min * 60); if (s >= 86400) return `${Math.floor(s / 86400)} d ${p2((s % 86400) / 3600)}:${p2((s % 3600) / 60)}:${p2(s % 60)}`; return `${Math.floor(s / 3600)}:${p2((s % 3600) / 60)}:${p2(s % 60)}`; }
// planned duration: "43 min" / "1 h 01" / "10 d 05 h"
export function plan(min) { const m = Math.round(min); return m < 60 ? `${m} min` : m < 1440 ? `${Math.floor(m / 60)} h ${p2(m % 60)}` : `${Math.floor(m / 1440)} d ${p2((m % 1440) / 60)} h`; }
export const realMin = (w, now = Date.now()) => w.done + (w.since ? (now - w.since) / 6e4 : 0);
// timesheet of a work order (Odoo sessions: start/stop/start…): work and stopped minutes, open time since the 1st start, cost
export function sheet(w, now = Date.now()) {
  // a closed session uses Odoo's duration (d); the open one counts until now. Work time is the union of the work sessions
  // (two operators in parallel count once as time); the cost adds every session × its €/h, as Odoo does.
  const ss = w.sessions || [], dur = (q) => (q.e != null && q.d != null ? q.d : Math.max(0, ((q.e ?? now) - q.s) / 6e4));
  let work = 0, ce = -Infinity;
  for (const [a, b] of ss.filter((q) => q.work).map((q) => [q.s, q.e ?? now]).sort((x, y) => x[0] - y[0])) { if (b <= ce) continue; work += (b - Math.max(a, ce)) / 6e4; ce = b; }
  const stop = ss.filter((q) => !q.work).reduce((a, q) => a + dur(q), 0);
  const first = ss.length ? Math.min(...ss.map((q) => q.s)) : null, end = w.state === 'done' ? Math.max(...ss.map((q) => q.e ?? now)) : now;
  return { work, stop, first, end, open: first ? (end - first) / 6e4 : 0, cost: ss.reduce((a, q) => a + (dur(q) / 60) * (q.rate || 0), 0) };
}
const esc = (x) => String(x ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
// Odoo housekeeping, shown on the screen: a session open longer than a shift, or a started work order stopped for over a
// day, is almost always a forgotten Pausa/Concluir in Odoo — it inflates times and costs until someone closes it
export const OPEN_LIMIT_H = 12, PAUSE_LIMIT_H = 24;
export function stale(w, now = Date.now()) {
  const ss = w.sessions || [], open = ss.filter((q) => q.e == null);
  if (open.length) { const s0 = Math.min(...open.map((q) => q.s)); if (now - s0 > OPEN_LIMIT_H * 36e5) return { kind: 'open', since: s0, text: `Sessão aberta há ${plan((now - s0) / 6e4)} · fechar no Odoo` }; }
  else if (w.state === 'progress' && ss.length) { const e0 = Math.max(...ss.map((q) => q.e)); if (now - e0 > PAUSE_LIMIT_H * 36e5) return { kind: 'pause', since: e0, text: `Parada há ${plan((now - e0) / 6e4)} · retomar ou concluir no Odoo` }; }
  return null;
}
// quantity (and kg when the unit is not kg) and the lot being produced
const nfq = (n) => Number(n || 0).toLocaleString('pt-PT', { maximumFractionDigits: 1 });
const qtyLot = (w) => `<div class="wo__q"><span><small>Quantidade</small>${nfq(w.qty)} ${w.uom || ''}${w.uom === 'un' && w.kg ? ` · ${nfq(w.kg)} kg` : ''}</span><span><small>Lote</small>${w.lot || 'por atribuir'}</span></div>`;
// progress bar of a work order: what its time went to, from the first Start to now (or to the end when finished).
// Setup = stop sessions whose Odoo reason is setup / batch change / cleaning; Work = productive sessions;
// Paragem = any other stop reason and the gaps with no session at all (the work order was paused).
const SETUP = /setup|ajust|mudan|limpeza/i;
export function phases(w, now = Date.now()) {
  const ss = [...(w.sessions || [])].sort((a, b) => a.s - b.s); if (!ss.length) return null;
  const end = w.state === 'done' ? Math.max(...ss.map((q) => q.e ?? now)) : now, segs = [];
  let t = ss[0].s;
  for (const q of ss) {
    if (q.s > t) segs.push({ k: 'stop', a: t, b: q.s });
    const b = q.e ?? now, a = Math.max(q.s, t); if (b > a) segs.push({ k: q.work ? 'work' : SETUP.test(q.loss || '') ? 'setup' : 'stop', a, b });
    t = Math.max(t, b);
  }
  if (end > t) segs.push({ k: 'stop', a: t, b: end });
  for (let i = segs.length - 1; i > 0; i--) if (segs[i].k === segs[i - 1].k) { segs[i - 1].b = segs[i].b; segs.splice(i, 1); } // one block per period
  const tot = { setup: 0, work: 0, stop: 0 }; for (const g of segs) tot[g.k] += (g.b - g.a) / 6e4;
  return { segs, tot, a: ss[0].s, b: end };
}
// bar widths per phase (setup · work · stop); any phase with time keeps at least MIN_PC so a short stop is still seen
const MIN_PC = 7;
export function barParts(tot) {
  const ks = ['setup', 'work', 'stop'].filter((k) => tot[k] > 0), sum = ks.reduce((a, k) => a + tot[k], 0); if (!sum) return [];
  let pcs = ks.map((k) => Math.max(MIN_PC, (tot[k] / sum) * 100));
  const over = pcs.reduce((a, x) => a + x, 0) - 100, big = pcs.indexOf(Math.max(...pcs)); pcs[big] -= over; // the largest absorbs the floors
  return ks.map((k, i) => [k, pcs[i]]);
}
const eur = (v) => `${v.toLocaleString('pt-PT', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`;

// Update el to match html touching only what changed: rebuilding every second re-laid out the panel (a hitch each second
// on the stand's Raspberry Pi) and restarted its pulses. Same structure → text and attributes patched in place; else replaced.
export function morph(el, html) {
  const t = document.createElement('template'); t.innerHTML = html;
  const same = (a, b) => a.length === b.length && a.every((x, k) => x.nodeName === b[k].nodeName);
  const walk = (a, b) => {
    if (a.nodeType !== 1) { if (a.nodeValue !== b.nodeValue) a.nodeValue = b.nodeValue; return; }
    for (const { name, value } of b.attributes) if (a.getAttribute(name) !== value) a.setAttribute(name, value);
    for (const { name } of [...a.attributes]) if (!b.hasAttribute(name)) a.removeAttribute(name);
    const ka = [...a.childNodes], kb = [...b.childNodes];
    if (same(ka, kb)) ka.forEach((x, k) => walk(x, kb[k])); else a.replaceChildren(...kb);
  };
  const ka = [...el.childNodes], kb = [...t.content.childNodes];
  if (same(ka, kb)) ka.forEach((x, k) => walk(x, kb[k])); else el.replaceChildren(...kb);
}

// stage: 'roasting' | 'packaging' shows only that work centre's work orders (one panel per phase)
export function mountWorkorders(app, { max = 8, float = false, stage = null, onlyStarted = false, compact = false, single = false } = {}) {
  const css = document.createElement('style');
  // each row: ref + product / state pill + operation · operator + real vs planned / thin progress line (red when over plan)
  css.textContent = `.wo{display:none;font-family:var(--font-ui);background:color-mix(in srgb,var(--nw-navy,#142137) 86%,transparent);border:1px solid color-mix(in srgb,#4a6a9a 30%,transparent);border-radius:16px;padding:calc(var(--u)*.85) calc(var(--u)*1.1) calc(var(--u)*.6);backdrop-filter:blur(10px)}
  .fl.-wo .wo{display:block}.wo.-float{position:absolute;z-index:4;left:calc(var(--u)*3);top:calc(var(--u)*10.5);width:calc(var(--u)*30)}
  .wo__h{display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between;gap:.3em 1em;padding-bottom:calc(var(--u)*.5);font-size:calc(var(--u)*.66);color:var(--creme-3);white-space:nowrap}
  .wo__h b{font-weight:600;letter-spacing:.16em;text-transform:uppercase;color:var(--creme-2)}
  .wo__h i{font-style:normal;font-family:var(--font-mono);color:var(--creme);margin-right:.25em}.wo__h em{font-style:normal;color:var(--creme-4);margin:0 .45em}
  .wo__r{position:relative;display:grid;grid-template-columns:1fr auto;gap:calc(var(--u)*.15) calc(var(--u)*.8);align-items:baseline;padding:calc(var(--u)*.45) 0 calc(var(--u)*.55);border-top:1px solid rgba(243,237,227,.08)}
  .wo__a{grid-column:1/-1;min-width:0;font-size:calc(var(--u)*.88);color:var(--creme);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .wo__a b{font-family:var(--font-mono);font-weight:500;color:var(--c);margin-right:.6em}
  .wo__s{margin-right:.7em;font-size:calc(var(--u)*.56);font-weight:600;letter-spacing:.12em;text-transform:uppercase;padding:.3em .7em;border-radius:999px;color:var(--c);background:color-mix(in srgb,var(--c) 16%,transparent)}
  .wo__x{min-width:0;overflow:hidden;text-overflow:ellipsis}.wo__s{flex:none;display:inline-flex;align-items:center;gap:.6em;line-height:1}
  .wo__r.-ready .wo__s,.wo__r.-blocked .wo__s{color:var(--creme-3);background:rgba(243,237,227,.07)}
  .wo__o{min-width:0;display:flex;align-items:center;font-size:calc(var(--u)*.68);color:var(--creme-3);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .wo__t{justify-self:end;font-family:var(--font-mono);font-size:calc(var(--u)*.92);color:var(--creme);font-variant-numeric:tabular-nums;white-space:nowrap}
  .wo__t small{font-size:.72em;color:var(--creme-3);margin-left:.3em}.wo__r:not(.-progress):not(.-done) .wo__t{font-size:calc(var(--u)*.72);color:var(--creme-3)}
  .wo__p{position:absolute;left:0;right:0;bottom:0;height:2px;background:rgba(243,237,227,.06)}.wo__p i{display:block;height:100%;background:var(--c)}
  .wo__r.-late .wo__t{color:#FF8A8E}.wo__r.-late .wo__p i{background:#E5484D}
  .wo__g{padding:calc(var(--u)*.55) 0 calc(var(--u)*.3);font-size:calc(var(--u)*.56);font-weight:600;letter-spacing:.16em;text-transform:uppercase;color:var(--creme-4)}
  .wo__g.-now{color:var(--creme-2)}.wo__g.-now::before{content:'';display:inline-block;width:7px;height:7px;margin-right:.6em;border-radius:50%;background:#E5484D;vertical-align:1px;animation:wo-live 1.4s ease-in-out infinite}
  @keyframes wo-live{50%{opacity:.25}}
  .wo__r.-progress{border:1px solid rgba(243,237,227,.09);margin:0 0 calc(var(--u)*.45);padding:calc(var(--u)*.6) calc(var(--u)*.75);border-radius:12px;background:rgba(243,237,227,.045);box-shadow:0 10px 24px -14px rgba(0,0,0,.7)}
  .wo__r.-progress .wo__a{font-size:calc(var(--u)*.98)}.wo__r.-progress .wo__s::before{content:'';width:.55em;height:.55em;border-radius:50%;background:currentColor}
  .wo__r.-progress .wo__p{display:none}
  .wo__r:not(.-progress){opacity:.62}
  .wo__g.-st{display:flex;align-items:baseline;gap:.6em;padding-top:calc(var(--u)*.8);color:var(--c);font-size:calc(var(--u)*.62)}
  .wo__g.-st i{font-style:normal;font-family:var(--font-mono)}.wo__g.-st span{margin-left:auto;color:var(--creme-3);letter-spacing:.08em;text-transform:none;font-weight:400}
  .wo__tl{grid-column:1/-1;position:relative;height:6px;margin-top:calc(var(--u)*.3);border-radius:3px;background:rgba(243,237,227,.06);overflow:hidden}
  .wo__tl i{position:absolute;top:0;bottom:0;background:var(--c);border-radius:2px}
  .wo__tl i.-stop{background:repeating-linear-gradient(135deg,rgba(243,237,227,.45) 0 3px,rgba(243,237,227,.12) 3px 6px)}
  .wo__ts{grid-column:1/-1;list-style:none;margin:calc(var(--u)*.35) 0 0;padding:0;display:grid;gap:2px}
  .wo__ts li{display:grid;grid-template-columns:auto 1fr auto;gap:.8em;align-items:baseline;font-size:calc(var(--u)*.66);color:var(--creme-2)}
  .wo__ts li span{font-family:var(--font-mono);color:var(--creme-3)}.wo__ts li em{font-style:normal;color:var(--c)}.wo__ts li b{font-family:var(--font-mono);font-weight:500}
  .wo__ts li.-stop em{color:var(--creme-3)}.wo__ts li.-now em::after{content:' · em curso';color:var(--creme-3)}.wo__ts li.-more span{color:var(--creme-4)}
  .wo__m{grid-column:1/-1;display:flex;justify-content:space-between;gap:1em;margin-top:calc(var(--u)*.25);font-size:calc(var(--u)*.66);color:var(--creme-2);white-space:nowrap}
  .wo__m span{white-space:normal}.wo__ts li em{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.wo__m b{font-family:var(--font-mono);font-weight:500;color:var(--creme-2)}
  .wo__r.-pause .wo__s{color:var(--creme-2);background:rgba(243,237,227,.1)}.wo__r.-pause .wo__s::before{width:.62em;height:.72em;border-radius:0;background:none;border-inline:.22em solid currentColor;box-sizing:border-box}
  .wo__w{grid-column:1/-1;font-size:calc(var(--u)*.62);font-weight:600;letter-spacing:.04em;color:#F2A29A}
  .wo__r.-stale{border-color:rgba(240,138,130,.35)!important}
  .wo__alert{margin:0 0 calc(var(--u)*.5);padding:calc(var(--u)*.45) calc(var(--u)*.6);border-radius:8px;background:rgba(224,124,115,.12);border:1px solid rgba(224,124,115,.3);font-size:calc(var(--u)*.64);color:#F2B3AC}
  .wo__mid{grid-column:1/-1;min-width:0}.wo__lb{color:var(--creme-3);margin-right:.5em}.wo__lb::after{content:':'}.wo__tm{grid-column:1/-1;display:flex;gap:1.6em;font-size:calc(var(--u)*.72);color:var(--creme-3)}.wo__tm b{font-family:var(--font-mono);font-weight:500;color:var(--creme)}.wo__q span,.wo__tm span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.wo__q{grid-column:1/-1;display:flex;gap:1.6em;font-family:var(--font-mono);font-size:calc(var(--u)*.72);color:var(--creme-2)}.wo__q span{display:grid;gap:.15em;min-width:0}.wo__q small{font-family:var(--font-ui);font-size:.82em;letter-spacing:.12em;text-transform:uppercase;color:var(--creme-3)}.wo__hd{grid-column:1/-1;display:flex;align-items:center;justify-content:space-between;gap:.8em;min-width:0}.wo__mo{font-family:var(--font-mono);font-weight:500;color:var(--c)}.wo__hd .wo__s{margin:0;flex:none}
  .wo__ph{grid-column:1/-1;display:grid;grid-template-columns:minmax(0,1fr);gap:calc(var(--u)*.5);min-width:0}
  .wo__pb{display:flex;gap:2px;height:calc(var(--u)*.7);border-radius:5px;overflow:hidden;background:rgba(243,237,227,.06)}
  .wo__pb i{flex:1 1 0;min-width:calc(var(--u)*1.6);display:grid;place-items:center;height:100%;font-style:normal;font-family:var(--font-mono);font-size:calc(var(--u)*.62);font-weight:600;color:#10140f;white-space:nowrap;overflow:hidden}.wo__pb .-setup{background:#8A8F99}.wo__pb .-work{background:#4FBF7E}.wo__pb .-stop{background:#E5594F}
  .wo__pl{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.3em 1em;white-space:nowrap;font-family:var(--font-mono);font-size:calc(var(--u)*.68);color:var(--creme-2)}
  .wo__pl em{font-style:normal;display:grid;gap:.2em;min-width:0;overflow:hidden;text-overflow:ellipsis}.wo__pl em small{display:flex;align-items:center;gap:.5em;font-family:var(--font-ui);font-size:.82em;letter-spacing:.12em;text-transform:uppercase}.wo__pl em small::before{content:'';width:9px;height:9px;border-radius:2px;background:currentColor;flex:none}
  .wo__pl .-setup{color:#A9AEB8}.wo__pl .-work{color:#6FCF8E}.wo__pl .-stop{color:#F08A82}
  .wo__more{padding-top:calc(var(--u)*.5);border-top:1px solid rgba(243,237,227,.08);font-size:calc(var(--u)*.62);color:var(--creme-4)}`;
  if (!document.getElementById('wo-css')) { css.id = 'wo-css'; document.head.appendChild(css); }
  const el = document.createElement('section'); el.className = `wo${float ? ' -float' : ''}`; el.setAttribute('aria-label', `Ordens de trabalho no Odoo${stage ? ` · ${STAGES.find((x) => x.id === stage).name}` : ''}`);
  let list = [];

  function row(w, now) {
    const t = sheet(w, now), started = w.state === 'progress' || w.state === 'done', late = started && w.expected > 0 && t.work > w.expected;
    const label = w.toClose ? 'Para fechar' : w.state === 'progress' ? (w.running ? 'A produzir' : 'Em pausa') : STATE[w.state] || w.state;
    // timesheet bar: each session on the time axis from the 1st start to now (work in the phase colour, stops neutral, gaps empty)
    const span = Math.max(1, t.end - (t.first || t.end));
    const ph = compact && phases(w, now);
    const bar = ph ? `<div class="wo__ph"><span class="wo__pb">${barParts(ph.tot).map(([k, pc]) => `<i class="-${k}" style="flex-grow:${pc.toFixed(2)}"></i>`).join('')}</span>
      <span class="wo__pl"><em class="-setup"><small>Setup</small>${clock(ph.tot.setup)}</em><em class="-work"><small>Trabalho</small>${clock(ph.tot.work)}</em><em class="-stop"><small>Paragem</small>${clock(ph.tot.stop)}</em></span></div>`
      : t.first ? `<span class="wo__tl">${(w.sessions || []).map((q) => `<i class="${q.work ? '' : '-stop'}" style="left:${((q.s - t.first) / span) * 100}%;width:${Math.max(0.8, (((q.e ?? now) - q.s) / span) * 100)}%"></i>`).join('')}</span>` : '';
    // timesheet: every start/stop as a line (latest 3), then the totals
    const ss = w.sessions || [], at = (ms) => { const d = new Date(ms), today = d.toDateString() === new Date(now).toDateString(); return (today ? '' : `${d.getDate()}/${d.getMonth() + 1} `) + d.toLocaleTimeString('pt-PT', { hour: '2-digit', minute: '2-digit' }); };
    const lines = ss.slice(-3).map((q) => `<li class="${q.work ? '' : '-stop'}${q.e ? '' : ' -now'}"><span>${at(q.s)} → ${q.e ? at(q.e) : 'agora'}</span><em>${q.work ? 'Produção' : esc(q.loss || 'Paragem')}</em><b>${plan(q.e != null && q.d != null ? q.d : ((q.e ?? now) - q.s) / 6e4)}</b></li>`).join('');
    const sheetHtml = started ? `<ul class="wo__ts">${ss.length > 3 ? `<li class="-more"><span>+ ${ss.length - 3} ${ss.length - 3 === 1 ? 'sessão anterior' : 'sessões anteriores'}</span></li>` : ''}${lines}</ul>` : '';
    const meta = started ? [`Produção ${plan(t.work)}`, `Paragens ${plan(t.stop)}`, `Aberta há ${plan(t.open)}`].join(' · ') : 'Ainda não iniciada';
    const st = stale(w, now);
    // current session and the total at this work centre (setup + work + stops since the first start = the bar), ticking
    // every second while running
    function times(x, at) { const q = (x.sessions || []).at(-1); if (!q) return ''; const t = phases(x, at).tot;
      return `<div class="wo__q"><span><small>Sessão</small>${clock(((q.e ?? at) - q.s) / 6e4)}</span><span><small>Total no centro</small>${clock(t.setup + t.work + t.stop)}</span></div>`; } // same label-over-value form as quantity / lot
    return `<div class="wo__r -${w.toClose ? 'progress -close' : w.state}${w.state === 'progress' && !w.running ? ' -pause' : ''}${late ? ' -late' : ''}${st && !compact ? ' -stale' : ''}" style="--c:${C[w.stage]}">
      ${st && !compact ? `<div class="wo__w">${esc(st.text)}</div>` : ''}
      ${compact ? `<div class="wo__hd"><b class="wo__mo">${w.mo}</b><span class="wo__s">${label}</span></div><div class="wo__mid"><div class="wo__a">${w.product}</div>
      <div class="wo__o"><span class="wo__x"><small class="wo__lb">${w.people.length > 1 ? 'Operadores' : 'Operador'}</small>${w.people.join(' · ') || '—'}</span></div></div>${qtyLot(w)}${times(w, now)}` : `<div class="wo__a"><b>${w.mo}</b>${w.product}</div>
      <div class="wo__o"><span class="wo__s">${label}</span><span class="wo__x">${[w.op, ...w.people].join(' · ')}</span></div>`}
      ${compact && started ? '' : `<div class="wo__t">${started ? `${clock(t.work)}<small>/ ${plan(w.expected)}</small>` : `previsto ${plan(w.expected)}`}</div>`}
      ${bar}${compact ? '' : `${sheetHtml}<div class="wo__m"><span>${meta}</span>${started && t.cost ? `<b title="Custo do centro de trabalho">${eur(t.cost)}</b>` : ''}</div>`}</div>`;
  }

  function draw() {
    const now = Date.now(), n = (st) => list.filter((w) => w.state === st).length;
    let body;
    if (stage) {
      // one phase: what is being produced right now first, in its own block; the rest follows, quieter
      let group = '';
      const shown = list.filter((w, i) => w.state === 'progress' || i < max); // everything in progress, then up to max
      body = shown.map((w) => {
        const g = w.state === 'progress' ? (w.running ? 'A produzir agora' : 'Em pausa') : 'A seguir', head = g !== group && !compact ? `<div class="wo__g${w.state === 'progress' ? ' -now' : ''}">${g}</div>` : ''; group = g;
        return head + row(w, now);
      }).join('') + (list.length > shown.length ? `<div class="wo__more">+ ${list.length - shown.length} ordens de trabalho</div>` : '');
    } else {
      // both phases (factory screen): one section per phase, in the phase's colour and number, like the 3D zones
      body = ['roasting', 'packaging'].map((st) => {
        const s = STAGES.find((x) => x.id === st), i = STAGES.indexOf(s), ws = list.filter((w) => w.stage === st), run = ws.filter((w) => w.state === 'progress').length;
        return `<div class="wo__g -st" style="--c:${s.color}">${s.name}<span>${run} a produzir</span></div>`
          + (ws.filter((w, j) => w.state === 'progress' || j < max).map((w) => row(w, now)).join('') || '<div class="wo__more">Sem ordens de trabalho</div>')
          + (ws.filter((w, j) => !(w.state === 'progress' || j < max)).length ? `<div class="wo__more">+ ${ws.filter((w, j) => !(w.state === 'progress' || j < max)).length}</div>` : '');
      }).join('');
    }
    const counts = onlyStarted ? [] : [[n('progress'), 'em curso'], [n('ready'), 'por fazer'], [n('blocked'), 'bloqueadas'], [n('done'), 'concluídas 24 h']].filter(([k], j) => k || j < 2); // started-only panels: counts of the rest would mislead
    const nStale = list.filter((w) => stale(w, now)).length;
    morph(el, `<div class="wo__h"><b>Ordens de trabalho</b><span>${counts.map(([k, l]) => `<i>${k}</i>${l}`).join('<em>·</em>')}</span></div>`
      + (nStale && !compact ? `<div class="wo__alert">${nStale} ${nStale === 1 ? 'ordem de trabalho por fechar' : 'ordens de trabalho por fechar'} no Odoo · os tempos e custos continuam a contar</div>` : '') + body);
  }
  addEventListener('flow:odoo', (e) => { if (!Array.isArray(e.detail.workorders)) return; list = e.detail.workorders.filter((w) => (!stage || w.stage === stage) && (!onlyStarted || w.state === 'progress' || w.toClose)); if (single) { const last = (w) => Math.max(0, ...(w.sessions || []).map((q) => q.s)); const keep = new Set(['roasting', 'packaging'].map((st) => list.filter((w) => (w.state === 'progress' || w.toClose) && w.stage === st).sort((a, b) => ((b.state === 'progress') - (a.state === 'progress')) || (b.running - a.running) || (last(b) - last(a)))[0]).filter(Boolean)); list = list.filter((w) => (w.state !== 'progress' && !w.toClose) || keep.has(w)); } // one per work centre: producing, then paused, then an order to close
    app.classList.add('-wo'); draw(); });
  setInterval(() => { if (list.some((w) => w.state === 'progress')) draw(); }, 1000); // paused ones tick too (their stop time grows)
  return el;
}
