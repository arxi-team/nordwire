# -*- coding: utf-8 -*-
from odoo import api, fields, models


class MrpWorkcenter(models.Model):
    """Resource Bridge: keeps edge.resource on the Core up to date on its
    own — independent of any mrp.bom, since a work center doesn't need a
    BOM to exist. Unlike product.product (which only reaches the Core
    lazily via BOM/MO association — see _get_or_create_nord_sync_product,
    to avoid flooding the Core with products never actually used in a job),
    the set of work centers is small and bounded, so syncing all of them
    eagerly doesn't risk flooding the Core DB.
    """
    _inherit = 'mrp.workcenter'

    resource_kind = fields.Selection([
        ('human', 'Human'),
        ('machine', 'Machine'),
        ('tool', 'Tool'),
    ], string='Nord Resource Kind', default='machine',
        help='What this work center represents on the Nord Core (edge.resource.resource_kind) — '
             'not native to mrp.workcenter, added for the Resource Bridge.',
    )

    # ── Nord Sync Autonomous Resource Policies ───────────────────────────────
    # Authored here, same as resource_kind above — mirrored onto the Core's
    # edge.resource by the Resource Bridge, never enforced client-side.

    nord_sync_autonomous_close = fields.Boolean(
        string='Autonomous Close',
        default=False,
        help='Let a port-driven Nord Alert on the Core close the job on this resource without '
             'a human clicking "Mark Done". Off by default — the Core keeps requiring a human action.',
    )
    nord_sync_granular_push = fields.Boolean(
        string='Granular Push to Client',
        default=False,
        help='Push work-session start/stop and job cancellation from the Core back to this '
             'work order in real time, not just the final result. Off by default — only the '
             'final result (Mark Done) reaches this workcenter, as today.',
    )
    nord_sync_contention_policy = fields.Selection([
        ('block', 'Block'),
        ('auto_close_previous', 'Auto-close Previous'),
    ], string='Resource Contention Policy', default='block', required=True,
        help='What the Core does when a new work session starts on this resource while another '
             'is still open: "Block" refuses the new session (current behavior); "Auto-close '
             'Previous" closes the open one first.',
    )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._nord_sync_notify('create')
        return records

    def write(self, vals):
        result = super().write(vals)
        self._nord_sync_notify('write')
        return result

    def unlink(self):
        self._nord_sync_notify('unlink')
        return super().unlink()

    def _nord_sync_notify(self, operation):
        for record in self:
            company = record.company_id or self.env.company
            config = self.env['nord_sync.config'].sudo()._get_for_company(company)
            if not config or not config.enabled or not config._is_source_enabled('mrp.production'):
                continue
            config._enqueue_and_notify('mrp.workcenter', record.id, operation, record._nord_sync_payload())

    def _nord_sync_payload(self):
        self.ensure_one()
        return {
            'name': self.name,
            'resource_kind': self.resource_kind,
            'autonomous_close': self.nord_sync_autonomous_close,
            'granular_push': self.nord_sync_granular_push,
            'contention_policy': self.nord_sync_contention_policy,
            'resource_calendar_attendances': [
                {
                    'dayofweek': att.dayofweek,
                    'hour_from': att.hour_from,
                    'hour_to': att.hour_to,
                    'day_period': att.day_period,
                }
                for att in self.resource_calendar_id.attendance_ids
            ] if self.resource_calendar_id else [],
        }
