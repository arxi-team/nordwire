# EXPOMETAL line dashboard served by Odoo itself (the same screen as the stand server's /flow/v5).
# Page:    /flow/v5/?token= (Linha de produção, ecrã 'flow' das dashboards Kioda) — add ?clean for the stand screen
# Data:    /flow/v5/data — the snapshot app/server/odoo/flow.js builds over JSON-2, read here with the ORM
# Summary: /flow/v5/summary?picking=<id> — the journey and cost of the order behind a validated delivery
# Read only; public, only for a Kioda device with access (?token=); no customer names on the screen (references, products, quantities).
# Keep in step with app/server/odoo/flow.js (poll → snapshot, summary).
import json
import re
import time
from datetime import datetime, timedelta, timezone

from odoo import fields, http
from odoo.http import request
from odoo.tools import file_path

PAGE = 'expometal_flow/static/web/flow/v5/'
POLL_MS = 5000  # each screen asks every 5 s; the snapshot is a handful of reads
SETUP_RE = re.compile(r'setup|ajust|mudan|limpeza', re.I)  # stop reasons that count as setup (same as the screens)


def _ms(dt):
    if not dt:
        return int(time.time() * 1000)
    if isinstance(dt, str):
        dt = datetime.strptime(dt[:19], '%Y-%m-%d %H:%M:%S')
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)


def _ref(name):
    p = str(name or '').split('/')
    return f'{p[-2]}-{p[-1]}' if len(p) >= 2 else str(name or '')


def _m2o(v, i=1):
    return v[i] if v else (0 if i == 0 else '')


def _label(display):
    s = re.sub(r'\s*\([^)]*\)\s*$', '', re.sub(r'^\[[^\]]+\]\s*', '', str(display or '')))
    parts = [x.strip() for x in s.split('|')]
    p1 = parts[1] if len(parts) > 1 else ''
    if re.search('granel', parts[0], re.I):
        return f'{p1 or parts[0]} · granel'
    if re.search('lote horeca', parts[0], re.I):
        return f"{parts[0]} · {re.sub(r'^6 x ', '6× ', p1)}"
    kind = 'moído' if re.search('moído', p1, re.I) else 'grão' if re.search('grão', p1, re.I) else ''
    second = f"{kind} {parts[2] if len(parts) > 2 else ''}".strip() if kind else ''
    return ' · '.join(x for x in (parts[0], second) if x)


def _kg(qty, prod):
    # no weight in Odoo → 0 kg
    return round(((qty or 0) if prod and prod['uom'] == 'kg' else (qty or 0) * ((prod or {}).get('weight') or 0)) * 10) / 10


def _short(name):
    p = str(name).split()
    return f'{p[0]} {p[-1][0]}.' if len(p) > 1 else (p[0] if p else '')  # public screen: first name + initial


def _union_min(iv):
    # union of [s, e] intervals in minutes: sessions in parallel are counted once as time
    tot, ce = 0, float('-inf')
    for a, b in sorted(iv):
        if b <= ce:
            continue
        tot += b - max(a, ce)
        ce = b
    return tot / 6e4


def _is_work(t):
    return t['loss_type'] in ('productive', 'performance')


def _wc_names(env):
    icp = env['ir.config_parameter'].sudo()
    return icp.get_param('expometal_flow.wc_roast', 'Torragem'), icp.get_param('expometal_flow.wc_pack', 'Embalagem')


def _products(env, ids, fields=('weight', 'uom_id', 'display_name')):
    ids = [i for i in ids if i]
    return {p['id']: {'weight': p['weight'], 'uom': _m2o(p['uom_id']), 'name': p['display_name'], **({'price': p['standard_price']} if 'standard_price' in p else {})}
            for p in env['product.product'].browse(ids).read(list(fields))} if ids else {}


def _costs(env):
    # €/h defined in Odoo: per work centre (by name) and per employee
    Emp = env['hr.employee']
    return {'wc': {w['name']: w['costs_hour'] or 0 for w in env['mrp.workcenter'].search_read([], ['name', 'costs_hour'])},
            'emp': {e['id']: e['hourly_cost'] or 0 for e in Emp.search_read([], ['hourly_cost'])} if 'hourly_cost' in Emp._fields else {}}


