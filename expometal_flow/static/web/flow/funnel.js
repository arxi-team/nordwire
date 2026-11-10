// Odoo funnel strip — the whole chain, live from the pilot: Leads → Propostas → Confirmadas → Ordens → Torragem → Embalagem → Expedição.
// Shown only when the server is connected to Odoo (SSE "odoo" / window event 'flow:odoo'). Counts only, no customer data.
import { STAGES } from './stages.js';
const C = Object.fromEntries(STAGES.map((s) => [s.id, s.color]));
const STEPS = [
  ['leads', 'Leads', null], ['proposals', 'Propostas', null], ['confirmed', 'Confirmadas', null],
  ['mos', 'Ordens', C.orders], ['roasting', 'Torra', C.roasting], ['packing', 'Embalam.', C.packaging], ['readyToShip', 'A expedir', C.delivered],
];
export function mountFunnel(app) {
  const css = document.createElement('style');
  css.textContent = `.ofun{position:absolute;z-index:6;left:50%;bottom:calc(var(--u)*5.9);transform:translateX(-50%);display:flex;align-items:center;gap:calc(var(--u)*.5);padding:calc(var(--u)*.55) calc(var(--u)*.9);border-radius:999px;background:rgba(12,11,9,.78);border:1px solid var(--linha);backdrop-filter:blur(10px);opacity:0;transition:opacity .6s}
  .ofun.-on{opacity:1}.fl.-clean .ofun{bottom:calc(var(--u)*1.6)}.fl.-odoo .fl__kpis{visibility:hidden}.ofun .s{display:flex;align-items:baseline;gap:.45em;padding:0 calc(var(--u)*.5);white-space:nowrap}
  .ofun b{font-family:var(--font-mono);font-weight:500;font-size:calc(var(--u)*1.1);color:var(--creme);font-variant-numeric:tabular-nums}
  .ofun span{font-size:calc(var(--u)*.6);letter-spacing:.1em;text-transform:uppercase;color:var(--creme-3)}
  .ofun i{width:7px;height:7px;border-radius:50%;background:var(--c,var(--creme-4));align-self:center}
  .ofun .a{color:var(--creme-4);font-size:calc(var(--u)*.8)}
  .ofun .src{display:flex;align-items:center;gap:.5em;padding-right:calc(var(--u)*.6);margin-right:calc(var(--u)*.2);border-right:1px solid var(--linha);font-size:calc(var(--u)*.62);letter-spacing:.16em;text-transform:uppercase;color:var(--ok)}
  .ofun .src::before{content:'';width:7px;height:7px;border-radius:50%;background:var(--ok);box-shadow:0 0 0 4px rgba(111,174,122,.18)}
  .ofun b.-bump{animation:ofb .7s cubic-bezier(.16,1,.3,1)}@keyframes ofb{30%{transform:translateY(-4px);color:var(--crema-2)}}`;
  document.head.appendChild(css);
  const el = document.createElement('div'); el.className = 'ofun'; el.setAttribute('aria-label', 'Funil Odoo ao vivo');
  el.innerHTML = '<span class="src">Odoo</span>' + STEPS.map(([k, l, c], i) => `${i ? '<span class="a">›</span>' : ''}<span class="s">${c ? `<i style="--c:${c}"></i>` : ''}<b data-k="${k}">–</b><span>${l}</span></span>`).join('');
  app.appendChild(el);
  addEventListener('flow:odoo', (e) => {
    const f = e.detail.funnel; if (!f) return; el.classList.add('-on'); app.classList.add('-odoo');
    for (const [k] of STEPS) { const b = el.querySelector(`[data-k=${k}]`); const v = String(f[k] ?? 0); if (b.textContent !== v) { if (b.textContent !== '–') { b.classList.remove('-bump'); void b.offsetWidth; b.classList.add('-bump'); } b.textContent = v; } }
  });
  // the source badge on the page says where the cards come from
  // one badge only: the live one (green dot) says the source; the separate source badge is hidden
  addEventListener('flow:odoo', () => {
    const s = app.querySelector('[data-el=source]'), l = app.querySelector('[data-el=link]');
    if (l) { l.innerHTML = '<b></b>Odoo · ao vivo'; if (s) s.style.display = 'none'; } else if (s) s.textContent = 'Odoo · ao vivo';
  });
}
