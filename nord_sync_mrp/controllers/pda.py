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
(mrp.workorder.action_nord_sync_not_ok), and an "Entregar" button that
delivers and closes the MO (mrp.production._nord_sync_demo_deliver). Results show in a banner fixed at
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
  body { font-family: system-ui, sans-serif; margin: 0; padding: 16px; background: #f4f5f7; color: #1f2933; }
  input { width: 100%; box-sizing: border-box; font-size: 1.4rem; padding: 16px; border-radius: 10px; border: 2px solid #1f6feb; }
  .msg { position: fixed; left: 12px; right: 12px; bottom: 12px; z-index: 10; padding: 16px; border-radius: 10px; font-size: 1.2rem; font-weight: 600; display: none; box-shadow: 0 4px 16px rgba(0, 0, 0, .25); }
  body { padding-bottom: 96px; }
  .ok { background: #e3f9e5; color: #05400a; display: block; }
  .err { background: #ffe3e3; color: #610404; display: block; }
  #todo { margin-top: 20px; }
  .wc { margin-top: 16px; }
  .wc h2 { font-size: 1.05rem; margin: 0 0 6px; display: flex; justify-content: space-between; }
  .wc h2 small { font-weight: 400; color: #52606d; }
  .mo { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 8px 12px; align-items: start; margin-bottom: 8px; padding: 12px; border-left: 4px solid transparent; border-radius: 10px; background: #fff; box-shadow: 0 1px 2px rgba(0, 0, 0, .06); }
  .mo.running { border-left-color: #2f9e44; }
  .mo.setup { border-left-color: #f08c00; }
  .mo.stopped { border-left-color: #e03131; }
  .mo b { display: block; font-size: 1.1rem; overflow-wrap: anywhere; }
  .mo .prod { margin-top: 2px; color: #52606d; font-size: .9rem; overflow-wrap: anywhere; }
  .mo .count { color: #c92a2a; font-weight: 600; }
  .tag { max-width: 11rem; padding: 3px 10px; border-radius: 12px; background: #e4e7eb; font-size: .8rem; line-height: 1.3; text-align: right; }
  .tag.running { background: #e3f9e5; color: #05400a; }
  .tag.setup { background: #fff0db; color: #7a4100; }
  .tag.stopped { background: #ffe3e3; color: #7d1a1a; }
  .tag small { display: block; opacity: .8; }
  .empty { color: #52606d; margin-top: 16px; }
  .notok { grid-column: 1 / -1; width: 100%; min-height: 52px; padding: 12px; border: 0; border-radius: 10px; background: #d64545; color: #fff; font-size: 1.15rem; font-weight: 700; letter-spacing: .02em; touch-action: manipulation; }
  .deliver { background: #2b8a3e; }
  .notok:active { background: #a61b1b; }
  .notok:disabled { opacity: .6; }
  .screen { display: none; }
  .screen.on { display: block; }
  #code { margin-bottom: 14px; }
  .menu button { display: flex; justify-content: space-between; align-items: center; gap: 12px; width: 100%; min-height: 84px; margin-bottom: 10px; padding: 0 18px; border: 0; border-radius: 14px; background: #fff; color: #1f2933; box-shadow: 0 1px 3px rgba(0, 0, 0, .15); font-size: 1.2rem; font-weight: 700; text-align: left; touch-action: manipulation; }
  .menu small { display: block; font-size: .8rem; font-weight: 400; color: #52606d; }
  .menu span { min-width: 40px; padding: 6px 12px; border-radius: 20px; background: #e4e7eb; color: #52606d; font-size: 1.1rem; text-align: center; }
  .menu span.n { background: #1f6feb; color: #fff; }
  .menu span.r { background: #2b8a3e; color: #fff; }
  .menu button:active { background: #e4e7eb; }
  .bar { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; }
  .bar h1 { margin: 0; font-size: 1.25rem; }
  .back { min-height: 48px; padding: 0 18px; border: 0; border-radius: 10px; background: #e4e7eb; color: #1f2933; font-size: 1.05rem; font-weight: 700; touch-action: manipulation; }
  .hint { margin-top: 12px; color: #52606d; }
  .stat { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 8px; padding: 12px; border-radius: 10px; background: #fff; box-shadow: 0 1px 2px rgba(0, 0, 0, .06); }
  .stat span { font-size: .9rem; color: #52606d; text-align: right; }
</style>
</head>
<body>
<input id="code" autofocus autocomplete="off" inputmode="none" aria-label="QR da MO" placeholder="Ler o QR da MO">
<div id="menu" class="screen on">
  <div class="menu">
    <button type="button" data-go="list"><div>Lista de MO<small>Por posto</small></div><span id="n-list">-</span></button>
    <button type="button" data-go="running"><div>Em curso<small>Não OK / Entregar</small></div><span id="n-running">-</span></button>
    <button type="button" data-go="status"><div>Estado dos postos<small>Resumo</small></div><span>&rsaquo;</span></button>
  </div>
</div>
<div id="list" class="screen">
  <div class="bar"><button type="button" class="back" data-go="menu">&larr; Menu</button><h1>Lista de MO</h1></div>
  <div class="todo" data-view="list" aria-live="polite"></div>
</div>
<div id="running" class="screen">
  <div class="bar"><button type="button" class="back" data-go="menu">&larr; Menu</button><h1>Em curso</h1></div>
  <div class="todo" data-view="running" aria-live="polite"></div>
</div>
<div id="status" class="screen">
  <div class="bar"><button type="button" class="back" data-go="menu">&larr; Menu</button><h1>Estado dos postos</h1></div>
  <div class="todo" data-view="status" aria-live="polite"></div>
</div>
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
const card = (o) => `<div class="mo ${o.floor}"><div><b>${esc(o.name)}</b>` +
  `<div class="prod">${esc(o.product)} \u00b7 ${esc(o.qty)}${o.not_ok ? ` \u00b7 <span class="count">Não OK: ${o.not_ok}</span>` : ''}</div></div>` +
  `<span class="tag ${o.floor}">${esc(o.operation)}${FLOOR[o.floor] ? `<small>${FLOOR[o.floor]}</small>` : ''}</span>` +
  `${o.can_not_ok ? `<button type="button" class="notok" data-mo="${esc(o.name)}">Não OK</button>` +
    `<button type="button" class="notok deliver" data-mo="${esc(o.name)}" data-deliver="1">Entregar</button>` : ''}</div>`;
const VIEWS = {
  list: (groups) => groups.length ? groups.map((g) =>
    `<div class="wc"><h2>${esc(g.workcenter)} <small>${g.orders.length}</small></h2>${g.orders.map(card).join('')}</div>`).join('')
    : '<div class="empty">Sem MOs por fazer.</div>',
  // Only the MOs a machine is working on, the ones that can be rejected or delivered
  running: (groups) => {
    const orders = groups.flatMap((g) => g.orders.filter((o) => o.can_not_ok));
    return orders.length ? orders.map(card).join('') : '<div class="empty">Nenhuma MO em curso.</div>';
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
  $('n-list').textContent = total; $('n-list').className = total ? 'n' : '';
  $('n-running').textContent = running; $('n-running').className = running ? 'r' : '';
  document.querySelectorAll('.todo').forEach((el) => { el.innerHTML = VIEWS[el.dataset.view](groups); });
}
async function refreshTodo() {
  try { groups = await call('/nord_sync/pda/todo', {}); } catch (e) { return; }
  render();
}
// Menu navigation: the hash is the screen, so the device's back button works
function go(name) { location.hash = name === 'menu' ? '' : name; }
function showScreen() {
  const name = location.hash.slice(1);
  const screen = $(name) && $(name).classList.contains('screen') ? name : 'menu';
  document.querySelectorAll('.screen').forEach((el) => el.classList.toggle('on', el.id === screen));
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
  const btn = e.target.closest('.notok');
  if (!btn || btn.disabled) return;
  btn.disabled = true;
  try {
    const r = await call(btn.dataset.deliver ? '/nord_sync/pda/deliver' : '/nord_sync/pda/not_ok', {mo_name: btn.dataset.mo});
    show(r.message, r.success);
  } catch (err) { show(err.message, false); }
  refreshTodo();
});
let hideMsg;
function show(text, ok) {
  const m = $('msg'); m.textContent = (ok ? '\u2713 ' : '\u2717 ') + text; m.className = 'msg ' + (ok ? 'ok' : 'err');
  clearTimeout(hideMsg);
  hideMsg = setTimeout(() => { m.className = 'msg'; }, ok ? 4000 : 8000);
}
// A scan is the setup: no confirm step. The field is cleared at once so the
// next scan can come in while this one is still on its way.
async function setup() {
  const mo = code.value.trim();
  code.value = '';
  code.focus();
  if (!mo) return;
  try {
    const r = await call('/nord_sync/pda/setup', {mo_name: mo});
    show(r.message, r.success);
  } catch (e) { show(e.message, false); }
  refreshTodo();
}
// Scanners end the code with Enter (some with Tab)
code.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); setup(); }
});
// The field keeps the focus on every screen, so a scan is recognised wherever
// the operator is and only has to pull the trigger
const focusScan = () => code.focus();
code.addEventListener('blur', () => setTimeout(focusScan, 0));
document.addEventListener('click', focusScan);
document.addEventListener('visibilitychange', () => { if (!document.hidden) focusScan(); });
window.addEventListener('focus', focusScan);
showScreen();
refreshTodo();
setInterval(refreshTodo, 30000);
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

    @route('/nord_sync/pda', type='http', auth='user', methods=['GET'])
    def pda_page(self, **kwargs):
        return request.make_response(_PAGE, headers=[('Content-Type', 'text/html; charset=utf-8')])

    @route('/nord_sync/pda/todo', type='jsonrpc', auth='user', methods=['POST'])
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
                'can_not_ok': running and workorder.workcenter_id.nord_sync_stop_tracking,
                'not_ok': workorder.nord_sync_not_ok_count,
            })
        return [
            {'workcenter': group['workcenter'], 'orders': group['orders']}
            for group in sorted(groups.values(), key=lambda g: (g['sequence'], g['workcenter']))
        ]

    @route('/nord_sync/pda/not_ok', type='jsonrpc', auth='user', methods=['POST'])
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

    @route('/nord_sync/pda/deliver', type='jsonrpc', auth='user', methods=['POST'])
    def pda_deliver(self, mo_name, **kwargs):
        """Delivers and closes the MO (the planned quantity), as a Nord
        "Mark Done" would. Only for an MO running on a stop-tracking work center."""
        mo_name = mo_name.strip()
        production = self._env()['mrp.production'].search([
            ('name', '=', mo_name), ('company_id', 'in', request.env.companies.ids),
        ], limit=1)
        if not production:
            return {'success': False, 'message': f'{mo_name}: MO não encontrada.'}
        success, message = production._nord_sync_demo_deliver()
        if success:
            wake_core(request.env)
            webhook(request.env, 'deliver', {'mo': production.name, 'state': production.state})
        return {'success': success, 'message': message}

    @route('/nord_sync/pda/setup', type='jsonrpc', auth='user', methods=['POST'])
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
        return {
            'success': True,
            'message': f'{mo_name} em setup em {workorder.workcenter_id.name}.',
        }