def snapshot(env):
    wc_roast, wc_pack = _wc_names(env)
    env = env(su=True)  # read only, aggregated: the screen user does not need rights on every model
    WO, MO, Pick, Move = env['mrp.workorder'], env['mrp.production'], env['stock.picking'], env['stock.move']
    now = int(time.time() * 1000)
    # Odoo 19 work-order states: blocked · ready · progress · done · cancel (+ the ones finished in the last 24 h, and those
    # of an order still to close)
    wo_fields = ['state', 'workcenter_id', 'production_id', 'product_id', 'date_start', 'date_finished', 'duration',
                 'duration_expected', 'qty_production', 'qty_remaining', 'name']
    has_assigned = 'employee_assigned_ids' in WO._fields  # mrp_workorder (Enterprise)
    if has_assigned:
        wo_fields.append('employee_assigned_ids')
    wos = WO.search_read(['|', '|', ('state', 'in', ['ready', 'progress', 'blocked']),
                          '&', ('state', '=', 'done'), ('date_finished', '>=', fields.Datetime.now() - timedelta(days=1)),
                          ('production_id.state', '=', 'to_close')], wo_fields)
    mos = MO.search_read([('state', 'in', ['confirmed', 'progress', 'to_close'])],
                         ['name', 'product_id', 'product_qty', 'product_uom_id', 'lot_producing_ids', 'origin', 'state', 'date_start',
                          'date_finished', 'create_date'], order='create_date asc, id asc', limit=60)
    picks_done = Pick.search_read([('picking_type_code', '=', 'outgoing'), ('state', '=', 'done')],
                                  ['name', 'origin', 'date_done'], order='date_done desc', limit=15)
    picks_ready = Pick.search_count([('picking_type_code', '=', 'outgoing'), ('state', '=', 'assigned')])
    so = dict(env['sale.order']._read_group([('state', 'in', ['draft', 'sent', 'sale'])], ['state'], ['__count']))
    leads = [(stage.name, n) for stage, n in env['crm.lead']._read_group([('type', '=', 'opportunity'), ('active', '=', True)], ['stage_id'], ['__count'])] if 'crm.lead' in env else []
    sales_open = Pick._read_group([('picking_type_code', '=', 'outgoing'), ('state', 'in', ['waiting', 'confirmed', 'assigned']), ('sale_id', '!=', False)], ['sale_id'], ['__count'])
    # Entregue: outgoing pickings Ready that a production order feeds (picking.move_ids.move_orig_ids.production_id — only
    # make-to-order moves have that link; a make-to-stock production just goes into stock), newest first
    ready_picks = Pick.search_read([('picking_type_code', '=', 'outgoing'), ('state', '=', 'assigned'), ('move_ids.move_orig_ids.production_id', '!=', False)],
                                   ['name', 'origin', 'write_date', 'sale_id'], order='write_date desc', limit=15)

    prods = _products(env, {m['product_id'][0] for m in mos if m['product_id']} | {w['product_id'][0] for w in wos if w['product_id']})
    moves = Move.search_read([('picking_id', 'in', [p['id'] for p in ready_picks])], ['picking_id', 'product_id', 'product_uom_qty', 'move_orig_ids']) if ready_picks else []
    prods.update(_products(env, {m['product_id'][0] for m in moves} - set(prods)))
    # when each picking's production closed: its finished-product move's date (set when the order is marked done)
    orig_ids = [i for m in moves for i in m['move_orig_ids']]
    origs = {m['id']: m for m in Move.browse(orig_ids).read(['production_id', 'state', 'date'])} if orig_ids else {}
    pick_closed = {}
    for m in moves:
        for o in (origs.get(i) for i in m['move_orig_ids']):
            if o and o['production_id'] and o['state'] == 'done':
                pick_closed[m['picking_id'][0]] = max(pick_closed.get(m['picking_id'][0], 0), _ms(o['date']))
    # the production order(s) of each picking, named on its card: picking.sale_id.mrp_production_ids.name
    so_mos = {s['id']: s['mrp_production_ids'] for s in env['sale.order'].browse({p['sale_id'][0] for p in ready_picks if p['sale_id']}).read(['mrp_production_ids'])}
    mo_ids = {i for ids in so_mos.values() for i in ids}
    mo_name = {m['id']: _ref(m['name']) for m in MO.search_read([('id', 'in', list(mo_ids)), ('state', '!=', 'cancel')], ['name'])} if mo_ids else {}
    pick_kg, pick_top, pick_n = {}, {}, {}
    for m in moves:
        pid, prod = m['picking_id'][0], prods.get(m['product_id'][0])
        k = _kg(m['product_uom_qty'], prod)
        pick_kg[pid] = pick_kg.get(pid, 0) + k
        pick_n[pid] = pick_n.get(pid, 0) + 1
        if pid not in pick_top or k > pick_top[pid][0]:
            pick_top[pid] = (k, _label(prod['name'] if prod else m['product_id'][1]))
    pick_prod = {pid: top + (f" + {pick_n[pid] - 1} {'artigo' if pick_n[pid] == 2 else 'artigos'}" if pick_n[pid] > 1 else '') for pid, (_, top) in pick_top.items()}
    mo_by_id = {m['id']: m for m in mos}
    # lot being produced (MO lot_producing_ids) for the work-order cards
    lot_ids = {i for w in wos for i in mo_by_id.get(_m2o(w['production_id'], 0), {}).get('lot_producing_ids', [])}
    lot_name = {lot['id']: lot['name'] for lot in env['stock.lot'].browse(list(lot_ids)).read(['name'])} if lot_ids else {}
    # timesheets: every work-time session of the started work orders. Odoo adds a session to `duration` only when it closes,
    # so an open session (no date_end) gives the running part.
    started = [w['id'] for w in wos if w['state'] in ('progress', 'done')]
    times = env['mrp.workcenter.productivity'].search_read([('workorder_id', 'in', started)],
                                                           ['workorder_id', 'workcenter_id', 'date_start', 'date_end', 'duration', 'loss_type', 'loss_id', 'employee_id'],
                                                           order='date_start asc') if started else []
    costs = _costs(env)
    sess, since, people, first_start = {}, {}, {}, {}
    for t in times:
        wid, st = t['workorder_id'][0], _ms(t['date_start'])
        en = _ms(t['date_end']) if t['date_end'] else None
        work = _is_work(t)
        # public screen: work-centre €/h only (an employee's €/h never travels next to a name)
        sess.setdefault(wid, []).append({'s': st, 'e': en, 'd': t['duration'] if en else None, 'work': work,
                                         'loss': None if work else (_m2o(t['loss_id']) or 'Paragem'), 'rate': costs['wc'].get(_m2o(t['workcenter_id']), 0)})
        first_start[wid] = min(first_start.get(wid, st), st)
        if en is None and work:
            since[wid] = min(since.get(wid, st), st)
            if t['employee_id']:
                people.setdefault(wid, []).append(t['employee_id'][1])
    emp_name = {}
    if has_assigned:
        ids = {i for w in wos for i in w['employee_assigned_ids']}
        emp_name = {e['id']: e['name'] for e in env['hr.employee'].browse(list(ids)).read(['name'])} if ids else {}
    # an order to close (every step done, not marked done in Odoo yet) stays on its last work centre until it is closed
    last_wo = {}
    for w in wos:
        mid = _m2o(w['production_id'], 0)
        if mo_by_id.get(mid, {}).get('state') == 'to_close' and w['state'] == 'done' and (mid not in last_wo or w['date_finished'] > last_wo[mid]['date_finished']):
            last_wo[mid] = w
    workorders = []
    for w in wos:
        wc = _m2o(w['workcenter_id'])
        if wc not in (wc_roast, wc_pack):
            continue
        mo = mo_by_id.get(_m2o(w['production_id'], 0), {})
        prod = prods.get(_m2o(w['product_id'], 0))
        names = people.get(w['id'], []) + [emp_name[i] for i in w.get('employee_assigned_ids', []) if i in emp_name]
        workorders.append({
            'id': w['id'], 'op': w['name'], 'wc': wc, 'stage': 'roasting' if wc == wc_roast else 'packaging',
            'mo': _ref(_m2o(w['production_id'])), 'product': _label(prod['name'] if prod else _m2o(w['product_id'])),
            'qty': w['qty_production'], 'qtyLeft': w['qty_remaining'], 'state': w['state'],
            'uom': 'kg' if _m2o(mo.get('product_uom_id')) == 'kg' else 'un', 'kg': _kg(w['qty_production'], prod),
            'lot': ', '.join(lot_name[i] for i in mo.get('lot_producing_ids', []) if i in lot_name),
            'expected': w['duration_expected'], 'done': w['duration'], 'since': since.get(w['id']),
            'people': [_short(n) for n in dict.fromkeys(names)],
            'finishedAt': _ms(w['date_finished']) if w['date_finished'] else None,
            'sessions': sess.get(w['id'], []), 'running': w['id'] in since, 'toClose': last_wo.get(_m2o(w['production_id'], 0)) is w,
        })
    rank = {'progress': 0, 'done': 2}
    workorders.sort(key=lambda x: (rank.get(x['state'], 1), -(x['finishedAt'] or 0) if x['state'] == 'done' else x['id']))  # in progress, then the rest oldest first
    real_min = {x['id']: x['done'] + ((now - x['since']) / 6e4 if x['since'] else 0) for x in workorders}
    running = {wc_roast: [], wc_pack: []}
    for w in wos:
        if w['state'] == 'progress' and _m2o(w['workcenter_id']) in running:
            running[_m2o(w['workcenter_id'])].append(w)
    busy_mo = {_m2o(w['production_id'], 0) for w in wos if w['state'] == 'progress'}

    def card(mo, stage, **extra):
        p = prods.get(_m2o(mo['product_id'], 0))
        c = {'id': _ref(mo['name']), 'odooId': mo['id'], 'product': _label(p['name'] if p else _m2o(mo['product_id'])),
             'origin': f"Ref. {mo['origin']}" if mo.get('origin') else 'Plano de produção', 'kg': _kg(mo['product_qty'], p), 'stage': stage,
             'enteredAt': _ms(mo.get('date_start') or mo.get('create_date')), 'createdAt': _ms(mo.get('create_date')),
             'due': _ms(mo['date_finished']) if mo.get('date_finished') else None, 'qty': mo['product_qty'], 'progress': 0}
        c.update(extra)
        return c
    orders = []
    for wc, stage in ((wc_roast, 'roasting'), (wc_pack, 'packaging')):
        for w in running[wc]:  # one MO can have cards in two work centres
            mo = mo_by_id.get(w['production_id'][0]) or {'id': w['production_id'][0], 'name': w['production_id'][1], 'product_id': False, 'product_qty': w['qty_production']}
            exp = w['duration_expected']
            orders.append(card(mo, stage, enteredAt=first_start.get(w['id']) or _ms(w['date_start'] or mo.get('create_date')),
                               progress=min(0.97, real_min.get(w['id'], 0) / exp) if exp else None, op=w['name'], woId=w['id'],
                               focusKey=f"wo{w['id']}", running=w['id'] in since))
    # Ordens de Trabalho: only orders not started yet; once one enters work at a work centre it leaves for good
    for mo in mos:
        if mo['id'] not in busy_mo and mo['state'] == 'confirmed':
            orders.append(card(mo, 'orders'))
    for pk in ready_picks:
        orders.append({'id': pk['name'], 'odooId': pk['id'], 'product': pick_prod.get(pk['id'], 'Expedição'),
                       'origin': f"Ref. {pk['origin']}" if pk['origin'] else '', 'kg': round(pick_kg.get(pk['id'], 0) * 10) / 10,
                       'stage': 'delivered', 'enteredAt': pick_closed.get(pk['id']) or _ms(pk['write_date']), 'progress': 1, 'picking': pk['name'],
                       'mo': ', '.join(mo_name[i] for i in so_mos.get(_m2o(pk['sale_id'], 0), []) if i in mo_name)})

    def stage_count(names):
        return sum(n for name, n in leads if name in names)
    funnel = {
        'leads': stage_count({'New', 'Qualified', 'Prova/Degustação'}), 'proposals': so.get('draft', 0) + so.get('sent', 0),
        'negotiating': stage_count({'Proposition', 'Negociação'}), 'confirmed': len(sales_open), 'mos': len(mos),
        'roasting': len(running[wc_roast]), 'packing': len(running[wc_pack]), 'readyToShip': picks_ready,
        'delivered': sum(1 for p in picks_done if _ms(p['date_done']) > now - 864e5),
    }
    # validated deliveries: a new one here opens the summary of its order on the screens (inputs.js)
    shipped = [{'id': p['id'], 'name': p['name']} for p in picks_done]
    return {'orders': orders, 'funnel': funnel, 'workorders': workorders, 'shipped': shipped, 'ts': now, 'source': 'odoo', 'db': env.cr.dbname}


