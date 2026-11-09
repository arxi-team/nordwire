# -*- coding: utf-8 -*-
"""PDA page for setting up the next MO on a Nord-controlled machine: the
operator scans the MO's QR code (its name, shown on the MO form) and the
MO's next open work order (the operation it is waiting for, e.g. Torragem)
is set up: its Core resource waits in "Setup" until the machine's own port
starts it. The setup travels to the Core as a 'setup' floor event on the
work order (mrp.workorder._nord_sync_notify_floor_event), same channel as
a Shop Floor start/pause.

A scan is the setup (no confirm button): the field is cleared and keeps the
focus, ready for the next scan, with no on-screen keyboard (inputmode none:
it would cover the list). It is a plain text input: a PDA's built-in
scanner types the code followed by Enter, which needs no camera access
(browsers only allow the camera on HTTPS).

The page is a small menu app (screens switched in the page, the hash is the
screen). The scan field is on every screen and always focused, so a scan is
recognised wherever the operator is. Screens: Lista de MO (below), Em curso (the MOs a
machine is running, with the buttons) and Estado dos postos (a summary per
work center). All of them reuse the endpoints below.

The list shows the MOs still to do, grouped by the work center of the
operation each one is waiting for (the same one a scan would set up), so the
operator can see what is queued on each machine, refreshed after every scan
and every 30 s. A card whose machine is running it (on a stop-tracking work
center) has a "Não OK" button: one rejected unit for that MO
(mrp.workorder.action_nord_sync_not_ok), and the Entregar screen picks a
running MO and a quantity (the planned one by default) to deliver and close
it with (mrp.production._nord_sync_demo_deliver). Results show in a banner fixed at
the bottom, so they are seen wherever the list is scrolled to.
"""
import logging
import threading

import requests

from odoo import fields, modules
from odoo.exceptions import UserError
from odoo.http import Controller, request, route


# Fair demo: after a PDA action the Core is told to fetch now (its
# /nord_sync/pda/pull, local network only) instead of on its next sync tick
# (5 min), and an optional webhook URL (nord_sync.demo_webhook_url) gets a
# POST {event, at, source, ...}. URL of the pull: nord_sync.demo_core_pull_url
# if set. Both go out after the commit, off the request's thread.
_logger = logging.getLogger(__name__)

NORD_SYNC_DEMO_TIMEOUT_SECONDS = 5
NORD_SYNC_DEMO_DEFAULT_CORE_PULL_URL = 'http://localhost:8079/nord_sync/pda/pull'


def _post_after_commit(env, url, body, headers=None):
    if not url or modules.module.current_test:
        return

    def _post():
        try:
            requests.post(url, json=body, headers=headers or {}, timeout=NORD_SYNC_DEMO_TIMEOUT_SECONDS)
        except Exception as exc:
            _logger.warning('nord_sync: demo POST to %s failed: %s', url, exc)

    env.cr.postcommit.add(lambda: threading.Thread(target=_post, daemon=True).start())


def wake_core(env):
    """Asks the Core to fetch this client's queue now."""
    url = env['ir.config_parameter'].sudo().get_param('nord_sync.demo_core_pull_url') or NORD_SYNC_DEMO_DEFAULT_CORE_PULL_URL
    _post_after_commit(env, url, {})


def webhook(env, event, data):
    """POSTs {event, at, source, ...data} to nord_sync.demo_webhook_url."""
    url = env['ir.config_parameter'].sudo().get_param('nord_sync.demo_webhook_url')
    _post_after_commit(env, url, {'event': event, 'at': str(fields.Datetime.now()), 'source': 'odoo', **data})

