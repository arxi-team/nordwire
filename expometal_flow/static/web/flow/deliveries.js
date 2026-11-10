// Delivered list (Odoo outgoing pickings done, newest first): picking, product, kg, date. A new one slides in at the top.
// Used by the Linha de produção (Entregue column) and the Fábrica 3D (right column).
const CSS = `/* ---- Entregue: list of delivered pickings (same panel language as the work orders) ---- */
.dl { background: color-mix(in srgb, var(--nw-navy, #142137) 86%, transparent); border: 1px solid color-mix(in srgb, #4a6a9a 30%, transparent); border-radius: 16px;
  padding: calc(var(--u) * .85) calc(var(--u) * 1.1) calc(var(--u) * .4); max-height: 100%; overflow: hidden;
  }
.dl header { display: flex; justify-content: space-between; align-items: baseline; padding-bottom: calc(var(--u) * .5); }
.dl header span { font-size: calc(var(--u) * .66); font-weight: 600; letter-spacing: .16em; text-transform: uppercase; color: var(--creme-2); }
.dl header em { font-style: normal; font-size: calc(var(--u) * .66); color: var(--creme-3); }
/* each delivery as a small card (same language as the work-order cards): product first, the picking under it, a check */
.dl__r { display: grid; grid-template-columns: auto 1fr auto; grid-template-rows: auto auto; column-gap: calc(var(--u) * .8); align-items: center;
  margin-top: calc(var(--u) * .5); padding: calc(var(--u) * .55) calc(var(--u) * .8); border-radius: 10px; background: rgba(243,237,227,.035); border: 1px solid rgba(243,237,227,.06); }
.dl__r::before { content: '✓'; grid-row: 1 / 3; display: grid; place-items: center; width: calc(var(--u) * 1.7); height: calc(var(--u) * 1.7); border-radius: 50%;
  font-size: calc(var(--u) * .8); color: var(--c); background: color-mix(in srgb, var(--c) 14%, transparent); }
.dl__r span { grid-column: 2; grid-row: 1; font-size: calc(var(--u) * .9); color: var(--creme); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.dl__r b { grid-column: 2; grid-row: 2; min-width: 0; font-family: var(--font-mono); font-weight: 400; font-size: calc(var(--u) * .7); color: var(--creme-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.dl__r.-new { animation: dl-in 1s var(--e-spring) both; background: rgba(243,237,227,.05); border-radius: 8px; }
@keyframes dl-in { from { opacity: 0; transform: translateY(-18px); } }
/* "Fechar": the delivery has been dealt with on the floor — it slides out and leaves the list (this screen only) */
.dl__x { grid-column: 3; grid-row: 1 / 3; padding: .5em 1em; border-radius: 999px; border: 1px solid rgba(243,237,227,.18); background: rgba(243,237,227,.06);
  color: var(--creme-2); font: 600 calc(var(--u) * .66) var(--font-ui); letter-spacing: .1em; text-transform: uppercase; cursor: pointer; }
.dl__x:hover { background: rgba(243,237,227,.14); color: var(--creme); }
.dl__r.-out { animation: dl-out .7s cubic-bezier(.6,0,.9,.4) forwards; }
@keyframes dl-out { to { opacity: 0; transform: translateX(-110%); } }
`;

// "Lote HORECA · 6× SK Forte + 2 artigos" → "Lote HORECA +2": the main product, then how many more lines
const short = (p) => { const m = /^(.*?) \+ (\d+) artigos?$/.exec(p || ''); return m ? `${m[1].split(' · ')[0]} +${m[2]}` : p || ''; };
// closed deliveries are remembered on this screen (localStorage); the list then shows the next ones
const KEY = 'flow.deliveries.closed';
const closed = (() => { try { return new Set(JSON.parse(localStorage.getItem(KEY) || '[]')); } catch { return new Set(); } })();
addEventListener('click', (e) => {
  const b = e.target.closest('[data-dl-close]'); if (!b) return;
  closed.add(b.dataset.dlClose); try { localStorage.setItem(KEY, JSON.stringify([...closed].slice(-200))); } catch { /* storage blocked: closed for this session */ }
  const row = b.closest('.dl__r'); row.classList.add('-out'); row.addEventListener('animationend', () => row.remove(), { once: true });
});
// empty: what the list says when nothing is shown (default: why)
export function deliveriesHtml(done, seen, max = 15, empty = null) {
  if (!document.getElementById('dl-css')) { const s = document.createElement('style'); s.id = 'dl-css'; s.textContent = CSS; document.head.appendChild(s); }
  const open = done.filter((o) => !closed.has(o.picking || o.id));
  const rows = [...open].sort((a, b) => b.enteredAt - a.enteredAt).slice(0, max).map((o) => `<div class="dl__r${seen && !seen.has(o.id) ? ' -new' : ''}">
    <span title="${o.product}">${short(o.product)}</span><b>${o.picking || o.id}${o.mo ? ` · ${o.mo}` : ''}</b><button type="button" class="dl__x" data-dl-close="${o.picking || o.id}">Fechar</button></div>`).join('');
  return `<section class="dl"><header><span>Entregas</span></header>${rows || `<div class="ll__idle"><b>${empty || (done.length ? 'Todas as entregas fechadas' : 'Sem entregas registadas')}</b></div>`}</section>`;
}