def summary(env, origin=None, picking_id=None, mo_id=None):
    """Journey of one order: its production orders (same sale order, or a single MO) → delivery. Times per work centre
    (from the timesheets), waits between steps, delivery, and the cost from Odoo: materials = consumed components × product
    cost (components made inside the same journey are not counted twice), work centres = session time × €/h of the work
    centre, labour = session time × €/h of the employee."""
    wc_roast, wc_pack = _wc_names(env)
    env = env(su=True)
    MO, Pick = env['mrp.production'], env['stock.picking']
    if picking_id and not origin:
        pk = Pick.browse(picking_id).read(['origin'])
        origin = pk[0]['origin'] if pk else None
    if mo_id and not origin:
        m = MO.browse(mo_id).read(['origin'])
        origin = (m[0]['origin'] if m else None) or None
    if not origin and not mo_id:
        # latest delivered order that has production behind it; otherwise the most recent order in production
        pk = Pick.search_read([('picking_type_code', '=', 'outgoing'), ('state', '=', 'done'), ('origin', '!=', False)], ['origin'], order='date_done desc', limit=30)
        with_mo = {m['origin'] for m in MO.search_read([('origin', 'in', list({p['origin'] for p in pk})), ('state', '!=', 'cancel')], ['origin'])} if pk else set()
        origin = next((p['origin'] for p in pk if p['origin'] in with_mo), None)
        if not origin:  # the order whose production was worked on most recently (latest timesheet)
            ts_ = env['mrp.workcenter.productivity'].search_read([('workorder_id', '!=', False)], ['workorder_id'], order='date_start desc', limit=40)
            wo = env['mrp.workorder'].browse(list({t['workorder_id'][0] for t in ts_})).read(['production_id']) if ts_ else []
            mo = MO.browse(list({w['production_id'][0] for w in wo})).read(['origin']) if wo else []
            origin = next((m['origin'] for m in mo if re.match(r'^S\d', m['origin'] or '')), None)
        if not origin:
            return None
    # production orders of the order: the sale order's own link (sale.order.mrp_production_ids), else the origin text
    mo_ids = [mo_id] if mo_id and not origin else None
    if origin:
        so = env['sale.order'].search_read([('name', '=', origin)], ['mrp_production_ids'], limit=1)
        if so and so[0]['mrp_production_ids']:
            mo_ids = so[0]['mrp_production_ids']
    mos = MO.search_read([('id', 'in', mo_ids), ('state', '!=', 'cancel')] if mo_ids else [('origin', '=', origin), ('state', '!=', 'cancel')],
                         ['name', 'product_id', 'product_qty', 'qty_produced', 'product_uom_id', 'state', 'create_date', 'date_start', 'date_finished',
                          'lot_producing_ids', 'workorder_ids'], order='create_date asc, id asc')
    if not mos:
        return None
    wo_ids = [i for m in mos for i in m['workorder_ids']]
    wos = env['mrp.workorder'].browse(wo_ids).read(['name', 'workcenter_id', 'production_id', 'duration', 'duration_expected', 'state']) if wo_ids else []
    times = env['mrp.workcenter.productivity'].search_read([('workorder_id', 'in', wo_ids)], ['workorder_id', 'workcenter_id', 'date_start', 'date_end', 'duration', 'loss_type', 'loss_id', 'employee_id'],
                                                           order='date_start asc') if wo_ids else []
    raw = env['stock.move'].search_read([('raw_material_production_id', 'in', [m['id'] for m in mos]), ('state', '!=', 'cancel')],
                                        ['product_id', 'quantity', 'product_uom_qty', 'picked', 'raw_material_production_id', 'product_uom'])
    picks = Pick.search_read([('origin', '=', origin), ('picking_type_code', '=', 'outgoing'), ('state', '!=', 'cancel')], ['name', 'state', 'date_done'], order='date_done desc') if origin else []
    costs = _costs(env)
    made = {m['product_id'][0] for m in mos}
    prods = _products(env, {m['product_id'][0] for m in raw} | made, ('standard_price', 'weight', 'uom_id', 'display_name'))
    quality = env['quality.check'].search_read([('production_id', 'in', [m['id'] for m in mos]), ('quality_state', '!=', 'none')],
                                               ['title', 'measure', 'norm_unit', 'quality_state', 'test_type']) if 'quality.check' in env else []
    lot_ids = [i for m in mos for i in m['lot_producing_ids']]
    lots = env['stock.lot'].browse(lot_ids).read(['name']) if lot_ids else []
    now = int(time.time() * 1000)

    def mins(a, b):
        return max(0, (b - a) / 6e4)
    # steps = work centres, in the order they were first used
    by_wc, wo_by_id, people = {}, {w['id']: w for w in wos}, set()
    for w in wos:
        x = by_wc.setdefault(_m2o(w['workcenter_id']) or '—', {'wc': _m2o(w['workcenter_id']) or '—', 'wos': [], 'sessions': [], 'expected': 0})
        x['wos'].append(w)
        x['expected'] += w['duration_expected']
    for t in times:
        # each session counts in the work centre where it happened (a work order may have been moved since)
        w = wo_by_id.get(t['workorder_id'][0])
        k = _m2o(t['workcenter_id']) or (w and _m2o(w['workcenter_id'])) or '—'
        s0, e0 = _ms(t['date_start']), (_ms(t['date_end']) if t['date_end'] else now)
        x = by_wc.setdefault(k, {'wc': k, 'wos': [], 'sessions': [], 'expected': 0})
        if w and w not in x['wos']:
            x['wos'].append(w)
        work = _is_work(t)
        x['sessions'].append({'s': s0, 'e': e0 if t['date_end'] else None, 'work': work, 'loss': None if work else (_m2o(t['loss_id']) or 'Paragem'),
                              'min': t['duration'] if t['date_end'] else mins(s0, now), 'emp': _m2o(t['employee_id'], 0), 'wo': t['workorder_id'][0]})
        if t['employee_id']:
            people.add(_short(t['employee_id'][1]))
    name_of = {wc_roast: 'Torra', wc_pack: 'Embalamento'}

    def timeline_of(sessions):
        # one timeline (all the sessions given): at each moment work wins over setup, setup over a stop; time with no session
        # open between the first and the last one is a stop (paused). Totals and how many times each happened.
        lst = [{'s': q['s'], 'e': q['e'] or now, 'k': 'work' if q['work'] else 'setup' if SETUP_RE.search(q['loss'] or '') else 'stop'} for q in sessions]
        cuts, segs = sorted({v for q in lst for v in (q['s'], q['e'])}), []
        for a, b in zip(cuts, cuts[1:]):
            on = [q['k'] for q in lst if q['s'] < b and q['e'] > a]
            k = 'work' if 'work' in on else 'setup' if 'setup' in on else 'stop'
            if segs and segs[-1]['k'] == k:
                segs[-1]['b'] = b
            else:
                segs.append({'k': k, 'a': a, 'b': b})
        phases = {k: {'min': 0, 'n': 0} for k in ('setup', 'work', 'stop')}
        for g in segs:
            phases[g['k']]['min'] += (g['b'] - g['a']) / 6e4
            phases[g['k']]['n'] += 1
        return {'phases': phases, 'segs': segs, 'n': len(lst)}

    steps, labour_of = [], {}
    for x in by_wc.values():
        ss = x['sessions']
        if not ss:
            continue
        first, last = min(q['s'] for q in ss), max(q['e'] or now for q in ss)
        # time = union of the sessions (parallel ones once); cost = per session, as Odoo does (duration × €/h)
        work = _union_min([(q['s'], q['e'] or now) for q in ss if q['work']])
        stop = sum(q['min'] for q in ss if not q['work'])
        rate = costs['wc'].get(x['wc'], 0)
        stops = {}
        for q in ss:
            if not q['work']:
                stops[q['loss']] = stops.get(q['loss'], 0) + q['min']
        used = [w for w in x['wos'] if any(q['wo'] == w['id'] for q in ss)]  # which production orders / operations this step belongs to
        t = timeline_of(ss)
        step = {'name': name_of.get(x['wc'], x['wc']), 'wc': x['wc'], 'mos': list(dict.fromkeys(_ref(_m2o(w['production_id'])) for w in used)),
                'ops': list(dict.fromkeys(w['name'] for w in used)), 'first': first, 'last': last, 'open': any(not q['e'] for q in ss), 'work': work, 'stop': stop,
                'span': mins(first, last), 'expected': sum(w['duration_expected'] or 0 for w in used if _m2o(w['workcenter_id']) == x['wc']), 'sessions': len(ss),
                'stops': [{'name': n, 'min': m} for n, m in stops.items()], 'wcCostHour': rate, 'wcCost': sum(q['min'] / 60 * rate for q in ss),
                'phases': t['phases'], 'segs': t['segs']}
        labour_of[id(step)] = sum(q['min'] / 60 * costs['emp'].get(q['emp'], 0) for q in ss)  # labour only as a total
        steps.append(step)
    steps.sort(key=lambda s: s['first'])
    # the order starts at the earliest of: MO creation, planned start, first timesheet (back-filled records can be created later)
    created = min([_ms(m['create_date']) for m in mos] + [_ms(m['date_start']) for m in mos if m['date_start']] + [s['first'] for s in steps])
    shipped = next((p for p in picks if p['state'] == 'done' and (not picking_id or p['id'] == picking_id)), None) or next((p for p in picks if p['state'] == 'done'), None)
    delivered = _ms(shipped['date_done']) if shipped else None
    prod_end = max(s['last'] for s in steps) if steps else None
    # timeline: wait → step → wait → step … → delivery
    timeline, t0 = [], created
    for s in steps:
        if s['first'] > t0:
            timeline.append({'kind': 'wait', 'label': f"Espera até {s['name'].lower()}" if timeline else 'Da ordem de trabalho à 1.ª operação', 'min': mins(t0, s['first'])})
        par = bool(timeline) and s['first'] < t0
        timeline.append({'kind': 'step', 'label': s['name'], 'mos': s['mos'], 'ops': s['ops'], 'stops': s['stops'], 'min': s['span'],
                         'bar': mins(t0, max(t0, s['last'])) if par else s['span'], 'work': s['work'], 'stop': s['stop'], 'open': s['open'], 'parallel': par})
        t0 = max(t0, s['last'])
    if delivered:
        timeline.append({'kind': 'ship', 'label': 'Até à entrega', 'min': mins(t0, delivered)})
    mo_done = {m['id'] for m in mos if m['state'] == 'done'}
    materials = []
    for m in raw:
        if m['product_id'][0] in made:
            continue
        p, used = prods.get(m['product_id'][0], {}), m['picked'] or _m2o(m['raw_material_production_id'], 0) in mo_done
        q = m['quantity'] if used else m['product_uom_qty']
        uom = _m2o(m['product_uom'])
        materials.append({'name': re.sub(r'\s*\|\s*', ' · ', re.sub(r'^\[[^\]]+\]\s*', '', m['product_id'][1])), 'qty': q, 'planned': not used,
                          'uom': 'un' if uom == 'Units' else uom, 'unitCost': p.get('price', 0), 'cost': q * p.get('price', 0)})
    raw_prods = {r['product_id'][0] for r in raw}
    final = [m for m in mos if m['product_id'][0] not in raw_prods]  # products not consumed inside the journey
    out = []
    for m in final or mos:
        q = m['qty_produced'] if m['state'] == 'done' else m['product_qty']
        uom = _m2o(m['product_uom_id'])
        out.append({'mo': _ref(m['name']), 'product': _label(m['product_id'][1]), 'qty': q, 'uom': 'un' if uom == 'Units' else uom,
                    'kg': _kg(q, prods.get(m['product_id'][0])), 'state': m['state']})
    cost = {'materials': sum(m['cost'] for m in materials), 'workcentres': sum(s['wcCost'] for s in steps), 'labour': sum(labour_of.values())}
    cost['total'] = cost['materials'] + cost['workcentres'] + cost['labour']
    kg = sum(o['kg'] or 0 for o in out)
    every = [q for x in by_wc.values() for q in x['sessions']]
    whole = timeline_of(every)
    # per operation (work order) in each work centre: the route the order really took, in the order it happened
    route = []
    for x in by_wc.values():
        groups = {}
        for q in x['sessions']:
            groups.setdefault(q['wo'], []).append(q)
        for wid, ss in groups.items():
            w, t = wo_by_id.get(wid), timeline_of(ss)
            first, last = min(q['s'] for q in ss), max(q['e'] or now for q in ss)
            route.append({'op': w['name'] if w else '—', 'wc': x['wc'], 'mo': _ref(_m2o(w['production_id'])) if w else '', 'first': first, 'last': last,
                          'span': mins(first, last), 'phases': t['phases'], 'segs': t['segs'], 'sessions': len(ss), 'open': any(not q['e'] for q in ss),
                          'expected': (w['duration_expected'] or 0) if w and _m2o(w['workcenter_id']) == x['wc'] else 0,
                          'wcCost': sum(q['min'] / 60 * costs['wc'].get(x['wc'], 0) for q in ss)})
    route.sort(key=lambda r: r['first'])
    produced = all(m['state'] == 'done' for m in mos)
    return {
        'phases': whole['phases'], 'segs': whole['segs'], 'sessions': len(every), 'expected': sum(s['expected'] or 0 for s in steps),
        'origin': origin or '', 'mos': [{'mo': _ref(m['name']), 'state': m['state']} for m in mos], 'out': out, 'kg': kg,
        'lot': ', '.join(lot['name'] for lot in lots), 'picking': shipped['name'] if shipped else (picks[0]['name'] if picks else ''),
        'delivered': delivered, 'created': created, 'prodEnd': prod_end, 'produced': produced,
        'lead': mins(created, delivered or (produced and prod_end) or now), 'steps': steps, 'route': route, 'timeline': timeline,
        'materials': materials, 'cost': cost, 'perKg': cost['total'] / kg if kg else None,
        'quality': [{'title': q['title'], 'value': q['measure'] if q['test_type'] == 'measure' else None, 'unit': q['norm_unit'] or '',
                     'ok': q['quality_state'] == 'pass'} for q in quality],
        'team': len(people), 'ts': now, 'source': 'odoo',  # public screen: how many people, not who (labour € is shown next to it)
    }


