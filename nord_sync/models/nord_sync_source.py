# -*- coding: utf-8 -*-
from odoo import fields, models


class NordSyncSource(models.Model):
    """One row per Nordwire Source this addon can bridge (mrp.production,
    sale.order, purchase.order, stock.picking, maintenance.request) — a
    small fixed catalog (data/nord_sync_sources.xml), not something a client
    creates. Every source's model/view/automation code is always installed
    together — they all live in this one addon now, rather than one addon
    per source; this table
    only exists so nord_sync.config.enabled_source_ids has something to
    Many2many against — the client picks which sources actually produce
    jobs (install wizard's Sources step), the rest stay installed but inert.
    """
    _name = 'nord_sync.source'
    _description = 'Nordwire Source'
    _order = 'name'

    name = fields.Char(required=True, help='Display label, e.g. "Manufacturing".')
    model = fields.Char(
        required=True, index=True,
        help='Technical source model, e.g. "mrp.production" — matched '
             "against a source's own _nord_sync_payload()-producing model.",
    )

    _sql_constraints = [
        ('model_unique', 'UNIQUE(model)', 'A Nordwire Source for this model already exists.'),
    ]
