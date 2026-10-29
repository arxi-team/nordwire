# -*- coding: utf-8 -*-
"""PDA page for setting up the next MO on a Nord-controlled machine: the
operator scans the MO's QR code (its name, shown on the MO form) and the
MO's next open work order (the operation it is waiting for, e.g. Torragem)
is set up: its Core resource waits in "Setup" until the machine's own port
starts it. The setup travels to the Core as a 'setup' floor event on the
work order (mrp.workorder._nord_sync_notify_floor_event), same channel as
a Shop Floor start/pause.

A scan is the setup (no confirm button): the field is cleared and keeps the
focus, ready for the next scan. It is a plain text input: a PDA's built-in
scanner types the code followed by Enter, which needs no camera access
(browsers only allow the camera on HTTPS).
"""
from odoo.http import Controller, request, route

_PAGE = """<!DOCTYPE html>
<html lang="pt">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Nord PDA</title>
<style>
  body { font-family: system-ui, sans-serif; margin: 0; padding: 16px; background: #f4f5f7; color: #1f2933; }
  input { width: 100%; box-sizing: border-box; font-size: 1.4rem; padding: 16px; border-radius: 10px; border: 2px solid #1f6feb; }
  .msg { margin-top: 16px; padding: 16px; border-radius: 10px; font-size: 1.2rem; font-weight: 600; display: none; }
  .ok { background: #e3f9e5; color: #05400a; display: block; }
  .err { background: #ffe3e3; color: #610404; display: block; }
</style>
</head>
<body>
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
    const r = await call('/nord_sync/pda/setup', {mo_name: mo});
    show(r.message, r.success);
  } catch (e) { show(e.message, false); }
}
// Scanners end the code with Enter (some with Tab)
code.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); setup(); }
});
// Keep the field focused so the operator only has to pull the trigger
code.addEventListener('blur', () => setTimeout(() => code.focus(), 0));
document.addEventListener('click', () => code.focus());
document.addEventListener('visibilitychange', () => { if (!document.hidden) code.focus(); });
window.addEventListener('focus', () => code.focus());
code.focus();
</script>
</body>
</html>
"""


class NordSyncPda(Controller):

    @route('/nord_sync/pda', type='http', auth='user', methods=['GET'])
    def pda_page(self, **kwargs):
        return request.make_response(_PAGE, headers=[('Content-Type', 'text/html; charset=utf-8')])

    @route('/nord_sync/pda/setup', type='jsonrpc', auth='user', methods=['POST'])
    def pda_setup(self, mo_name, **kwargs):
        mo_name = mo_name.strip()
        production = request.env['mrp.production'].search([
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
        production._nord_sync_ensure_delivery()
        return {
            'success': True,
            'message': f'{mo_name} em setup em {workorder.workcenter_id.name}.',
        }
