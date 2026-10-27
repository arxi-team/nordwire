# -*- coding: utf-8 -*-
from odoo import _, fields, models


class StockPicking(models.Model):
    """Nordwire Source for stock.picking — same minimal shape as
    maintenance.request (nord_sync_maintenance): create-only Automation Rule, no product/
    declaration/result push, own _nord_sync_payload only (the create/enqueue
    plumbing is nord_sync.notify.mixin, shared by every source). `operation_type`
    in the payload is what tells the Core which nord.job.type to use — never
    hardcoded Core-side.
    """
    _name = 'stock.picking'
    _inherit = ['stock.picking', 'nord_sync.notify.mixin']

    def _nord_sync_payload(self):
        """Payload sent to the Core when this picking is created.

        name comes from _nord_sync_configurable_payload(), per-company
        selectable (default: on, unchanged behavior). operation_type stays
        hardcoded — it's a constant, not a field read.

        Keys:
            operation_type (str): always 'inventory' — tells the Core which
                nord.job.type to use.
            production_source_res_ids (list[int], optional): the MOs this
                transfer delivers (same origin: the sale order both came
                from, or the MO itself for a simulated delivery), so the Core
                can queue it after the MO's last operation. Only when mrp is
                installed.
        """
        self.ensure_one()
        payload = {
            **self._nord_sync_configurable_payload(),
            'operation_type': 'inventory',
        }
        productions = self._nord_sync_productions()
        if productions:
            payload['production_source_res_ids'] = productions.ids
        return payload

    def _nord_sync_productions(self):
        self.ensure_one()
        if 'mrp.production' not in self.env or not self.origin or self.picking_type_code != 'outgoing':
            return self.env['mrp.production'] if 'mrp.production' in self.env else False
        return self.env['mrp.production'].sudo().search([
            ('company_id', '=', self.company_id.id), '|', ('name', '=', self.origin), ('origin', '=', self.origin),
        ])

    def _nord_sync_apply_granular_event(self, event_type, payload):
        """Work on this transfer is timed on the Core (its own machine/
        station port); here it only leaves a note — the transfer is still
        validated by hand in Odoo."""
        self.ensure_one()
        times = {key: fields.Datetime.to_datetime(payload[key]) for key in ('start_date', 'end_date') if payload.get(key)}
        # Applied by the inbox cron (no user timezone): fall back to the
        # company's working-hours timezone so the note reads in local time
        tz = self.env.user.tz or self.user_id.tz or self.company_id.resource_calendar_id.tz or 'UTC'
        local = {
            key: fields.Datetime.context_timestamp(self.with_context(tz=tz), value).strftime('%H:%M:%S')
            for key, value in times.items()
        }
        if event_type == 'session_start':
            body = _('Nord: expedition started at %s.', local.get('start_date', '-'))
        elif event_type == 'session_stop':
            body = _('Nord: expedition stopped at %s.', local.get('end_date', '-'))
        elif event_type == 'session_setup':
            minutes = (times['end_date'] - times['start_date']).total_seconds() / 60 if len(times) == 2 else 0
            body = _('Nord: setup before the expedition, %(start)s to %(end)s (%(minutes).1f min).',
                     start=local.get('start_date', '-'), end=local.get('end_date', '-'), minutes=minutes)
        else:
            return True, f'{event_type} ignored for a transfer.'
        self.message_post(body=body)
        return True, 'ok'
