# -*- coding: utf-8 -*-
"""PDA page for setting up the next MO on a Nord-controlled machine: the
operator scans the MO's QR code (its name, shown on the MO form) and the
work order's Core resource waits in "Setup" until the machine's own port
starts it. The setup travels to the Core as a 'setup' floor event on the
work order (mrp.workorder._nord_sync_notify_floor_event), same channel as
a Shop Floor start/pause.

The scan field is a plain text input: a PDA's built-in scanner types the
code followed by Enter, which needs no camera access (browsers only allow
the camera on HTTPS).
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
  h1 { font-size: 1.3rem; margin: 0 0 12px; }
  label { display: block; font-size: .85rem; margin: 12px 0 4px; color: #52606d; }
  select, input, button { width: 100%%; box-sizing: border-box; font-size: 1.1rem; padding: 12px; border-radius: 8px; border: 1px solid #cbd2d9; }
  button { background: #1f6feb; color: #fff; border: 0; margin-top: 12px; }
  .card { background: #fff; border-radius: 10px; padding: 14px; margin-top: 16px; }
  .msg { margin-top: 12px; padding: 12px; border-radius: 8px; display: none; }
  .ok { background: #e3f9e5; color: #05400a; display: block; }
  .err { background: #ffe3e3; color: #610404; display: block; }
  .state { font-size: 1.2rem; font-weight: 600; }
</style>
</head>
<body>
<h1>Setup de MO</h1>
<label for="resource">Centro de trabalho</label>
<select id="resource">%(options)s</select>
<label for="code">Ler o QR da MO</label>
<input id="code" autofocus autocomplete="off" placeholder="WH/MO/00000">
<button id="send">Colocar em setup</button>
<div id="msg" class="msg"></div>
<div class="card">
  <div class="state" id="state">-</div>
  <div id="detail"></div>
</div>
<script>
const $ = (id) => document.getElementById(id);
async function call(route, params) {
  const res = await fetch(route, {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({jsonrpc: '2.0', method: 'call', params})});
  const body = await res.json();
  if (body.error) throw new Error(body.error.data && body.error.data.message || body.error.message);
  return body.result;
}
function show(text, ok) { const m = $('msg'); m.textContent = text; m.className = 'msg ' + (ok ? 'ok' : 'err'); }
async function refresh() {
  try {
    const s = await call('/nord_sync/pda/status', {workcenter_id: +$('resource').value});
    $('state').textContent = s.state;
    $('detail').textContent = s.detail;
  } catch (e) { $('state').textContent = 'Sem ligação'; $('detail').textContent = e.message; }
}
async function setup() {
  const code = $('code').value.trim();
  if (!code) return;
  try {
    const r = await call('/nord_sync/pda/setup', {workcenter_id: +$('resource').value, mo_name: code});
    show(r.message, r.success);
  } catch (e) { show(e.message, false); }
  $('code').value = ''; $('code').focus(); refresh();
}
$('send').onclick = setup;
$('code').addEventListener('keydown', (e) => { if (e.key === 'Enter') setup(); });
// Each PDA sits at one machine: remember the work center it was set to
try {
  const saved = localStorage.getItem('nord_pda_workcenter');
  if (saved && [...$('resource').options].some((o) => o.value === saved)) $('resource').value = saved;
} catch (e) {}
$('resource').onchange = () => {
  try { localStorage.setItem('nord_pda_workcenter', $('resource').value); } catch (e) {}
  refresh();
};
refresh(); setInterval(refresh, 3000);
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

    @route('/nord_sync/pda/setup', type='json', auth='user', methods=['POST'])
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
                'message': f'{mo_name} não tem nenhuma operação por fazer em {workcenter.name}.',
            }
        workorder._nord_sync_notify_floor_event('setup')
        workorder.production_id._nord_sync_ensure_delivery()
        return {
            'success': True,
            'message': f'{mo_name} em setup em {workcenter.name}. Carregue no botão para iniciar.',
        }

    @route('/nord_sync/pda/status', type='json', auth='user', methods=['POST'])
    def pda_status(self, workcenter_id, **kwargs):
        workcenter = self._workcenters().filtered(lambda wc: wc.id == int(workcenter_id))
        running = self._open_workorders(workcenter).filtered(
            lambda wo: wo.time_ids.filtered(lambda t: not t.date_end)
        ) if workcenter else False
        if running:
            return {'state': 'A trabalhar', 'detail': ', '.join(running.mapped('production_id.name'))}
        return {'state': 'Parado', 'detail': ''}