class ExpometalFlow(http.Controller):
    # Public screen of a Kioda dashboard (screen = 'flow'): only served to a device with access (kioda.dashboards.devices).

    def _authorized(self, token):
        if not token:
            return False
        return bool(request.env['kioda.dashboards.devices'].sudo().search_count(
            [('token', '=', token), ('has_access', '=', True), ('dashboard_id.screen', '=', 'flow')]))

    @http.route(['/flow/v5', '/flow/v5/'], type='http', auth='public', methods=['GET'])
    def line(self, token=None, **kw):
        if not self._authorized(token):
            return request.render('kioda_dashboards.not_found', {'uuid': 'device-not-authorized'})
        with open(file_path(PAGE + 'index.html'), encoding='utf-8') as f:
            html = f.read()
        # relative files (main.js, line.css…) resolve from the module's static folder; the page polls Odoo for data
        # (the token travels in the path so the screen's own fetch('<url>?picking=…') keeps working)
        cfg = json.dumps({'data': f'/flow/v5/data/{token}', 'summary': f'/flow/v5/summary/{token}', 'poll': POLL_MS})
        html = html.replace('<head>', f'<head><base href="/{PAGE}"><script>window.FLOW_CFG = {cfg};</script>', 1)
        return request.make_response(html, headers=[('Content-Type', 'text/html; charset=utf-8'), ('Cache-Control', 'no-cache')])

    @http.route('/flow/v5/data/<token>', type='http', auth='public', methods=['GET'])
    def data(self, token, **kw):
        if not self._authorized(token):
            return request.not_found()
        return request.make_json_response(snapshot(request.env), headers=[('Cache-Control', 'no-store')])

    @http.route('/flow/v5/summary/<token>', type='http', auth='public', methods=['GET'])
    def order_summary(self, token, picking=None, **kw):
        if not self._authorized(token):
            return request.not_found()
        return request.make_json_response(summary(request.env, picking_id=int(picking) if picking and picking.isdigit() else None),
                                          headers=[('Cache-Control', 'no-store')])