_PAGE = """<!DOCTYPE html>
<html lang="pt">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Nord PDA</title>
<style>
  :root { --bg: #eef0f3; --card: #f6f7f9; --surface: #fff; --text: #1a1a1a; --text2: #495057; --muted: #6b7280; --border: rgba(17, 33, 56, .08); --border2: rgba(17, 33, 56, .2); --hover: rgba(17, 33, 56, .1); --navy: #112138; --navy-hover: #0c1726; --on-navy: #fff; --success: #28a745; --success-bg: rgba(40, 167, 69, .12); --warning: #d97706; --warning-bg: rgba(255, 172, 0, .16); --danger: #dc3545; --danger-bg: rgba(220, 53, 69, .12); --info: #17a2b8; --neutral-bg: rgba(108, 117, 125, .12); --shadow: 0 1px 3px rgba(0, 0, 0, .06); --shadow-lg: 0 4px 16px rgba(0, 0, 0, .12); }
  @media (prefers-color-scheme: dark) { :root { --bg: #0a1628; --card: #0d1b2e; --surface: #101f35; --text: #e2e8f0; --text2: #94a3b8; --muted: #94a3b8; --border: rgba(30, 58, 95, .5); --border2: rgba(30, 58, 95, .85); --hover: rgba(255, 255, 255, .06); --navy: #2f5a96; --navy-hover: #3a6bb0; --success: #3fb950; --success-bg: rgba(63, 185, 80, .16); --warning: #e3b341; --warning-bg: rgba(227, 179, 65, .16); --danger: #f85149; --danger-bg: rgba(248, 81, 73, .16); --neutral-bg: rgba(148, 163, 184, .14); --shadow: 0 1px 3px rgba(0, 0, 0, .3); --shadow-lg: 0 8px 32px rgba(0, 0, 0, .5); } }
  * { box-sizing: border-box; }
  body { font-family: 'DM Sans', system-ui, sans-serif; font-size: 15px; margin: 0; padding: 16px; min-height: 100vh; min-height: 100dvh; display: flex; flex-direction: column; background: var(--bg); color: var(--text); -webkit-font-smoothing: antialiased; }
  input, select { width: 100%; height: 44px; font: inherit; padding: 0 14px; border-radius: 8px; border: 1px solid var(--border2); background: var(--surface); color: var(--text); }
  input:focus, select:focus { outline: 2px solid var(--navy); outline-offset: 0; }
  .wc-bar { margin-bottom: 10px; }
  .msg { position: fixed; left: 16px; right: 16px; bottom: 16px; z-index: 10; padding: 12px 14px; border-radius: 10px; font-weight: 600; display: none; box-shadow: var(--shadow-lg); border: 1px solid var(--border2); background: var(--surface); }
  .ok { color: var(--success); border-color: var(--success); display: block; }
  .err { color: var(--danger); border-color: var(--danger); display: block; }
  .wc { margin-top: 20px; }
  .wc h2 { font-size: 11px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); margin: 0 0 8px 2px; display: flex; justify-content: space-between; }
  .mo { display: grid; grid-template-columns: minmax(0, 1fr); gap: 10px; margin-bottom: 8px; padding: 12px 14px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface); }
  .mo b { display: block; font-weight: 700; overflow-wrap: anywhere; }
  .mo .prod { margin-top: 2px; color: var(--muted); font-size: 13px; overflow-wrap: anywhere; }
  .mo .count { color: var(--danger); font-weight: 600; }
  .mo .state { margin-top: 6px; font-size: 12px; font-weight: 600; color: var(--muted); }
  .mo .state.running { color: var(--success); }
  .mo .state.setup { color: var(--warning); }
  .mo .state.stopped { color: var(--danger); }
  .empty { color: var(--muted); margin: 20px 2px; }
  .btn { width: 100%; min-height: 44px; padding: 0 16px; border: 1px solid transparent; border-radius: 8px; background: var(--navy); color: var(--on-navy); font: inherit; font-weight: 600; touch-action: manipulation; }
  .btn:active { background: var(--navy-hover); }
  .btn:disabled { opacity: .6; }
  .btn.danger { background: transparent; color: var(--danger); border-color: var(--danger); }
  .btn.danger:active { background: var(--danger-bg); }
  .back { height: 36px; padding: 0 12px; border: 1px solid var(--border2); border-radius: 8px; background: var(--surface); color: var(--text); font: inherit; font-size: 13px; font-weight: 600; touch-action: manipulation; }
  .back:active { background: var(--hover); }
  .screen { display: none; }
  .screen.on { display: block; }
  #code { margin-bottom: 16px; }
  .menu button { display: flex; justify-content: space-between; align-items: center; gap: 12px; width: 100%; min-height: 56px; margin-bottom: 8px; padding: 0 16px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface); color: var(--text); font: inherit; font-size: 16px; font-weight: 600; text-align: left; touch-action: manipulation; }
  .menu span { min-width: 28px; color: var(--muted); font-size: 14px; font-weight: 600; text-align: right; }
  .menu span.r { color: var(--success); }
  .menu button:active { background: var(--hover); }
  .bar { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
  .bar h1 { margin: 0; font-size: 20px; font-weight: 800; letter-spacing: -.02em; line-height: 1.15; }
  .stat { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 8px; padding: 12px 14px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface); }
  .stat span { font-size: 13px; color: var(--muted); text-align: right; }
  .pick { cursor: pointer; }
  .qty { display: grid; grid-template-columns: 56px minmax(0, 1fr) 56px; gap: 8px; margin: 16px 0; }
  .qty .btn { min-height: 56px; font-size: 1.5rem; }
  .qty input { height: 56px; text-align: center; font-size: 1.5rem; }
  .row { display: flex; gap: 8px; }
  .row .btn { flex: 1; }
  .row .btn.alt { background: var(--surface); color: var(--text); border-color: var(--border2); }
  /* Pushed to the bottom of the page and tall enough that the last card clears the banner */
  .brand { margin-top: auto; padding-top: 32px; text-align: center; pointer-events: none; user-select: none; }
  .brand img { height: 22px; width: auto; opacity: .75; vertical-align: bottom; }
</style>
</head>
<body>
<div class="wc-bar">
  <select id="wc-select" aria-label="Posto / Máquina">
    <option value="all">Todas as máquinas</option>
  </select>
</div>
<input id="code" autofocus autocomplete="off" inputmode="none" aria-label="QR da MO" placeholder="Ler o QR da MO">
<div id="menu" class="screen on">
  <div class="menu">
    <button type="button" data-go="list">Lista de MO<span id="n-list">-</span></button>
    <button type="button" data-go="running">Em curso<span id="n-running">-</span></button>
    <button type="button" data-go="deliver">Entregar<span>&rsaquo;</span></button>
    <button type="button" data-go="status">Estado dos postos<span>&rsaquo;</span></button>
  </div>
</div>
<div id="list" class="screen">
  <div class="bar"><button type="button" class="back" data-go="menu">&lsaquo; Menu</button><h1>Lista de MO</h1></div>
  <div class="todo" data-view="list" aria-live="polite"></div>
</div>
<div id="deliver" class="screen">
  <div class="bar"><button type="button" class="back" data-go="menu">&lsaquo; Menu</button><h1>Entregar</h1></div>
  <div class="todo" data-view="deliver" aria-live="polite"></div>
</div>
<div id="running" class="screen">
  <div class="bar"><button type="button" class="back" data-go="menu">&lsaquo; Menu</button><h1>Em curso</h1></div>
  <div class="todo" data-view="running" aria-live="polite"></div>
</div>
<div id="status" class="screen">
  <div class="bar"><button type="button" class="back" data-go="menu">&lsaquo; Menu</button><h1>Estado dos postos</h1></div>
  <div class="todo" data-view="status" aria-live="polite"></div>
</div>
<footer class="brand"><picture><source srcset="/nord_sync_mrp/static/src/img/logo_nordwire_white.svg" media="(prefers-color-scheme: dark)"><img src="/nord_sync_mrp/static/src/img/logo_nordwire.svg" alt="Nordwire"></picture></footer>
<div id="msg" class="msg"></div>
<script>
const $ = (id) => document.getElementById(id);
const code = $('code');
async function call(route, params) {
  const res = await fetch(route, {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({jsonrpc: '2.0', method: 'call', params})});
  const body = await res.json();
  if (body.error) throw new Error(body.error.data && body.error.data.message || body.error.message);
  return body.result;
}
const FLOOR = {running: 'a trabalhar', setup: 'em setup', stopped: 'parada'};
const esc = (t) => String(t).replace(/[&<>"']/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const stateOf = (o) => FLOOR[o.floor] ? `<div class="state ${o.floor}">${FLOOR[o.floor]}</div>` : '';
const card = (o, op) => `<div class="mo"><div><b>${esc(o.name)}</b>` +
  `<div class="prod">${op ? esc(o.operation) + ' \u00b7 ' : ''}${esc(o.product)} \u00b7 ${esc(o.qty)}${o.not_ok ? ` \u00b7 <span class="count">Não OK: ${o.not_ok}</span>` : ''}</div>${stateOf(o)}</div>` +
  `${o.can_not_ok ? `<button type="button" class="btn danger notok" data-mo="${esc(o.name)}">Não OK</button>` : ''}</div>`;
// Delivery: pick a running MO, then the quantity (the planned one by default)
let picked = null;
const deliverView = (groups) => {
  const orders = groups.flatMap((g) => g.orders.filter((o) => o.can_not_ok));
  if (picked) {
    const o = orders.find((x) => x.name === picked);
    if (!o) picked = null; else return `<div class="mo"><div><b>${esc(o.name)}</b>` +
      `<div class="prod">${esc(o.product)} \u00b7 planeado ${esc(o.qty)}</div></div></div>` +
      `<div class="qty"><button type="button" class="btn" data-step="-1">&minus;</button>` +
      `<input id="qty" type="number" inputmode="decimal" min="0" step="any" value="${o.qty_planned}" aria-label="Quantidade a entregar">` +
      `<button type="button" class="btn" data-step="1">+</button></div>` +
      `<div class="row"><button type="button" class="btn alt" data-pick="">Cancelar</button>` +
      `<button type="button" class="btn" data-confirm="${esc(o.name)}">Entregar</button></div>`;
  }
  return orders.length ? orders.map((o) => `<div class="mo pick" data-pick="${esc(o.name)}"><div><b>${esc(o.name)}</b>` +
    `<div class="prod">${esc(o.operation)} \u00b7 ${esc(o.product)} \u00b7 ${esc(o.qty)}</div></div></div>`).join('')
    : '<div class="empty">Nenhuma MO em curso para entregar.</div>';
};
const VIEWS = {
  deliver: (groups) => deliverView(groups),
  list: (groups) => groups.length ? groups.map((g) =>
    `<div class="wc"><h2>${esc(g.workcenter)} <small>${g.orders.length}</small></h2>${g.orders.map((o) => card(o)).join('')}</div>`).join('')
    : '<div class="empty">Sem MOs por fazer.</div>',
  // Only the MOs a machine is working on, the ones that can be rejected or delivered
  running: (groups) => {
    const orders = groups.flatMap((g) => g.orders.filter((o) => o.can_not_ok));
    return orders.length ? orders.map((o) => card(o, true)).join('') : '<div class="empty">Nenhuma MO em curso.</div>';
  },
  status: (groups) => groups.length ? groups.map((g) => {
    const n = (f) => g.orders.filter((o) => o.floor === f).length;
    const parts = [[n('running'), 'a trabalhar'], [n('setup'), 'em setup'], [n('stopped'), 'parada(s)']]
      .filter((p) => p[0]).map((p) => `${p[0]} ${p[1]}`);
    const waiting = g.orders.length - n('running') - n('setup') - n('stopped');
    if (waiting) parts.push(`${waiting} em espera`);
    return `<div class="stat"><b>${esc(g.workcenter)}</b><span>${parts.join(' \u00b7 ')}</span></div>`;
  }).join('') : '<div class="empty">Sem MOs por fazer.</div>',
};
let groups = [];
function render() {
  const running = groups.reduce((n, g) => n + g.orders.filter((o) => o.can_not_ok).length, 0);
  const total = groups.reduce((n, g) => n + g.orders.length, 0);
  $('n-list').textContent = total; 
  $('n-running').textContent = running; $('n-running').className = running ? 'r' : '';
  const typing = document.querySelector('#qty');
  const kept = typing ? typing.value : null;
  document.querySelectorAll('.todo').forEach((el) => { el.innerHTML = VIEWS[el.dataset.view](groups); });
  if (kept !== null && $('qty')) $('qty').value = kept;
}
async function refreshTodo() {
  try { groups = await call('/nordwire/pda/todo', {}); } catch (e) { return; }
  render();
}
// Menu navigation: the hash is the screen, so the device's back button works
function go(name) { location.hash = name === 'menu' ? '' : name; }
function showScreen() {
  const name = location.hash.slice(1);
  const screen = $(name) && $(name).classList.contains('screen') ? name : 'menu';
  document.querySelectorAll('.screen').forEach((el) => el.classList.toggle('on', el.id === screen));
  if (screen !== 'deliver') picked = null;
  code.focus();
  refreshTodo();
}
window.addEventListener('hashchange', showScreen);
document.addEventListener('click', (e) => {
  const nav = e.target.closest('[data-go]');
  if (nav) go(nav.dataset.go);
});
// The field keeps the focus (below), so a tap on a button must not take it:
// otherwise the field grabs it back mid-tap, the on-screen keyboard pops up,
// the page jumps and the tap misses. click still fires.
document.addEventListener('pointerdown', (e) => { if (e.target.closest('button')) e.preventDefault(); });
// One tap is one rejected unit, so a tap in flight disables the button
document.addEventListener('click', async (e) => {
  const btn = e.target.closest('.notok, [data-confirm]');
  if (!btn || btn.disabled) return;
  btn.disabled = true;
  try {
    const r = btn.dataset.confirm
      ? await call('/nordwire/pda/deliver', {mo_name: btn.dataset.confirm, qty: $('qty').value})
      : await call('/nordwire/pda/not_ok', {mo_name: btn.dataset.mo});
    show(r.message, r.success);
    if (btn.dataset.confirm && r.success) picked = null;
  } catch (err) { show(err.message, false); }
  btn.disabled = false;
  refreshTodo();
});
document.addEventListener('click', (e) => {
  const pick = e.target.closest('[data-pick]');
  if (pick) { picked = pick.dataset.pick || null; render(); }
  const step = e.target.closest('[data-step]');
  if (step) { const q = $('qty'); q.value = Math.max(0, (parseFloat(q.value) || 0) + Number(step.dataset.step)); }
});
let hideMsg;
function show(text, ok) {
  const m = $('msg'); m.textContent = text; m.className = 'msg ' + (ok ? 'ok' : 'err');
  clearTimeout(hideMsg);
  hideMsg = setTimeout(() => { m.className = 'msg'; }, ok ? 4000 : 8000);
}
async function loadWorkcenters() {
  try {
    const list = await call('/nordwire/pda/workcenters_list', {});
    const sel = $('wc-select');
    if (!sel) return;
    const currentVal = sel.value;
    sel.innerHTML = '<option value="all">Todas as máquinas</option>' +
      list.map((w) => `<option value="${w.id}">${esc(w.name)}${w.current_mo ? ' (' + esc(w.current_mo) + ')' : ''}</option>`).join('');
    if ([...sel.options].some((o) => o.value === currentVal)) sel.value = currentVal;
  } catch (e) {}
}
// A scan is the setup: no confirm step. The field is cleared at once so the
// next scan can come in while this one is still on its way.
async function setup() {
  const mo = code.value.trim();
  code.value = '';
  code.focus();
  if (!mo) return;
  const wcSelect = $('wc-select');
  const targetWc = wcSelect ? wcSelect.value : 'all';
  try {
    const r = await call('/nordwire/pda/assign_mo', {mo_name: mo, workcenter_id: targetWc});
    show(r.message, r.success);
  } catch (e) { show(e.message, false); }
  refreshTodo();
  loadWorkcenters();
}
// Scanners end the code with Enter (some with Tab)
code.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); setup(); }
});
$('wc-select').addEventListener('change', () => code.focus());
// The field keeps the focus on every screen, so a scan is recognised wherever
// the operator is and only has to pull the trigger
const focusScan = () => { if (!document.activeElement || (document.activeElement.id !== 'qty' && document.activeElement.id !== 'wc-select')) code.focus(); };
code.addEventListener('blur', () => setTimeout(focusScan, 0));
document.addEventListener('focusout', () => setTimeout(focusScan, 0));
document.addEventListener('click', focusScan);
document.addEventListener('visibilitychange', () => { if (!document.hidden) focusScan(); });
window.addEventListener('focus', focusScan);
showScreen();
refreshTodo();
loadWorkcenters();
setInterval(() => { refreshTodo(); loadWorkcenters(); }, 30000);
</script>
</body>
</html>
"""


