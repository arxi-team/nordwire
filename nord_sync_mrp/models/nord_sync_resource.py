# -*- coding: utf-8 -*-
from odoo import api, fields, models


class NordSyncResource(models.Model):
    """The MO & Work Order rules of a Core resource (overlap policy, block of a
    change of MO, machine working without MO), mirrored here with the rest of
    its snapshot.

    The work center's rules are authored in Odoo and mirrored to the Core on
    every work center write; this is the way back: a change made on the Core
    (or the Cloud, which reaches it through the Core) is applied to the work
    centers mapped to the resource, so no side overrides another the next
    time it writes.
    """
    _inherit = 'nord_sync.resource'

    nord_sync_overlap_policy = fields.Selection([
        ('close_previous', 'One session at a time'),
        ('allow_parallel', 'Allow parallel sessions'),
    ], string='Overlapping Sessions', readonly=True)
    nord_sync_prevent_mo_change = fields.Boolean(string='Block MO Change If Running', readonly=True)
    nord_sync_unassigned_behavior = fields.Selection([
        ('first_scheduled', 'Start 1st Scheduled MO'),
        ('unassigned_timesheets', 'Create Unassigned Timesheets'),
    ], string='Machine Working Without MO', readonly=True)

    @api.model
    def _nord_sync_upsert_from_core(self, company, resources_payload):
        Resource = self.sudo().with_context(active_test=False)
        known = {
            resource.uid: resource._nord_sync_mo_rules()
            for resource in Resource.search([('company_id', '=', company.id)])
            if resource.nord_sync_overlap_policy
        }
        result = super()._nord_sync_upsert_from_core(company, resources_payload)
        for item in resources_payload or []:
            uid = item.get('uid')
            if not uid or not item.get('timesheet_overlap_policy'):
                continue
            resource = Resource.search([('company_id', '=', company.id), ('uid', '=', uid)], limit=1)
            if not resource:
                continue
            resource.write({
                'nord_sync_overlap_policy': item['timesheet_overlap_policy'],
                'nord_sync_prevent_mo_change': bool(item.get('prevent_mo_change_if_running')),
                'nord_sync_unassigned_behavior': item.get('unassigned_work_behavior') or 'first_scheduled',
            })
            # Only what the Core changed since the last snapshot is applied: the
            # first one seen just records the values (Odoo keeps what it authored).
            before = known.get(uid)
            if before:
                resource._nord_sync_apply_mo_rules_to_workcenters(
                    {key: value for key, value in resource._nord_sync_mo_rules().items() if before[key] != value},
                )
        return result

    def _nord_sync_mo_rules(self):
        self.ensure_one()
        return {
            'nord_sync_mo_change_behavior': (
                'start_without_close' if self.nord_sync_overlap_policy == 'allow_parallel' else 'close_and_open'
            ),
            'nord_sync_prevent_mo_change_if_running': self.nord_sync_prevent_mo_change,
            'nord_sync_unassigned_work_behavior': self.nord_sync_unassigned_behavior,
        }

    def _nord_sync_apply_mo_rules_to_workcenters(self, changed):
        """`changed`: the work center fields (name -> value) the Core changed."""
        self.ensure_one()
        if not changed:
            return
        workcenters = self.env['mrp.workcenter'].sudo().search([
            ('resource_id.nord_sync_resource_id', 'in', self.ids), ('company_id', '=', self.company_id.id),
        ])
        for workcenter in workcenters:
            vals = {
                field: value for field, value in changed.items()
                if workcenter._nord_sync_effective_rule(field) != value
            }
            if vals:
                workcenter.write(vals)
