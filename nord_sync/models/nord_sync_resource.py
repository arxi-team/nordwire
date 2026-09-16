# -*- coding: utf-8 -*-
from odoo import api, fields, models


class NordSyncResource(models.Model):
    """Nordwire Resource Mapping: a read-only local mirror of
    the Core's edge.resource list, pushed down whole on every Core
    heartbeat (POST /nord_sync/api/v1/resources) — never a delta, so a
    missed tick self-heals on the next one. This is the pick list behind
    resource.resource.nord_sync_resource_id: a human links their own
    mrp.workcenter/hr.employee to one of these by hand, instead of the
    Resource/Employee Bridge auto-creating or guess-matching a Core
    resource by name the way it used to (real duplicate-data bug that
    caused).

    Only ever written by the controller (sudo, on receipt of the Core's
    push) — never created/edited through the UI directly, hence no manager
    write access in ir.model.access.csv.
    """
    _name = 'nord_sync.resource'
    _description = 'Nordwire Resource'
    _rec_name = 'complete_name'
    _order = 'complete_name'

    uid = fields.Char(required=True, index=True, help='The edge.resource.uid on the Core — the join key.')
    complete_name = fields.Char(
        required=True,
        help='Full hierarchical path (e.g. "Line 1 / Motor"), not just the bare name — '
             'edge.resource.name is not unique per company, complete_name is what tells '
             'two same-named resources apart in the mapping pick list.',
    )
    resource_kind = fields.Selection([
        ('human', 'Human'),
        ('machine', 'Machine'),
        ('tool', 'Tool'),
    ], string='Type')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)

    _company_uid_unique = models.Constraint(
        'UNIQUE(company_id, uid)',
        'A Nordwire Resource with this uid already exists for this company.',
    )

    @api.model
    def _nord_sync_upsert_from_core(self, company, resources_payload):
        """Applies the Core's full resource-list snapshot for one company —
        find-or-create by (company, uid), full field overwrite each time
        (the Core is always authoritative here, same posture as every other
        Core->client push in this bridge).

        Keys (per dict in `resources_payload`):
            uid (str, required): skipped when absent — can't upsert without
                a join key.
            complete_name (str, optional): defaults to '' when absent.
            resource_kind (str, optional): defaults to False.
            active (bool, optional): defaults to True.
        """
        Resource = self.sudo()
        for item in resources_payload or []:
            uid = item.get('uid')
            if not uid:
                continue
            vals = {
                'complete_name': item.get('complete_name') or '',
                'resource_kind': item.get('resource_kind') or False,
                'active': item.get('active', True),
            }
            existing = Resource.search([('company_id', '=', company.id), ('uid', '=', uid)], limit=1)
            if existing:
                existing.write(vals)
            else:
                Resource.create({**vals, 'uid': uid, 'company_id': company.id})
