# -*- coding: utf-8 -*-
from odoo import fields, models


class ResourceResource(models.Model):
    """Nordwire Resource Mapping lands here rather than on
    mrp.workcenter/hr.employee separately — both already carry their own
    resource_id (resource.mixin/hr native) pointing here, so one field
    covers every Odoo resource type at once, machine or human, with no
    custom view needed: the native Resources list already shows every
    resource.resource in one place.
    """
    _inherit = 'resource.resource'

    nord_sync_resource_id = fields.Many2many(
        'nord_sync.resource', string='Nord Core Resources',
        domain="[('company_id', '=', company_id)]",
        help='Which edge.resource(s) on the Nord Core this resource is. Several Core '
             'resources can feed the same work center (e.g. more than one physical machine '
             'reported as one Odoo resource) — any of them starting starts this resource\'s '
             'own work here too. The Resource/Employee Bridge only ever updates existing, '
             'already-mapped Core resources — it never creates one, so nothing syncs for '
             'this resource until at least one is set.',
    )
