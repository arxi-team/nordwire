# -*- coding: utf-8 -*-
from odoo import fields, models


class ResourceResource(models.Model):
    """Nord Sync Resource Mapping (ADR 0026) lands here rather than on
    mrp.workcenter/hr.employee separately — both already carry their own
    resource_id (resource.mixin/hr native) pointing here, so one field
    covers every Odoo resource type at once, machine or human, with no
    custom view needed: the native Resources list already shows every
    resource.resource in one place.
    """
    _inherit = 'resource.resource'

    nord_sync_resource_id = fields.Many2one(
        'nord_sync.resource', string='Nord Core Resource',
        domain="[('company_id', '=', company_id)]",
        help='Which edge.resource on the Nord Core this resource is. The Resource/Employee '
             'Bridge only ever updates an existing, already-mapped Core resource — it never '
             'creates one, so nothing syncs for this resource until this is set.',
    )