class NordSyncPda(Controller):

    def _env(self):
        """The PDA's calls carry no context, so the session's language is
        the browser's: run them in the operator's own, which is what the
        notes they leave on the MO are written in."""
        return request.env(context=dict(request.env.context, lang=request.env.user.lang))

    @route(['/nordwire/pda', '/nord_sync/pda'], type='http', auth='user', methods=['GET'])
    def pda_page(self, **kwargs):
        return request.make_response(_PAGE, headers=[('Content-Type', 'text/html; charset=utf-8')])

    @route('/nordwire/pda/todo', type='jsonrpc', auth='user', methods=['POST'])
    def pda_todo(self, **kwargs):
        """The MOs still to do, grouped by the work center of the operation
        each one is waiting for (its next open work order, the one a scan
        sets up). A work center with nothing waiting is left out."""
        productions = self._env()['mrp.production'].search([
            ('state', 'in', ('confirmed', 'progress', 'to_close')),
            ('company_id', 'in', request.env.companies.ids),
        ], order='priority desc, date_start, id', limit=200)
        groups = {}
        for production in productions:
            workorder = production.workorder_ids.filtered(
                lambda wo: wo.state not in ('done', 'cancel')
            ).sorted(lambda wo: (wo.sequence, wo.id))[:1]
            if not workorder:
                continue
            group = groups.setdefault(workorder.workcenter_id.id, {
                'workcenter': workorder.workcenter_id.display_name,
                'sequence': workorder.workcenter_id.sequence,
                'orders': [],
            })
            running = workorder.state == 'progress' and workorder._nord_sync_is_running()
            open_kinds = set(workorder.time_ids.filtered(lambda t: not t.date_end).mapped('nord_sync_downtime_kind'))
            if running:
                floor = 'running'
            elif 'setup' in open_kinds:
                floor = 'setup'
            elif workorder.state == 'progress':
                floor = 'stopped'
            else:
                floor = ''
            group['orders'].append({
                'name': production.name,
                'product': production.product_id.display_name,
                'qty': f'{production.product_qty:g} {production.product_uom_id.name}',
                'operation': workorder.name,
                'in_progress': workorder.state == 'progress',
                # The machine on this operation, as Nord's live lines show it
                'floor': floor,
                'running': running,
                'qty_planned': production.product_qty,
                'can_not_ok': running and workorder.workcenter_id.nord_sync_stop_tracking,
                'not_ok': workorder.nord_sync_not_ok_count,
            })
        return [
            {'workcenter': group['workcenter'], 'orders': group['orders']}
            for group in sorted(groups.values(), key=lambda g: (g['sequence'], g['workcenter']))
        ]

    @route('/nordwire/pda/not_ok', type='jsonrpc', auth='user', methods=['POST'])
    def pda_not_ok(self, mo_name, **kwargs):
        mo_name = mo_name.strip()
        production = self._env()['mrp.production'].search([
            ('name', '=', mo_name), ('company_id', 'in', request.env.companies.ids),
        ], limit=1)
        if not production:
            return {'success': False, 'message': f'{mo_name}: MO não encontrada.'}
        workorder = production.workorder_ids.filtered(
            lambda wo: wo.state == 'progress'
        ).sorted(lambda wo: (wo.sequence, wo.id))[:1]
        if not workorder:
            return {'success': False, 'message': f'{mo_name}: nenhuma operação em curso.'}
        try:
            count = workorder.action_nord_sync_not_ok()
            wake_core(request.env)
            webhook(request.env, 'not_ok', {'mo': production.name, 'operation': workorder.name,
                                    'workcenter': workorder.workcenter_id.name, 'count': count})
        except UserError as e:
            return {'success': False, 'message': f'{mo_name}: {e}'}
        return {'success': True, 'message': f'{mo_name}: Não OK registado ({count}).'}

    @route('/nordwire/pda/deliver', type='jsonrpc', auth='user', methods=['POST'])
    def pda_deliver(self, mo_name, qty=None, **kwargs):
        """Delivers and closes the MO with `qty` good units (default: the
        planned quantity), as a Nord "Mark Done" would. Only for an MO running
        on a stop-tracking work center."""
        mo_name = mo_name.strip()
        production = self._env()['mrp.production'].search([
            ('name', '=', mo_name), ('company_id', 'in', request.env.companies.ids),
        ], limit=1)
        if not production:
            return {'success': False, 'message': f'{mo_name}: MO não encontrada.'}
        try:
            qty = None if qty in (None, '') else float(qty)
        except ValueError:
            return {'success': False, 'message': f'{mo_name}: quantidade inválida.'}
        if qty is not None and qty < 0:
            return {'success': False, 'message': f'{mo_name}: quantidade inválida.'}
        success, message = production._nord_sync_demo_deliver(qty=qty)
        if success:
            wake_core(request.env)
            webhook(request.env, 'deliver', {'mo': production.name, 'state': production.state, 'qty': qty})
        return {'success': success, 'message': message}

    @route('/nordwire/pda/setup', type='jsonrpc', auth='user', methods=['POST'])
    def pda_setup(self, mo_name, **kwargs):
        mo_name = mo_name.strip()
        production = self._env()['mrp.production'].search([
            ('name', '=', mo_name), ('company_id', 'in', request.env.companies.ids),
        ], limit=1)
        if not production:
            return {'success': False, 'message': f'{mo_name}: MO não encontrada.'}
        # The operation the MO is waiting for: work orders come in sequence
        workorder = production.workorder_ids.filtered(
            lambda wo: wo.state not in ('done', 'cancel')
        ).sorted(lambda wo: (wo.sequence, wo.id))[:1]
        if not workorder:
            return {'success': False, 'message': f'{mo_name}: nada por fazer.'}
        workorder._nord_sync_notify_floor_event('setup')
        wake_core(request.env)
        webhook(request.env, 'pda_setup', {'mo': production.name, 'operation': workorder.name,
                                                   'workcenter': workorder.workcenter_id.name})
        production._nord_sync_ensure_delivery()
        # The Core makes a second scan of the same MO on the same work center
        # a plain selection (no new setup), so say so instead of "setup".
        params = request.env['ir.config_parameter'].sudo()
        key = f'nord_sync.pda_selected.{workorder.workcenter_id.id}'
        selected_again = params.get_param(key) == str(production.id)
        params.set_param(key, production.id)
        # The Core keeps a scan made while the machine runs another MO
        # pending until that run stops: the next start is this MO's.
        # The latest open work line is the machine's run: an older one left
        # open (a session never closed) isn't what is on the machine now.
        line = self._env()['mrp.workcenter.productivity'].search([
            ('workcenter_id', '=', workorder.workcenter_id.id), ('date_end', '=', False),
            ('nord_sync_downtime_kind', '=', False), ('workorder_id.state', '=', 'progress'),
        ], order='date_start desc, id desc', limit=1)
        running = line.workorder_id if line.workorder_id != workorder else self._env()['mrp.workorder']
        if running:
            message = (f'{mo_name} pendente em {workorder.workcenter_id.name}: '
                       f'{running.production_id.name} continua até a máquina parar.')
        elif selected_again:
            message = f'{mo_name} selecionada em {workorder.workcenter_id.name}.'
        else:
            message = f'{mo_name} em setup em {workorder.workcenter_id.name}.'
        return {'success': True, 'message': message, 'selected_again': selected_again,
                'pending': bool(running)}

    @route('/nordwire/pda/workcenters_list', type='jsonrpc', auth='user', methods=['POST'])
    def pda_workcenters_list(self, **kwargs):
        workcenters = self._env()['mrp.workcenter'].search([
            ('company_id', 'in', request.env.companies.ids),
        ], order='sequence, name')
        return [
            {
                'id': wc.id,
                'name': wc.display_name or wc.name,
                'current_mo': wc.nord_sync_current_production_id.name or False,
            }
            for wc in workcenters
        ]

    @route('/nordwire/pda/assign_mo', type='jsonrpc', auth='user', methods=['POST'])
    def pda_assign_mo(self, mo_name, workcenter_id='all', **kwargs):
        mo_name = (mo_name or '').strip()
        production = self._env()['mrp.production'].search([
            ('name', '=', mo_name), ('company_id', 'in', request.env.companies.ids),
        ], limit=1)
        if not production:
            return {'success': False, 'message': f'{mo_name}: MO não encontrada.'}

        Workcenter = self._env()['mrp.workcenter']
        if workcenter_id == 'all':
            workcenters = Workcenter.search([
                ('company_id', 'in', request.env.companies.ids),
            ])
            if not workcenters:
                return {'success': False, 'message': 'Nenhum posto de trabalho encontrado.'}
        else:
            try:
                wc_id = int(workcenter_id)
                workcenters = Workcenter.browse(wc_id)
                if not workcenters.exists():
                    return {'success': False, 'message': 'Posto de trabalho não encontrado.'}
            except (ValueError, TypeError):
                return {'success': False, 'message': 'Identificador de posto inválido.'}

        if production.state not in ('confirmed', 'progress', 'to_close'):
            return {'success': False, 'message': f'{mo_name}: MO não está disponível para produção.'}

        updated_names = []
        errors = []
        for wc in workcenters:
            try:
                # Own savepoint: a failure half way (e.g. after the work order
                # was created) must not leave partial writes behind.
                with self._env().cr.savepoint():
                    wc.with_context(nord_sync_pda_setup=True).nord_sync_current_production_id = production.id
                updated_names.append(wc.display_name or wc.name)
            except UserError as ue:
                errors.append(f"{wc.name}: {ue.args[0]}")
            except Exception as e:
                errors.append(f"{wc.name}: {e}")

        wake_core(request.env)
        webhook(request.env, 'pda_assign_mo', {
            'mo': production.name,
            'workcenters': [w.name for w in workcenters],
            'updated': updated_names,
            'errors': errors,
        })

        if errors and not updated_names:
            return {'success': False, 'message': ' | '.join(errors)}
        elif errors:
            return {
                'success': True,
                'message': f"{mo_name} atribuída a: {', '.join(updated_names)}. Avisos: {' | '.join(errors)}",
            }
        else:
            if workcenter_id == 'all':
                return {'success': True, 'message': f"{mo_name} atribuída a todas as máquinas ({len(updated_names)})."}
            return {'success': True, 'message': f"{mo_name} atribuída a {updated_names[0]}."}
