# -*- coding: utf-8 -*-
from odoo import api, models


class MrpBom(models.Model):
    """BOM Bridge: pushes a full snapshot of this BOM (materials, output
    products including byproducts, operations) on every change — including
    changes to bom_line_ids/operation_ids, which are child records that
    never call write() on this parent (see mrp_bom_line.py/
    mrp_routing_workcenter.py, which notify via bom_id instead of
    themselves).
    """
    _inherit = 'mrp.bom'

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
            config._enqueue_and_notify('mrp.bom', record.id, operation, record._nord_sync_payload())

    def _nord_sync_payload(self):
        self.ensure_one()
        main_product = self.product_id or self.product_tmpl_id.product_variant_id
        product_lines = []
        if main_product:
            product_lines.append({
                'product': self._nord_sync_product_payload(main_product),
                'quantity': self.product_qty,
            })
        for byproduct in self.byproduct_ids:
            product_lines.append({
                'product': self._nord_sync_product_payload(byproduct.product_id),
                'quantity': byproduct.product_qty,
            })
        return {
            'name': self.display_name or self.code or 'BOM',
            'lines': [
                {
                    'product': self._nord_sync_product_payload(line.product_id),
                    'quantity': line.product_qty,
                    # Which operation/resource this material is consumed at — a
                    # Nord Sync Task (see the Workorder Bridge) only makes sense
                    # once that resource's real workorder exists. Blank when the
                    # line isn't tied to any operation (no resource to wait for).
                    'workcenter_source_res_id': line.operation_id.workcenter_id.id or False,
                }
                for line in self.bom_line_ids
            ],
            'product_lines': product_lines,
            'operations': [
                {
                    'name': operation.name,
                    'workcenter_source_res_id': operation.workcenter_id.id,
                    # time_cycle_manual is in minutes; nord.timesheet.expected_duration is hours.
                    'expected_duration': operation.time_cycle_manual / 60.0,
                }
                for operation in self.operation_ids
            ],
        }

    def _nord_sync_product_payload(self, product):
        return {
            'name': product.name,
            'default_code': product.default_code or False,
            'uom': product.uom_id.name,
        }


class MrpBomLine(models.Model):
    """A line is a child of mrp.bom — editing it never calls write() on the
    parent, so it notifies bom_id directly instead of itself (no own
    res_model entry in the queue; always res_model='mrp.bom').
    """
    _inherit = 'mrp.bom.line'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.mapped('bom_id')._nord_sync_notify('write')
        return records

    def write(self, vals):
        boms = self.mapped('bom_id')
        result = super().write(vals)
        boms._nord_sync_notify('write')
        return result

    def unlink(self):
        boms = self.mapped('bom_id')
        result = super().unlink()
        boms._nord_sync_notify('write')
        return result


class MrpRoutingWorkcenter(models.Model):
    """Same reasoning as MrpBomLine above — an operation is a child of
    mrp.bom, notifies via bom_id.
    """
    _inherit = 'mrp.routing.workcenter'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.mapped('bom_id')._nord_sync_notify('write')
        return records

    def write(self, vals):
        boms = self.mapped('bom_id')
        result = super().write(vals)
        boms._nord_sync_notify('write')
        return result

    def unlink(self):
        boms = self.mapped('bom_id')
        result = super().unlink()
        boms._nord_sync_notify('write')
        return result
