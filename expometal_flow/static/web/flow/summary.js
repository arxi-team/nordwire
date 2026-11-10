// Order journey: when a delivery is validated in Odoo (and production is linked to it by the sale order), the board steps aside
// for 10 s and shows the journey: waiting → roasting → packing → delivery (timesheets per work centre), the cost from
// Odoo (materials, work centres €/h, labour €/h), quality and team — then returns. Everything comes from Odoo (odooFlow.summary()).
// Triggers: SSE 'summary' (a delivery just validated) → window event 'flow:summary'; key R shows the latest one.
const SHOW_MS = 10000;
const nf = (n, d = 0) => Number(n || 0).toLocaleString('pt-PT', { minimumFractionDigits: d, maximumFractionDigits: d });
const dur = (min) => { const m = Math.round(min); return m < 60 ? `${m} min` : m < 1440 ? `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, '0')}` : `${Math.floor(m / 1440)} d ${String(Math.floor((m % 1440) / 60)).padStart(2, '0')} h`; };
const hm = (ts) => new Date(ts).toLocaleTimeString('pt-PT', { hour: '2-digit', minute: '2-digit' });
const day = (ts) => new Date(ts).toLocaleDateString('pt-PT', { day: 'numeric', month: 'short' });
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

export function mountSummary(app) {
  const css = document.createElement('style');
  // layout (from the whiteboard sketch): top-right the closed MO, left 4 cards (setup · work · stop · total cost),
  // right the time details, bottom the cost calculation. Colours = the screens' state colours (work green, setup grey, stop red).
  css.textContent = `
  .sm{position:fixed;inset:0;z-index:50;display:grid;grid-template-columns:1.15fr 1fr;grid-template-rows:auto 1fr auto auto;
    gap:calc(var(--u)*1.6) calc(var(--u)*2.4);padding:calc(var(--u)*2.6) calc(var(--u)*3.2) calc(var(--u)*2);
    background:radial-gradient(120% 95% at 0% -10%,#2a2321 0%,#17120f 55%,#0d0b0a 100%);color:var(--creme);font-family:var(--font-ui);text-align:left;
    opacity:0;visibility:hidden;transition:opacity .6s cubic-bezier(.16,1,.3,1),visibility 0s .6s}
  .sm.-on{opacity:1;visibility:visible;transition:opacity .6s cubic-bezier(.16,1,.3,1)}
  .sm.-on>*{animation:sm-in .9s cubic-bezier(.16,1,.3,1) both}.sm.-on>*:nth-child(2){animation-delay:.06s}.sm.-on>*:nth-child(3){animation-delay:.12s}.sm.-on>*:nth-child(4){animation-delay:.18s}.sm.-on>*:nth-child(5){animation-delay:.24s}
  @keyframes sm-in{from{opacity:0;transform:translateY(14px)}}
  /* top-left: what this screen is */
  .sm__hd{align-self:start}
  .sm__brand{font-size:calc(var(--u)*.7);letter-spacing:.2em;text-transform:uppercase;color:var(--creme-3)}
  .sm__ttl{margin-top:calc(var(--u)*.6);font-family:var(--font-craft);font-weight:300;font-size:calc(var(--u)*3);line-height:1.05}
  .sm__ttl em{font-style:normal;color:var(--creme-3)}
  /* top-right: the closed MO, the most visible element */
  .sm__mo{align-self:start;padding:calc(var(--u)*1.4) calc(var(--u)*1.7);border-radius:18px;background:#0f1a2c;border:1px solid rgba(120,150,200,.24);box-shadow:0 26px 52px -26px rgba(0,0,0,.9)}
  .sm__st{display:inline-flex;align-items:center;gap:.6em;padding:.5em 1.1em;border-radius:999px;font-size:calc(var(--u)*.78);font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:#0f1a14;background:#4FBF7E;box-shadow:0 0 22px -6px #4FBF7E}
  .sm__st.-run{background:#F0A531;box-shadow:0 0 22px -6px #F0A531;color:#1a1206}
  .sm__mo h2{margin:calc(var(--u)*.8) 0 calc(var(--u)*.2);font-family:var(--font-mono);font-weight:500;font-size:calc(var(--u)*3.6);letter-spacing:.01em;line-height:1}
  .sm__mo h2 small{font-size:.32em;color:var(--creme-3);margin-left:.7em;letter-spacing:.04em}
  .sm__mo p{margin:0;font-size:calc(var(--u)*1.35)}
  .sm__mo dl{display:grid;grid-template-columns:repeat(4,auto);justify-content:start;gap:.2em calc(var(--u)*2);margin:calc(var(--u)*1) 0 0}
  .sm__mo dt{font-size:calc(var(--u)*.58);letter-spacing:.14em;text-transform:uppercase;color:var(--creme-3)}
  .sm__mo dd{margin:0;font-family:var(--font-mono);font-size:calc(var(--u)*.92);color:var(--creme-2)}
  .sm__mo dd.-ok{color:#6FCF8E}.sm__mo dd.-bad{color:#F08A82}
  /* left: 4 cards */
  .sm__cards{display:grid;grid-template-columns:1fr 1.3fr;grid-template-rows:minmax(0,1fr) minmax(0,1fr);gap:calc(var(--u)*1.2);min-height:0}
  .sm__card{display:flex;flex-direction:column;justify-content:space-between;padding:calc(var(--u)*1.3) calc(var(--u)*1.5);border-radius:16px;background:color-mix(in srgb,#142137 70%,transparent);border:1px solid rgba(120,150,200,.16)}
  .sm__card header{display:flex;align-items:center;gap:.6em;font-size:calc(var(--u)*.8);font-weight:600;letter-spacing:.14em;text-transform:uppercase;color:var(--creme-2)}
  .sm__card header i{width:12px;height:12px;border-radius:3px;background:var(--k)}
  .sm__card b{font-family:var(--font-mono);font-weight:500;font-size:calc(var(--u)*3);letter-spacing:-.02em;color:var(--k)}
  .sm__card span{font-size:calc(var(--u)*.86);color:var(--creme-3)}
  /* the operation cost: the card in focus (bigger cell of the grid, darkest, the only one with a shadow) */
  .sm__card.-cost{padding-block:calc(var(--u)*1.05);background:#0b1424;border-color:rgba(140,170,220,.34);box-shadow:0 26px 52px -26px rgba(0,0,0,.9)}
  .sm__card.-cost b{color:var(--creme);font-size:calc(var(--u)*3.6);line-height:1}
  .sm__card.-cost dl{display:grid;grid-template-columns:1fr auto;gap:.15em calc(var(--u)*1);margin:0;font-size:calc(var(--u)*.86);line-height:1.3;color:var(--creme-3)}
  .sm__card.-cost dd{margin:0;font-family:var(--font-mono);color:var(--creme-2);text-align:right}
  /* right: time details */
  .sm__lines{display:grid;align-content:start;gap:calc(var(--u)*.2);min-height:0}
  .sm__bar{display:flex;gap:3px;height:calc(var(--u)*1);border-radius:6px;overflow:hidden;margin-bottom:calc(var(--u)*.8)}
  .sm__bar i{display:block;height:100%;min-width:6px}.sm__bar .-work{background:#4FBF7E}.sm__bar .-setup{background:#8A8F99}.sm__bar .-stop{background:#E5594F}
  .sm__ln{display:grid;grid-template-columns:auto 1fr auto;gap:calc(var(--u)*.9);align-items:baseline;padding:calc(var(--u)*.75) 0;border-bottom:1px solid rgba(243,237,227,.08)}
  .sm__ln:last-child{border-bottom:0}
  .sm__ln i{width:10px;height:10px;border-radius:3px;background:var(--k,var(--creme-3));align-self:center}
  .sm__ln div{font-size:calc(var(--u)*1.05);color:var(--creme)}.sm__ln div small{display:block;margin-top:.2em;font-size:.76em;color:var(--creme-3)}
  .sm__ln b{font-family:var(--font-mono);font-weight:500;font-size:calc(var(--u)*1.3);color:var(--k,var(--creme))}
  /* per work centre: name + MO/operations + time in it, its own history bar, and work · setup · stop with how many times */
  .sm__wc{display:grid;gap:calc(var(--u)*.45);padding:calc(var(--u)*.8) 0;border-bottom:1px solid rgba(243,237,227,.08)}
  .sm__wch{display:grid;grid-template-columns:auto auto 1fr auto;gap:calc(var(--u)*.7);align-items:baseline}
  .sm__wch i{width:10px;height:10px;border-radius:50%;background:var(--c);align-self:center}
  .sm__wch b{font-size:calc(var(--u)*1.15);font-weight:600}.sm__wch small{font-size:calc(var(--u)*.72);color:var(--creme-3);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .sm__wch span{font-family:var(--font-mono);font-weight:500;font-size:calc(var(--u)*1.3)}
  .sm__wcb{display:flex;gap:2px;height:8px;border-radius:4px;overflow:hidden}
  .sm__wcb i{display:block;height:100%;min-width:4px}.sm__wcb .-work{background:#4FBF7E}.sm__wcb .-setup{background:#8A8F99}.sm__wcb .-stop{background:#E5594F}
  .sm__wcf{display:flex;flex-wrap:wrap;gap:.2em calc(var(--u)*1.4);font-size:calc(var(--u)*.78);color:var(--creme-3)}
  .sm__wcf em{font-style:normal}.sm__wcf b{font-family:var(--font-mono);font-weight:500}
  .sm__wcf .-work b{color:#6FCF8E}.sm__wcf .-setup b{color:#B5BAC4}.sm__wcf .-stop b{color:#F08A82}
  /* bottom: the cost calculation */
  .sm__calc{grid-column:1/-1;display:flex;align-items:stretch;gap:calc(var(--u)*1.2);padding:calc(var(--u)*1.2) calc(var(--u)*1.6);border-radius:16px;background:rgba(243,237,227,.04);border:1px solid rgba(243,237,227,.1)}
  .sm__calc > div{display:grid;align-content:center;gap:.3em;min-width:0}
  .sm__calc > div:not(.-op){flex:1}
  .sm__calc small{font-size:calc(var(--u)*.62);letter-spacing:.14em;text-transform:uppercase;color:var(--creme-3)}
  .sm__calc b{font-family:var(--font-mono);font-weight:500;font-size:calc(var(--u)*1.6);color:var(--creme)}
  .sm__calc em{font-style:normal;font-size:calc(var(--u)*.72);color:var(--creme-3);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .sm__calc .-op{font-family:var(--font-mono);font-size:calc(var(--u)*1.8);color:var(--creme-4);align-self:center}
  .sm__calc .-tot{flex:1.2;padding-left:calc(var(--u)*1.4);border-left:1px solid rgba(243,237,227,.12)}.sm__calc .-tot b{font-size:calc(var(--u)*2.2)}
  .sm__f{grid-column:1/-1;display:flex;align-items:center;gap:calc(var(--u)*1.2);font-size:calc(var(--u)*.7);color:var(--creme-4)}
  .sm__f u{flex:1;height:2px;border-radius:1px;background:rgba(243,237,227,.08);overflow:hidden;text-decoration:none}
  .sm__f u i{display:block;height:100%;width:100%;background:var(--creme-3);transform-origin:left}
  .sm.-on .sm__f u i{animation:sm-count ${SHOW_MS}ms linear both}@keyframes sm-count{to{transform:scaleX(0)}}`;
  document.head.appendChild(css);
  const el = document.createElement('section'); el.className = 'sm'; el.setAttribute('aria-live', 'polite'); el.setAttribute('aria-label', 'Resumo da produção concluída');
  app.appendChild(el);
  let timer = 0;

  const eur = (v) => `${Number(v || 0).toLocaleString('pt-PT', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`;
  const K = { work: '#4FBF7E', setup: '#8A8F99', stop: '#E5594F' };
  const STAGE = { Torra: '#F0A531', Torragem: '#F0A531', Embalamento: '#EE6047', Embalagem: '#EE6047' };
  const OP = { Moagem: 'Torra' }; // stand naming for Odoo operations (the user's call)
  const times = (n, one, many) => `${n} ${n === 1 ? one : many}`;
  function show(s) {
    if (!s || !s.steps) return;
    const produced = !s.delivered && s.produced, endAt = s.delivered || (produced ? s.prodEnd : null), done = !!s.delivered;
    const ph = s.phases || { setup: { min: 0, n: 0 }, work: { min: 0, n: 0 }, stop: { min: 0, n: 0 } };
    const first = s.segs?.[0]?.a, last = s.segs?.at(-1)?.b, span = first ? (last - first) / 6e4 : 0;
    const pc = (m) => (span ? `${Math.round((m / span) * 100)}% do tempo` : '');
    const main = s.out.length === 1 ? s.out[0] : null, moName = s.mos.map((m) => m.mo).join(' · ');
    const qOk = s.quality.filter((q) => q.ok).length;
    const diff = s.expected ? (ph.work.min - s.expected) / s.expected : null;
    const total = Math.max(1, (last || 1) - (first || 0));
    const opCost = s.cost.workcentres + s.cost.labour; // card: what running the MO cost (work centres + labour), materials apart
    const wc = s.steps.reduce((a, x) => a + x.wcCost, 0), wcHours = s.steps.map((x) => `${dur(x.work + x.stop)} × ${nf(x.wcCostHour)} €/h`).join(' + ');
    el.innerHTML = `
      <div class="sm__hd"><div class="sm__brand">Nordwire × Arxi · SK Coffee</div><div class="sm__ttl">Resumo de produção<em>.</em></div></div>
      <section class="sm__mo">
        <span class="sm__st${done || produced ? '' : ' -run'}">${done ? '✓ Encomenda entregue' : produced ? '✓ Produção concluída' : '● Em curso'}</span>
        <h2>${esc(moName)}${s.origin ? `<small>${esc(s.origin)}</small>` : ''}</h2>
        <p>${esc(main ? main.product : `${s.out.length} produtos`)}</p>
        <dl><dt>Quantidade</dt><dt>Lote</dt><dt>${done ? 'Entregue' : 'Concluída'}</dt><dt>Qualidade</dt>
          <dd>${main ? `${nf(main.qty, main.uom === 'kg' ? 1 : 0)} ${esc(main.uom)}${main.uom !== 'kg' && s.kg ? ` · ${nf(s.kg, 1)} kg` : ''}` : `${nf(s.kg, 1)} kg`}</dd>
          <dd>${esc(s.lot || '—')}</dd><dd>${endAt ? `${day(endAt)} ${hm(endAt)}` : '—'}</dd>
          <dd class="${s.quality.length ? (qOk === s.quality.length ? '-ok' : '-bad') : ''}">${s.quality.length ? `${qOk}/${s.quality.length} conformes` : '—'}</dd></dl>
      </section>
      <div class="sm__cards">
        <div class="sm__card" style="--k:${K.setup}"><header><i></i>Setup</header><b>${dur(ph.setup.min)}</b><span>${times(ph.setup.n, 'vez', 'vezes')} · ${pc(ph.setup.min)}</span></div>
        <div class="sm__card" style="--k:${K.work}"><header><i></i>Trabalho</header><b>${dur(ph.work.min)}</b><span>${times(ph.work.n, 'período', 'períodos')} · ${pc(ph.work.min)}</span></div>
        <div class="sm__card" style="--k:${K.stop}"><header><i></i>Paragem</header><b>${dur(ph.stop.min)}</b><span>${times(ph.stop.n, 'paragem', 'paragens')} · ${pc(ph.stop.min)}</span></div>
        <div class="sm__card -cost"><header>Custo da operação</header><b>${eur(opCost)}</b>
          <dl><dt>Centros de trabalho</dt><dd>${eur(s.cost.workcentres)}</dd><dt>Mão de obra</dt><dd>${eur(s.cost.labour)}</dd>${s.kg && opCost ? `<dt>Por kg · sem materiais</dt><dd>${eur(opCost / s.kg)}</dd>` : ''}</dl></div>
      </div>
      <div class="sm__lines">
        <div class="sm__bar">${(s.segs || []).map((g) => `<i class="-${g.k}" style="flex-grow:${Math.max(1, ((g.b - g.a) / total) * 100).toFixed(2)}"></i>`).join('')}</div>
        <div class="sm__ln"><i></i><div>Do início ao fim<small>${first ? `${day(first)} ${hm(first)} → ${day(last)} ${hm(last)}` : '—'}</small></div><b>${dur(span)}</b></div>
        ${(s.route || []).map((x) => { const p = x.phases || { setup: { min: 0, n: 0 }, work: { min: 0, n: 0 }, stop: { min: 0, n: 0 } }, w = Math.max(1, x.last - x.first);
          const name = OP[x.op] || x.op;
          return `<div class="sm__wc" style="--c:${STAGE[name] || STAGE[x.wc] || '#8FA9D6'}">
            <div class="sm__wch"><i></i><b>${esc(name)}</b><small>${s.mos.length > 1 ? esc(x.mo) : ''}</small><span>${dur(x.span)}</span></div>
            <div class="sm__wcb">${(x.segs || []).map((g) => `<i class="-${g.k}" style="flex-grow:${Math.max(1, ((g.b - g.a) / w) * 100).toFixed(2)}"></i>`).join('')}</div>
            <div class="sm__wcf"><em class="-work">Trabalho <b>${dur(p.work.min)}</b></em><em class="-setup">Setup <b>${dur(p.setup.min)}</b> · ${p.setup.n}×</em><em class="-stop">Paragem <b>${dur(p.stop.min)}</b> · ${p.stop.n}×</em>
              <em>${times(x.sessions, 'sessão', 'sessões')}${x.expected ? ` · previsto ${dur(x.expected)}` : ''} · ${eur(x.wcCost)}</em></div></div>`; }).join('')}
        ${diff != null ? `<div class="sm__ln" style="--k:${diff <= 0 ? K.work : K.stop}"><i></i><div>Real vs previsto<small>${dur(ph.work.min)} reais para ${dur(s.expected)} previstos</small></div><b>${diff <= 0 ? '−' : '+'}${Math.abs(Math.round(diff * 100))}%</b></div>` : ''}
        ${done ? `<div class="sm__ln"><i></i><div>Até à entrega<small>${s.picking ? esc(s.picking) : ''}</small></div><b>${dur((s.delivered - last) / 6e4)}</b></div>` : ''}
      </div>
      <section class="sm__calc">
        <div><small>Materiais</small><b>${eur(s.cost.materials)}</b><em>${s.materials.map((m) => `${nf(m.qty, m.qty % 1 ? 1 : 0)} ${esc(m.uom)} × ${eur(m.unitCost)}`).join(' + ')}</em></div>
        <div class="-op">+</div>
        <div><small>Operações</small><b>${eur(wc + s.cost.labour)}</b><em>centros de trabalho ${eur(wc)} + mão de obra ${eur(s.cost.labour)}</em></div>
        <div class="-op">=</div>
        <div class="-tot"><small>Custo total de produção</small><b>${eur(s.cost.total)}</b><em>${s.kg ? `${eur(s.perKg)} por kg · ${nf(s.kg, 1)} kg` : ''}</em></div>
      </section>
      <footer class="sm__f"><span>Dados e custos do Odoo · volta ao painel em ${SHOW_MS / 1000} s</span><u><i></i></u></footer>`;
    el.classList.remove('-on'); void el.offsetWidth; el.classList.add('-on');
    clearTimeout(timer); timer = setTimeout(() => el.classList.remove('-on'), SHOW_MS);
  }

  addEventListener('flow:summary', (e) => show(e.detail));
  // R: show the latest finished production again (real data, view only) · Esc closes it
  addEventListener('keydown', (e) => {
    if (e.key === 'r' || e.key === 'R') fetch(window.FLOW_CFG?.summary || '/api/flow/summary', { credentials: 'same-origin' }).then((r) => r.json()).then(show).catch(() => {});
    if (e.key === 'Escape') { clearTimeout(timer); el.classList.remove('-on'); }
  });
  return { show };
}
