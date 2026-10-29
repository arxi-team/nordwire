# -*- coding: utf-8 -*-
"""PDA page for setting up the next MO on a Nord-controlled machine: the
operator scans the MO's QR code (its name, shown on the MO form) and the
work order's Core resource waits in "Setup" until the machine's own port
starts it. The setup travels to the Core as a 'setup' floor event on the
work order (mrp.workorder._nord_sync_notify_floor_event), same channel as
a Shop Floor start/pause.

A scan is the setup (no confirm button): the field is cleared and keeps the
focus, ready for the next scan. It is a plain text input: a PDA's built-in
scanner types the code followed by Enter, which needs no camera access
(browsers only allow the camera on HTTPS).
"""
from markupsafe import escape

from odoo.http import Controller, request, route

_PAGE = """<!DOCTYPE html>
<html lang="pt">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Nord PDA</title>
<style>
  body { font-family: system-ui, sans-serif; margin: 0; padding: 16px; background: #f4f5f7; color: #1f2933; }
  select { font-size: .9rem; padding: 6px; border-radius: 6px; border: 1px solid #cbd2d9; background: #fff; color: #52606d; }
  input { width: 100%%; box-sizing: border-box; font-size: 1.4rem; padding: 16px; margin-top: 12px; border-radius: 10px; border: 2px solid #1f6feb; }
  .msg { margin-top: 16px; padding: 16px; border-radius: 10px; font-size: 1.2rem; font-weight: 600; display: none; }
  .ok { background: #e3f9e5; color: #05400a; display: block; }
  .err { background: #ffe3e3; color: #610404; display: block; }
</style>
</head>
<body>
<select id="resource" aria-label="Centro de trabalho">%(options)s</select>
<input id="code" autofocus autocomplete="off" aria-label="QR da MO" placeholder="Ler o QR da MO">
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
function show(text, ok) { const m = $('msg'); m.textContent = (ok ? '\u2713 ' : '\u2717 ') + text; m.className = 'msg ' + (ok ? 'ok' : 'err'); }
// A scan is the setup: no confirm step. The field is cleared at once so the
// next scan can come in while this one is still on its way.
async function setup() {
  const mo = code.value.trim();
  code.value = '';
  code.focus();
  if (!mo) return;
  try {
    const r = await call('/nord_sync/pda/setup', {workcenter_id: +$('resource').value, mo_name: mo});
    show(r.message, r.success);
  } catch (e) { show(e.message, false); }
}
// Scanners end the code with Enter (some with Tab)
code.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); setup(); }
});
// Keep the field focused so the operator only has to pull the trigger;
// the work center select is the one thing allowed to take it away
code.addEventListener('blur', () => setTimeout(() => {
  if (document.activeElement !== $('resource')) code.focus();
}, 0));
document.addEventListener('click', (e) => { if (e.target !== $('resource')) code.focus(); });
document.addEventListener('visibilitychange', () => { if (!document.hidden) code.focus(); });
window.addEventListener('focus', () => code.focus());
// Each PDA sits at one machine: remember the work center it was set to
try {
  const saved = localStorage.getItem('nord_pda_workcenter');
  if (saved && [...$('resource').options].some((o) => o.value === saved)) $('resource').value = saved;
} catch (e) {}
$('resource').onchange = () => {
  try { localStorage.setItem('nord_pda_workcenter', $('resource').value); } catch (e) {}
  code.focus();
};
$('resource').addEventListener('blur', () => setTimeout(() => code.focus(), 0));
code.focus();
</script>
</body>
</html>
"""


class NordSyncPda(Controller):

    def _workcenters(self):
        return request.env['mrp.workcenter'].search(
            [('company_id', 'in', request.env.companies.ids + [False])], order='name',
        )

    def _open_workorders(self, workcenter):
        return request.env['mrp.workorder'].search([
            ('workcenter_id', '=', workcenter.id), ('state', 'not in', ('done', 'cancel')),
        ])

    @route('/nord_sync/pda', type='http', auth='user', methods=['GET'])
    def pda_page(self, workcenter_id=None, **kwargs):
        workcenters = self._workcenters()
        # Default to a machine Nord drives (its own port starts the work),
        # not just the alphabetically first work center
        default = workcenters.filtered('nord_sync_autonomous_close')[:1] or workcenters[:1]
        selected = int(workcenter_id) if workcenter_id else default.id
        options = ''.join(
            f'<option value="{wc.id}"{" selected" if wc.id == selected else ""}>{escape(wc.display_name)}</option>'
            for wc in workcenters
        )
        return request.make_response(
            _PAGE % {'options': options}, headers=[('Content-Type', 'text/html; charset=utf-8')],
        )

    @route('/nord_sync/pda/setup', type='jsonrpc', auth='user', methods=['POST'])
    def pda_setup(self, workcenter_id, mo_name, **kwargs):
        workcenter = self._workcenters().filtered(lambda wc: wc.id == int(workcenter_id))
        if not workcenter:
            return {'success': False, 'message': 'Centro de trabalho desconhecido.'}
        workorder = self._open_workorders(workcenter).filtered(
            lambda wo: wo.production_id.name == mo_name.strip()
        )[:1]
        if not workorder:
            return {
                'success': False,
                'message': f'{mo_name}: nada por fazer em {workcenter.name}.',
            }
        workorder._nord_sync_notify_floor_event('setup')
        workorder.production_id._nord_sync_ensure_delivery()
        return {
            'success': True,
            'message': f'{mo_name} em setup em {workcenter.name}.',
        }
