# -*- coding: utf-8 -*-
import logging
from datetime import datetime, timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class MrpWorkcenter(models.Model):
    """Resource Bridge: keeps edge.resource on the Core up to date on its
    own — independent of any mrp.bom, since a work center doesn't need a
    BOM to exist. Unlike product.product (which only reaches the Core
    lazily via BOM/MO association — see _get_or_create_nord_sync_product,
    to avoid flooding the Core with products never actually used in a job),
    the set of work centers is small and bounded, so syncing all of them
    eagerly doesn't risk flooding the Core DB. A support model of the
    mrp.production source, not a toggle-able source of its own — see
    _nord_sync_source_key below.
    """
    _inherit = ['mrp.workcenter', 'nord_sync.notify.mixin']

    # ── Nordwire Resource Mapping ───────────────────────────────────────────
    # The real field lives on resource.resource (nord_sync_mrp/models/
    # resource_resource.py) — shared with hr.employee via the resource_id both
    # already carry, see that file's own docstring for why. Exposed here too,
    # related+editable, purely so mapping a work center doesn't require
    # leaving this form for the generic Resources screen (ADR 0026's own
    # mapping mechanism is unchanged — this is only a second, more
    # convenient door onto the same field).

    nord_sync_resource_id = fields.Many2many(
        'nord_sync.resource', string='Connected Nord Resources',
        related='resource_id.nord_sync_resource_id', readonly=False,
        help='Select the Nord resource(s) linked to this work center — more than one when '
             'several physical Nord resources feed it. This connection is required for '
             'production data to be synchronized with Nord.',
    )

    nord_sync_current_production_id = fields.Many2one(
        'mrp.production', string='Current Manufacturing Order',
        tracking=True, copy=False,
        domain="[('company_id', '=', company_id), ('state', 'in', ('confirmed', 'progress', 'to_close'))]",
        help='Manufacturing Order currently being worked on this Work Center.',
    )
    nord_sync_mo_change_behavior = fields.Selection([
        ('close_and_open', 'Close current timesheet and open new on new MO'),
        ('start_without_close', 'Start new WO without closing previous'),
    ], string='MO Change Behavior',
        help='Behavior when changing the MO on this work center. If unset, uses the company configuration.',
    )
    nord_sync_prevent_mo_change_if_running = fields.Boolean(
        string='Block MO Change If Running',
        help='Prevents changing the MO if this work center already has a work order in progress (requires stop first). If unset, uses the company configuration.',
    )
    nord_sync_unassigned_work_behavior = fields.Selection([
        ('first_scheduled', 'Start 1st Scheduled MO'),
        ('unassigned_timesheets', 'Create Unassigned Timesheets'),
    ], string='Machine Working Without MO',
        help='Behavior when the machine works without an MO selected. If unset, uses the company configuration.',
    )

    # ── Nordwire Autonomous Resource Policies ───────────────────────────────
    # Authored here — mirrored onto the Core's edge.resource by the Resource
    # Bridge, never enforced client-side.

    nord_sync_autonomous_close = fields.Boolean(
        string='Let Nord Finish Jobs Automatically',
        default=False,
        help='Let a Nord sensor or alert finish the job on this resource by itself, '
             'without anyone pressing "Mark Done" on the Nord side first. '
             'Does not change what happens in Odoo: any job someone finishes on Nord, '
             'whether by hand or automatically, still closes this production order here.',
    )
    nord_sync_granular_push = fields.Boolean(
        string='Sync Work Progress to Odoo',
        default=False,
        help='Send job progress from Nord to Odoo as it happens, not just the final result. '
             'This includes starting and stopping work and cancelling jobs, so changes made '
             'in Nord are reflected in Odoo while the job is still being worked on.',
    )
    nord_sync_contention_policy = fields.Selection([
        ('block', "Don't Start Another Job"),
        ('auto_close_previous', 'Finish the Previous Job Automatically'),
    ], string='When This Resource Is Already in Use', default='block', required=True,
        help='What happens when someone tries to start a new job on this resource while '
             'another one is still being worked.',
    )
    nord_sync_chain_close = fields.Boolean(
        string='Finish Previous Steps Automatically',
        default=False,
        help='Automatically finish the previous step when the next step of the same job '
             'starts on another resource. This is useful when operators move to the next step '
             'without manually stopping the previous one.'
        ,
    )
    nord_sync_mirror_mode = fields.Boolean(
        string='Sync Job Status from Odoo',
        default=False,
        help='When enabled, job status changes made in Odoo are also sent to Nord. '
             'This keeps Nord aligned when a job is confirmed, started, or completed in Odoo. '
             'Job cancellations are synchronized regardless of this setting.',
    )
    nord_sync_close_notify_only = fields.Boolean(
        string="Review Quantities Before Closing",
        default=False,
        help="When a job finishes on Nord, don't apply the declared quantities to this "
             "production order automatically — just post a note here with how many "
             "declarations were recorded, and leave marking it done to a person. Use this "
             "when the quantities Nord declares for this resource can't be trusted yet.",
    )

    nord_sync_stop_tracking = fields.Boolean(
        string='Track Stops and Changeovers',
        default=False,
        help='When the machine stops in the middle of a job, log that stop on the work order '
             'as an unjustified stop (until someone gives it a reason); when it starts again, '
             'carry on with the same production order. When the operator stops another '
             'tracked work center and then starts this one, the time in between is logged '
             'as setup of this work center instead of a stop of the other one.',
    )

    nord_sync_time_chart = fields.Json(
        string='Nord Times Chart', compute='_compute_nord_sync_time_chart',
        help='Placeholder for the "Nord Times" chart on the Nordwire tab: the widget '
             'fetches its own data (nord_sync_time_chart_data).',
    )

    def _compute_nord_sync_time_chart(self):
        self.nord_sync_time_chart = False

    nord_sync_capacity_per_hour = fields.Float(
        string='Capacity per Hour',
        help='Units this work center should produce in one hour of the work day, the '
             'reference for the Performance of the machine overview (OEE). Left at 0, it '
             'is estimated from the expected duration of today\'s work orders.',
    )
    nord_sync_machine_overview = fields.Json(
        string='Machine Overview', compute='_compute_nord_sync_machine_overview',
        help='Placeholder for the machine overview (OEE, working hours, declarations, '
             'OEE by hour): the widget fetches its own data (nord_sync_machine_overview_data).',
    )

    def _compute_nord_sync_machine_overview(self):
        self.nord_sync_machine_overview = False

    # ── Automatic Idle/Tooling Segments ──────────────────────────────────────
    # Authored here purely for a familiar place to configure it — the Core
    # never actually needs client data to compute either segment (it's pure
    # session timing on edge.resource, ADR 0030), same "config lives on the
    # workcenter, computation doesn't need it" split as the rest of this
    # bridge's autonomy policies. Also outside Control Mode: a reporting/OEE
    # concern, not floor-event or job-state authority.

    nord_sync_auto_idle_segments = fields.Boolean(
        string='Record Idle Time Automatically',
        default=False,
        help='Automatically record the time between work sessions as idle time. '
             'This helps account for periods when the resource is not actively working on a job. '
             'Idle time is not counted as worked time.',
    )
    nord_sync_idle_segment_reason_name = fields.Char(
        string='Idle Time Reason',
        default='Idle',
        help='Unused for now — downtime segments open without a reason.',
    )
    nord_sync_auto_tooling_segments = fields.Boolean(
        string='Track Tooling Time Automatically',
        default=False,
        help='Unused for now.',
    )
    nord_sync_tooling_segment_reason_name = fields.Char(
        string='Tooling Time Reason',
        default='Tooling',
        help='Unused for now.',
    )

    # Odoo leaves the MO rules free (parallel work orders included); Nord has a
    # single active session per resource, so a change of MO closes the previous
    # one and the Core's own "block" policy takes the place of the block flag.
    NORD_SYNC_CONTROL_MODE_PRESETS = {
        'odoo': {
            'nord_sync_autonomous_close': False, 'nord_sync_granular_push': False,
            'nord_sync_contention_policy': 'block', 'nord_sync_chain_close': False,
        },
        'nord': {
            'nord_sync_autonomous_close': True, 'nord_sync_granular_push': True,
            'nord_sync_contention_policy': 'auto_close_previous', 'nord_sync_chain_close': True,
            'nord_sync_mo_change_behavior': 'close_and_open',
            'nord_sync_prevent_mo_change_if_running': False,
        },
    }

    nord_sync_control_mode = fields.Selection([
        ('odoo', 'Odoo controls production'), ('nord', 'Nord controls production'), ('custom', 'Custom settings'),
    ], string='Production Control', compute='_compute_nord_sync_control_mode', inverse='_inverse_nord_sync_control_mode',
        help='Choose how production activity is controlled for this resource. '
             'Odoo controls production keeps job activity under Odoo control. '
             'Nord controls production lets Nord manage production activity automatically. '
             'Custom settings lets you configure each production behavior individually.',
    )

    nord_sync_mo_parallel = fields.Boolean(
        compute='_compute_nord_sync_mo_parallel',
        help='Work orders of different MOs run side by side here (2.2), so there is no '
             'running work order to block a change of MO for.',
    )
    nord_sync_mo_running = fields.Boolean(
        compute='_compute_nord_sync_mo_running',
        help='The work order of the current MO here has its timer running.',
    )

    @api.depends(
        'nord_sync_autonomous_close', 'nord_sync_granular_push',
        'nord_sync_contention_policy', 'nord_sync_chain_close',
        'nord_sync_mo_change_behavior', 'nord_sync_prevent_mo_change_if_running',
    )
    def _compute_nord_sync_control_mode(self):
        for workcenter in self:
            # The MO rules count with what applies (the company's value when
            # the work center's own is empty), not with the raw field.
            current = {
                field: workcenter[field] for field in self.NORD_SYNC_CONTROL_MODE_PRESETS['odoo']
            }
            current['nord_sync_mo_change_behavior'] = workcenter._nord_sync_effective_mo_change_behavior()
            current['nord_sync_prevent_mo_change_if_running'] = workcenter._nord_sync_effective_prevent_mo_change()
            workcenter.nord_sync_control_mode = next(
                (mode for mode, preset in self.NORD_SYNC_CONTROL_MODE_PRESETS.items()
                 if all(current[field] == value for field, value in preset.items())),
                'custom',
            )

    @api.depends('nord_sync_current_production_id')
    def _compute_nord_sync_mo_running(self):
        for workcenter in self:
            workorders = workcenter.nord_sync_current_production_id.workorder_ids.filtered(
                lambda wo: wo.workcenter_id == workcenter
            )
            workcenter.nord_sync_mo_running = any(wo._nord_sync_is_running() for wo in workorders)

    def _nord_sync_effective_mo_change_behavior(self):
        self.ensure_one()
        config = self.env['nord_sync.config'].sudo()._get_for_company(self.company_id)
        return (
            self.nord_sync_mo_change_behavior
            or (config and config.nord_sync_mo_change_behavior)
            or 'close_and_open'
        )

    def _nord_sync_effective_prevent_mo_change(self):
        """3.1 is an option of 2.1 (the previous work order is closed): with
        parallel work orders (2.2) there is nothing to block."""
        self.ensure_one()
        if self._nord_sync_effective_mo_change_behavior() == 'start_without_close':
            return False
        config = self.env['nord_sync.config'].sudo()._get_for_company(self.company_id)
        return bool(
            self.nord_sync_prevent_mo_change_if_running
            or (config and config.nord_sync_prevent_mo_change_if_running)
        )

    def _nord_sync_effective_unassigned_behavior(self):
        self.ensure_one()
        config = self.env['nord_sync.config'].sudo()._get_for_company(self.company_id)
        return (
            self.nord_sync_unassigned_work_behavior
            or (config and config.nord_sync_unassigned_work_behavior)
            or 'first_scheduled'
        )

    def _nord_sync_effective_rule(self, field):
        """What applies for one of the three MO & Work Order rules, by field name."""
        self.ensure_one()
        return {
            'nord_sync_mo_change_behavior': self._nord_sync_effective_mo_change_behavior,
            'nord_sync_prevent_mo_change_if_running': self._nord_sync_effective_prevent_mo_change,
            'nord_sync_unassigned_work_behavior': self._nord_sync_effective_unassigned_behavior,
        }[field]()

    @api.depends('nord_sync_mo_change_behavior', 'company_id')
    def _compute_nord_sync_mo_parallel(self):
        for workcenter in self:
            workcenter.nord_sync_mo_parallel = (
                workcenter._nord_sync_effective_mo_change_behavior() == 'start_without_close'
            )

    def _inverse_nord_sync_control_mode(self):
        for workcenter in self:
            preset = self.NORD_SYNC_CONTROL_MODE_PRESETS.get(workcenter.nord_sync_control_mode)
            if preset:
                workcenter.write(preset)
        # write() on an inverse field caches the literal value just assigned
        # (e.g. picking 'custom' explicitly with the four fields still
        # matching a preset) rather than recomputing — invalidate so the
        # next read always reflects the real fields, never a stale label.
        self.invalidate_recordset(['nord_sync_control_mode'])

    @api.model_create_multi
    def create(self, vals_list):
        self._nord_sync_apply_default_control_mode(vals_list)
        records = super().create(vals_list)
        records._nord_sync_notify('create')
        return records

    def _nord_sync_apply_default_control_mode(self, vals_list):
        """Fills in a new work center's four floor-event fields from its
        company's nord_sync_default_workcenter_control_mode (nord_sync.config)
        when the vals dict says nothing at all about Control Mode — checked
        before super().create() runs, not after, since these are the same
        fields _compute_nord_sync_control_mode itself depends on. Only ever a
        starting point: a vals dict naming nord_sync_control_mode itself, or
        any one of the four fields directly (its own value, its own factory
        default, an XML data file, another addon), is left alone untouched —
        explicit always wins, and a work center already created never
        revisits this, so changing the company default later has no effect on it.
        """
        override_keys = {'nord_sync_control_mode', *self.NORD_SYNC_CONTROL_MODE_PRESETS['odoo']}
        Company = self.env['res.company']
        for index, vals in enumerate(vals_list):
            if not override_keys.isdisjoint(vals):
                continue
            company = Company.browse(vals['company_id']) if vals.get('company_id') else self.env.company
            config = self.env['nord_sync.config'].sudo()._get_for_company(company)
            preset = config and self.NORD_SYNC_CONTROL_MODE_PRESETS.get(
                config.nord_sync_default_workcenter_control_mode,
            )
            if preset:
                # Copy before updating — vals is the caller's own dict object
                # (create() may be called with a vals_list a caller reuses
                # across several create() calls), and mutating it in place
                # would bake this company's preset into it permanently, the
                # same class of bug already fixed once in mrp.production.create.
                vals_list[index] = {**vals, **preset}

    def write(self, vals):
        if vals.get('nord_sync_mo_change_behavior') == 'start_without_close':
            vals = {**vals, 'nord_sync_prevent_mo_change_if_running': False}
        if 'nord_sync_current_production_id' in vals and not self.env.context.get('nord_sync_skip_mo_change'):
            new_mo_id = vals.get('nord_sync_current_production_id')
            for workcenter in self:
                old_mo = workcenter.nord_sync_current_production_id
                if old_mo.id != new_mo_id:
                    workcenter._nord_sync_on_change_current_mo(old_mo, new_mo_id)
        result = super().write(vals)
        self._nord_sync_notify('write')
        return result

    def _nord_sync_on_change_current_mo(self, old_mo, new_mo_id):
        self.ensure_one()

        # 3.1: Verificar se tem WO a correr e setting ativo
        prevent_if_running = self._nord_sync_effective_prevent_mo_change()

        # The block is for people: whatever the Core sends is never refused here.
        from_core = self.env.context.get('nord_sync_skip_prevent_check') or self.env.context.get('nord_sync_from_core')
        if prevent_if_running and not from_core:
            has_running_wo = bool(self.env['mrp.workorder'].search([
                ('workcenter_id', '=', self.id),
                ('state', '=', 'progress'),
            ], limit=1))
            has_open_timesheet = bool(self.env['mrp.workcenter.productivity'].search([
                ('workcenter_id', '=', self.id),
                ('date_end', '=', False),
                ('nord_sync_downtime_kind', '=', False),
            ], limit=1))
            if has_running_wo or has_open_timesheet:
                raise UserError(_(
                    "Work center '%(wc)s' already has a work order in progress. "
                    "You must stop it before selecting another Manufacturing Order.",
                    wc=self.display_name or self.name,
                ))

        # 2: Reação na mudança da MO anterior
        behavior = self._nord_sync_effective_mo_change_behavior()
        if old_mo:
            if behavior == 'close_and_open':
                # 2.1: Fechar timesheet atual e parar WO anterior
                # The work order whose Start triggered this change has just
                # opened its own timesheet: leave it open.
                starting_ids = self.env.context.get('nord_sync_starting_workorder_ids') or []
                open_timesheets = self.env['mrp.workcenter.productivity'].search([
                    ('workcenter_id', '=', self.id),
                    ('date_end', '=', False),
                    ('workorder_id', 'not in', starting_ids),
                ])
                if open_timesheets:
                    open_timesheets.write({'date_end': fields.Datetime.now()})
                running_wos = old_mo.workorder_ids.filtered(
                    lambda wo: wo.workcenter_id == self and wo.state == 'progress'
                )
                for rwo in running_wos:
                    rwo.with_context(nord_sync_from_core=True).end_previous(doall=True)
                    # Whatever changed the MO (PDA, form, Start of another work
                    # order), the Nord side hears the previous one stopped;
                    # nothing goes out when the change came from the Core itself.
                    rwo._nord_sync_notify_floor_event('stop')
            elif behavior == 'start_without_close':
                # 2.2: Dar start em nova WO sem fechar a anterior
                pass

            # A setup line of the previous MO is not running work: it goes
            # with the MO whichever way the previous work order is treated.
            self._nord_sync_close_setup_lines(old_mo.workorder_ids)

        # 3, 3.2, 5.2: Atribuir nova MO
        if new_mo_id:
            new_mo = self.env['mrp.production'].browse(new_mo_id)
            target_wo = self._nord_sync_get_or_create_workorder(new_mo)

            # 5.2: Atribuir timesheets unassigned abertos à nova WO
            unassigned_timesheets = self.env['mrp.workcenter.productivity'].search([
                ('workcenter_id', '=', self.id),
                ('nord_sync_is_unassigned', '=', True),
                ('date_end', '=', False),
            ])
            if unassigned_timesheets:
                unassigned_timesheets.write({
                    'workorder_id': target_wo.id,
                    'nord_sync_is_unassigned': False,
                })
                if target_wo.state != 'progress':
                    target_wo.state = 'progress'

            if self.env.context.get('nord_sync_from_wo_start'):
                # The work order is starting itself (Start in Odoo).
                return
            if self.env.context.get('nord_sync_from_core'):
                # The machine is already working: the MO is running, not only picked.
                self._nord_sync_start_workorder(target_wo)
            elif self.env.context.get('nord_sync_pda_setup'):
                # A scan on the PDA: the work center is in setup for the MO until Start.
                self._nord_sync_setup_workorder(target_wo)
            # Anything else (the work center's form) only identifies the MO:
            # Start / Stop on the work center run it.

    def _nord_sync_get_or_create_workorder(self, production):
        """3.2: the work order of this work center on the MO that is still to
        do; 3: none, so one is created on this work center."""
        self.ensure_one()
        workorder = production.workorder_ids.filtered(
            lambda wo: wo.workcenter_id == self and wo.state not in ('done', 'cancel')
        ).sorted(lambda wo: (wo.sequence, wo.id))[:1]
        return workorder or self.env['mrp.workorder'].create({
            'name': self.name,
            'production_id': production.id,
            'workcenter_id': self.id,
            'product_uom_id': production.product_uom_id.id,
            'consumption': production.consumption,
        })

    def _nord_sync_close_setup_lines(self, workorders):
        """Ends the open setup lines of this work center on the MO(s) of
        `workorders`: whichever of the MO's work orders the Core opened the
        setup on (it may not be the one this work center runs, e.g. one
        already done)."""
        lines = self.env['mrp.workcenter.productivity'].search([
            ('workcenter_id', '=', self.id), ('workorder_id.production_id', 'in', workorders.production_id.ids),
            ('date_end', '=', False), ('nord_sync_downtime_kind', '=', 'setup'),
        ])
        lines.write({'date_end': fields.Datetime.now()})
        return lines

    def _nord_sync_setup_workorder(self, workorder):
        """The work center is set up for `workorder` (its MO was scanned on the PDA): a
        work center mapped to the Core tells the Core, which opens the setup
        segment and shows it back as a live line (same as a PDA scan always
        did); one without Nord gets the setup line here. A work order already
        running keeps running."""
        self.ensure_one()
        # A work order stopped earlier stays 'progress' in Odoo: only one with
        # its timer running is already on the machine.
        if workorder.state in ('done', 'cancel') or workorder._nord_sync_is_running():
            return
        if self.nord_sync_resource_id:
            workorder._nord_sync_notify_floor_event('setup')
            return
        if not workorder.time_ids.filtered(lambda t: not t.date_end and t.nord_sync_downtime_kind == 'setup'):
            self.env['mrp.workcenter.productivity'].create(
                workorder._nord_sync_downtime_line_vals(
                    {'start_date': fields.Datetime.now(), 'nord_timesheet_id': 0}, 'setup',
                ),
            )

    def _nord_sync_start_workorder(self, workorder):
        """Starts `workorder` here and opens its timesheet, whoever asked."""
        self.ensure_one()
        if workorder.state not in ('progress', 'done', 'cancel'):
            workorder.with_context(
                nord_sync_skip_confirm=True,
                nord_sync_from_core=True,
                nord_sync_from_wo_start=True,
            )._nord_sync_button_start_bypassing_employee_check()
        elif workorder.state == 'progress':
            open_session = workorder.time_ids.filtered(lambda t: not t.date_end)
            if not open_session:
                self.env['mrp.workcenter.productivity'].create({
                    **workorder._prepare_timeline_vals(workorder.duration, fields.Datetime.now()),
                    'user_id': False,
                    'employee_id': False,
                })
        # A Start pressed in Odoo already tells the Nord side (button_start);
        # any other way of starting has to as well.
        if workorder.state == 'progress':
            workorder._nord_sync_notify_floor_event('start')

    def action_nord_sync_start(self):
        """Start of the MO the work center is on: its work order starts (one
        is created when the MO has none here) and the setup ends."""
        for workcenter in self:
            production = workcenter.nord_sync_current_production_id
            if not production:
                raise UserError(_("Pick the Manufacturing Order of '%s' first.", workcenter.display_name))
            workorder = workcenter._nord_sync_get_or_create_workorder(production)
            workcenter._nord_sync_close_setup_lines(workorder)
            workcenter._nord_sync_start_workorder(workorder)

    def action_nord_sync_stop(self):
        """Stop of the MO the work center is on: its running work orders
        pause and the work center is left without MO (nothing is on it)."""
        for workcenter in self:
            production = workcenter.nord_sync_current_production_id
            if not production:
                continue
            workorders = production.workorder_ids.filtered(lambda wo: wo.workcenter_id == workcenter)
            running = workorders.filtered(lambda wo: wo.state == 'progress')
            for workorder in running:
                # Same as the change of MO: the timer ends here (a line with no
                # employee is not one Shop Floor's own pause would find) and the
                # Nord side hears the stop.
                workorder.with_context(nord_sync_from_core=True).end_previous(doall=True)
                workorder._nord_sync_notify_floor_event('stop')
            running._nord_sync_update_wc_current_production_on_stop()
            workcenter._nord_sync_close_setup_lines(workorders)
            if workcenter.nord_sync_current_production_id == production:
                workcenter.with_context(nord_sync_skip_mo_change=True).nord_sync_current_production_id = False

    def _nord_sync_close_previous_operations(self, workorder, start_date=None):
        """Chain Close (nord_sync_chain_close, on the work center of the EARLIER operation): `workorder`
        starting ends the Nord time lines still open on the earlier operations of the same MO, so the
        operations of an MO never run at the same time."""
        self.ensure_one()
        start = fields.Datetime.to_datetime(start_date) if start_date else fields.Datetime.now()
        earlier = workorder.production_id.workorder_ids.filtered(
            lambda w: w != workorder and w.workcenter_id.nord_sync_chain_close
            and (w.sequence, w.id) < (workorder.sequence, workorder.id))
        for line in earlier.time_ids.filtered(lambda t: not t.date_end and t.nord_sync_timesheet_id):
            line.date_end = max(start, line.date_start)

    def _nord_sync_close_open_downtime(self, end_date=None):
        """A stop line of this work center still open ends where the machine starts again."""
        self.ensure_one()
        end = fields.Datetime.to_datetime(end_date) if end_date else fields.Datetime.now()
        for line in self.env['mrp.workcenter.productivity'].sudo().search([
            ('workcenter_id', '=', self.id), ('date_end', '=', False), ('nord_sync_downtime_kind', '!=', False),
        ]):
            line.date_end = max(end, line.date_start)

    def _nord_sync_apply_downtime_event(self, event_type, payload):
        """session_downtime_open / session_downtime / session_downtime_cancel of a Nord resource
        with no job (a machine stopped with nothing assigned to it). The same stop lines a work
        order gets, on the work order of the work center's current MO when it has one, else with no
        work order (like the unassigned work lines).

        Keys: see mrp.workorder._nord_sync_apply_granular_event.
        """
        self.ensure_one()
        workorder = self.nord_sync_current_production_id.workorder_ids.filtered(
            lambda w: w.workcenter_id == self and w.state not in ('done', 'cancel'))[:1]
        if workorder:
            return workorder._nord_sync_apply_granular_event(event_type, payload)
        nord_timesheet_id = payload.get('nord_timesheet_id')
        if not nord_timesheet_id:
            return False, 'Missing nord_timesheet_id'
        Productivity = self.env['mrp.workcenter.productivity'].sudo()
        line = Productivity.search([('nord_sync_timesheet_id', '=', nord_timesheet_id)], limit=1)
        if event_type == 'session_downtime_cancel':
            line.filtered(lambda t: not t.date_end).unlink()
            return True, 'ok'
        start_date, end_date = payload.get('start_date'), payload.get('end_date')
        if not start_date or (event_type == 'session_downtime' and not end_date):
            return False, 'Missing start_date/end_date'
        if event_type == 'session_downtime_open':
            if not line:
                Productivity.create(self._nord_sync_workcenter_downtime_vals(payload))
            return True, 'ok'
        if line and line.date_end:
            return True, 'Already logged.'
        if line:
            line.write({'date_start': start_date, 'date_end': end_date})
        else:
            Productivity.create(self._nord_sync_workcenter_downtime_vals(payload))
        return True, 'ok'

    def _nord_sync_workcenter_downtime_vals(self, payload):
        loss = self.env['mrp.workorder']._nord_sync_downtime_loss('stop', payload)
        return {
            'workcenter_id': self.id, 'workorder_id': False,
            'date_start': payload['start_date'], 'date_end': payload.get('end_date') or False,
            'loss_id': loss.id, 'description': 'Unjustified stop',
            'nord_sync_timesheet_id': payload['nord_timesheet_id'], 'nord_sync_downtime_kind': 'stop',
            'user_id': False, 'employee_id': False,
        }

    def _nord_sync_handle_machine_working_without_mo(self, start_date=None, payload=None):
        """Ponto 5: máquina diz que aquele WC está a trabalhar mas não tem nenhuma MO selecionada."""
        self.ensure_one()
        start_date = start_date or (payload and payload.get('start_date')) or fields.Datetime.now()
        # The machine starts: the stop it was in ends here (else the two lines overlap)
        self._nord_sync_close_open_downtime(start_date)
        behavior = self._nord_sync_effective_unassigned_behavior()

        if behavior == 'first_scheduled':
            # 5.1: Agarra na 1ª MO programada, organizada por data ascendente e marca start
            mo = self.env['mrp.production'].search([
                ('company_id', '=', self.company_id.id),
                ('state', 'in', ('confirmed', 'progress')),
            ], order='date_start asc, id asc', limit=1)
            if mo:
                try:
                    # A MO that cannot start must not lose the machine's time:
                    # nothing of the attempt stays, the unassigned timesheet below does.
                    with self.env.cr.savepoint():
                        self.with_context(
                            nord_sync_skip_prevent_check=True, nord_sync_from_core=True,
                        ).nord_sync_current_production_id = mo.id
                    return True, _("Started first scheduled MO: %s", mo.name)
                except Exception as exc:  # noqa: BLE001 - never reject a Nord event
                    _logger.warning(
                        'nord_sync: first scheduled MO %s could not start on %s (%s); '
                        'creating an unassigned timesheet instead.', mo.name, self.display_name, exc,
                    )
                    self.env.invalidate_all()
            behavior = 'unassigned_timesheets'

        if behavior == 'unassigned_timesheets':
            # 5.2: Cria os timesheets sem MO, com estado por atribuir (unassigned)
            Loss = self.env['mrp.workcenter.productivity.loss']
            productive = Loss.search([('loss_type', '=', 'productive')], limit=1)
            if not productive:
                productive = Loss._nord_sync_get_or_create_undefined()
            line = self.env['mrp.workcenter.productivity'].create({
                'workcenter_id': self.id,
                'workorder_id': False,
                'date_start': start_date,
                'date_end': False,
                'loss_id': productive.id,
                'nord_sync_is_unassigned': True,
                'nord_sync_timesheet_id': (payload or {}).get('nord_timesheet_id', 0),
                'description': 'Machine work without assigned MO',
                'user_id': False,
                'employee_id': False,
            })
            return True, _("Created unassigned timesheet (%s)", line.id)
        return False, "No behavior defined"

    def unlink(self):
        self._nord_sync_notify('unlink')
        return super().unlink()

    def _nord_sync_source_key(self):
        return 'mrp.production'

    def action_nord_sync_force_resync_reasons(self):
        """"Resync Reasons to Core" button (Nordwire tab, base.group_system
        only) — not actually scoped to this work center, loss/loss.type are
        global tables, not per-resource; lives here purely because the Nordwire
        tab is where an admin already is when they'd reach for it.

        Force-resyncs (action_nord_sync_force_resync, nord_sync.notify.mixin)
        every mrp.workcenter.productivity.loss.type and .loss — the same gate
        each model's own _nord_sync_notify already applies (loss needs a real
        external id) still runs, this only forces a fresh 'write' entry
        through, it never bypasses that filter. Meant for recovery: the Core
        apply side is get-or-create, not get-or-update (see
        reason_nord_sync.py) — if the Core's own nord.reason.type/nord.reason
        copy is ever lost (a DB reset, a manual delete there), its
        ir.model.data tag goes with it, and the next entry recreates it
        instead of being silently skipped as already-applied.
        """
        self.env['mrp.workcenter.productivity.loss.type'].search([]).action_nord_sync_force_resync()
        self.env['mrp.workcenter.productivity.loss'].search([]).action_nord_sync_force_resync()

    def _nord_sync_minute_timeline(self, days=1):
        """Minute by minute picture of this work center over the last `days`
        local days (today included, up to local midnight tonight), shared by
        the Nord Times chart and the machine overview. A minute is in the
        work day when the calendar (minus leaves) covers it, and carries the
        Nord category of the time line covering it (a line still open runs
        until now); a stop, setup or quality line wins over a productive one
        covering the same minute, so it is never hidden.

        Returns:
            dict: tz, local_now, now (naive UTC), first_day (date),
            start/end (naive UTC bounds of the range), minutes_in_range,
            now_minute (minutes elapsed since start, capped to the range),
            in_calendar (list[bool] per minute), minute_category
            (list[str|None] per minute), lines (the time lines of the
            range), local_midnight/to_naive_utc/minute_of (helpers bound to
            this range).
        """
        self.ensure_one()
        tz = pytz.timezone(self.env.user.tz or self.resource_calendar_id.tz or 'UTC')
        now = fields.Datetime.now()
        local_now = pytz.utc.localize(now).astimezone(tz)

        def local_midnight(date):
            return tz.localize(datetime.combine(date, datetime.min.time()))

        def to_naive_utc(moment):
            return moment.astimezone(pytz.utc).replace(tzinfo=None)

        first_day = local_now.date() - timedelta(days=days - 1)
        range_start = local_midnight(first_day)
        range_end = local_midnight(local_now.date() + timedelta(days=1))
        start = to_naive_utc(range_start)
        end = to_naive_utc(range_end)
        minutes_in_range = int((end - start).total_seconds() // 60)
        now_minute = min(int((now - start).total_seconds() // 60), minutes_in_range)

        def minute_of(moment):
            return int((moment - start).total_seconds() // 60)

        in_calendar = [False] * minutes_in_range
        if self.resource_calendar_id:
            intervals = self.resource_calendar_id._work_intervals_batch(
                range_start, range_end, resources=self.resource_id)[self.resource_id.id]
            for interval_start, interval_stop, _records in intervals:
                first = minute_of(to_naive_utc(interval_start))
                last = minute_of(to_naive_utc(interval_stop))
                for minute in range(max(first, 0), min(last, minutes_in_range)):
                    in_calendar[minute] = True

        lines = self.env['mrp.workcenter.productivity'].search([
            ('workcenter_id', '=', self.id), ('date_start', '<', end),
            '|', ('date_end', '=', False), ('date_end', '>', start),
        ], order='date_start')
        minute_category = [None] * minutes_in_range
        for line in lines:
            line_start, line_end = max(line.date_start, start), min(line.date_end or now, end)
            first = minute_of(line_start)
            last = int(-(-(line_end - start).total_seconds() // 60))
            for minute in range(max(first, 0), min(last, minutes_in_range)):
                if minute_category[minute] in (None, 'productive'):
                    minute_category[minute] = line.nord_sync_time_category
        return {
            'tz': tz, 'local_now': local_now, 'first_day': first_day,
            'start': start, 'end': end,
            'minutes_in_range': minutes_in_range, 'now_minute': now_minute,
            'in_calendar': in_calendar, 'minute_category': minute_category,
            'local_midnight': local_midnight, 'to_naive_utc': to_naive_utc, 'minute_of': minute_of,
            'lines': lines, 'now': now,
        }

    def nord_sync_time_chart_data(self, period='today'):
        """Time of this work center for the chart on the Nordwire tab: one
        bucket per local hour of today, or per local day of the last 7
        (week) / 30 (month) days. Every elapsed minute of a bucket is either
        one of the Nord categories (productive / stop / setup / quality: the
        time lines, a line still open running until now), 'overtime'
        (productive time outside the work day: the calendar minus leaves; a
        stop, setup or quality keeps its own colour), 'offline' (inside the
        work day, but no line), 'outside' (not in the work day, no line) or
        still to come (not counted). Today shows the hours of the work day,
        widened to any hour that had activity.

        Args:
            period (str): 'today', 'week' or 'month'.

        Returns:
            dict: categories (list[dict]: key, label of the Nord ones),
            buckets (list[dict]: label, start (hour of the day, or the
            date), minutes (dict: key -> minutes, incl. offline/outside/
            overtime), work_minutes (minutes of the bucket in the work
            day), future (bool)), totals (dict: key -> minutes, Nord ones
            only, over the whole period).
        """
        self.ensure_one()
        days = {'today': 1, 'week': 7, 'month': 30}.get(period, 1)
        timeline = self._nord_sync_minute_timeline(days)
        local_now, first_day = timeline['local_now'], timeline['first_day']
        minutes_in_range, now_minute = timeline['minutes_in_range'], timeline['now_minute']
        in_calendar, minute_category = timeline['in_calendar'], timeline['minute_category']
        local_midnight, to_naive_utc, minute_of = (
            timeline['local_midnight'], timeline['to_naive_utc'], timeline['minute_of'])
        categories = self.env['mrp.workcenter.productivity']._fields['nord_sync_time_category']._description_selection(self.env)

        if days == 1:
            active = [minute for minute in range(minutes_in_range) if minute_category[minute]]
            work = [minute for minute in range(minutes_in_range) if in_calendar[minute]]
            hour_marks = [minute // 60 for minute in work + active]
            first_hour, last_hour = (min(hour_marks), max(hour_marks)) if hour_marks else (8, max(local_now.hour, 8))
            spans = [
                (f'{hour:02d}h', hour, hour * 60, min(hour * 60 + 60, minutes_in_range))
                for hour in range(first_hour, last_hour + 1)
            ]
        else:
            spans = []
            for offset in range(days):
                date = first_day + timedelta(days=offset)
                spans.append((
                    f'{date:%d/%m}', date.isoformat(),
                    minute_of(to_naive_utc(local_midnight(date))),
                    minute_of(to_naive_utc(local_midnight(date + timedelta(days=1)))),
                ))

        totals = {key: 0.0 for key, _label in categories}
        buckets = []
        for label, key_value, span_start, span_end in spans:
            bucket = {key: 0.0 for key, _label in categories}
            bucket.update(offline=0.0, outside=0.0, overtime=0.0)
            work_minutes = 0
            for minute in range(span_start, span_end):
                work_minutes += in_calendar[minute]
                if minute >= now_minute:
                    continue
                category = minute_category[minute]
                if category:
                    totals[category] += 1
                    bucket['overtime' if category == 'productive' and not in_calendar[minute] else category] += 1
                else:
                    bucket['offline' if in_calendar[minute] else 'outside'] += 1
            buckets.append({
                'label': label,
                'start': key_value,
                'minutes': {key: round(value, 1) for key, value in bucket.items()},
                'work_minutes': work_minutes,
                'future': span_start >= now_minute,
            })
        return {
            'categories': [{'key': key, 'label': label} for key, label in categories],
            'buckets': buckets,
            'totals': {key: round(value, 1) for key, value in totals.items()},
        }

    def action_nord_sync_time_report(self):
        """The time lines behind the Nordwire tab's chart, as graph/pivot/
        list: the chart's "details" link."""
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('nord_sync_mrp.action_mrp_workcenter_productivity_nord_sync')
        action['display_name'] = self.env._('Nord Times — %s', self.display_name)
        action['domain'] = [('workcenter_id', '=', self.id)]
        action['context'] = {
            'create': False, 'edit': False,
            'search_default_nord_today': 1,
            'graph_groupbys': ['date_start:hour', 'nord_sync_time_category'],
        }
        return action

    def action_nord_sync_alerts(self):
        """The Nord stops of this work center, as a list: the "all alerts"
        link of the machine overview (filtered on today)."""
        self.ensure_one()
        action = self.action_nord_sync_time_report()
        action['display_name'] = self.env._('Alerts — %s', self.display_name)
        action['domain'] = [('workcenter_id', '=', self.id), ('nord_sync_time_category', '=', 'stop')]
        action['views'] = [(self.env.ref('nord_sync_mrp.mrp_workcenter_productivity_view_list_nord_sync').id, 'list'), (False, 'form')]
        action['view_mode'] = 'list,form'
        return action

    def _nord_sync_overview_alerts(self, timeline):
        """The alerts of today for the machine overview: every stop time
        line of the day, the open ones (still running) first, then the
        latest first. They are this work center's Kioda alert tasks: a stop
        comes from Nord (the Core opens it when the machine stops, see
        mrp.workorder's session_downtime_open, and closes it, or sends it
        closed with session_downtime), or is a time line logged with an
        availability reason, and stays an alarm until it ends. Quality time
        (rejects) is not one: those units already count as bad.

        Returns:
            dict: open (int: alerts still running), count (int), minutes
            (float: their elapsed minutes today), items (list[dict]: id,
            category ('stop'), reason (the loss reason),
            start / end (str 'HH:MM' local, end False while open), minutes
            (float), open (bool), operation (str or False: work order),
            production (str or False: production order name)).
        """
        tz, now, start = timeline['tz'], timeline['now'], timeline['start']

        def local_hm(moment):
            return pytz.utc.localize(moment).astimezone(tz).strftime('%H:%M')

        lines = timeline['lines'].filtered(lambda line: line.nord_sync_time_category == 'stop')
        lines = lines.sorted(lambda line: (bool(line.date_end), -line.date_start.timestamp()))
        items = []
        for line in lines:
            line_start, line_end = max(line.date_start, start), line.date_end or now
            items.append({
                'id': line.id,
                'category': line.nord_sync_time_category,
                'reason': line.loss_id.name or False,
                'start': local_hm(line_start),
                'end': local_hm(line.date_end) if line.date_end else False,
                'minutes': round(max((line_end - line_start).total_seconds(), 0) / 60, 1),
                'open': not line.date_end,
                'operation': line.workorder_id.name or False,
                'production': line.workorder_id.production_id.name or False,
            })
        return {
            'open': sum(item['open'] for item in items),
            'count': len(items),
            'minutes': round(sum(item['minutes'] for item in items), 1),
            'items': items,
        }

    # Machine overview: the 15 minute segments of the working hours timeline
    # and the state a minute of the day is in (the Kioda machine screen's).
    NORD_SYNC_SEGMENT_MINUTES = 15
    # The alarm is not one of them: like the Kioda alert tasks, it runs on its
    # own, on top of whatever the machine was doing.
    NORD_SYNC_MACHINE_STATES = ('working', 'setup', 'idle', 'offline')

    def nord_sync_machine_overview_data(self):
        """Today (local 00:00 until now) of this work center for the machine
        overview, one call for its four parts:

        - oee: OEE = Availability x Performance x Quality, with
          Availability = worked / planned hours until now (the calendar
          minus leaves; worked never counts above planned), Performance =
          produced / (capacity per hour x planned hours) and Quality =
          good / produced. Produced is good + bad: good is the quantity of
          the work orders finished here today (qty_produced, at
          date_finished), bad the scrap done today on them (the work
          order's own, or the production order's when the scrap names no
          work order). Worked is running time (productive time lines).
        - utilization: one segment per 15 minutes, each minute in one state:
          working (a productive line), setup (a setup line, not working),
          idle (in the work day, neither) or offline (out of the work day,
          neither). The segment's status is its working share (working_90
          / working_60 / working_30) when it ran at all, else its biggest
          state, or 'future'. The alarm is counted apart, as the Kioda
          screen counts its open alert tasks: the minutes a Nord stop
          covers (see _nord_sync_overview_alerts), whatever the machine
          was doing, shown as the segment's alarm strip, never as its
          colour, and never taken off the working time. Utilization rate
          is worked minutes over the minutes elapsed today.
        - declarations: good / bad per hour, with the average good of the
          hours that had planned or worked time.
        - oee_by_hour: the same three factors per elapsed hour (capacity of
          one hour), with their average over the same hours.
        - alerts: the Nord stops of the day (see
          _nord_sync_overview_alerts).

        Returns:
            dict: oee (dict: oee, availability, performance, quality,
            oee_target, planned_hours, worked_hours, expected_production,
            produced, good, bad, capacity_per_hour, capacity_source
            ('workcenter' / 'workorders' / False)), utilization (dict:
            current_status, in_alarm (a stop still open), segments
            (list[dict]: label, status, alarm (bool), minutes (dict: state
            or 'alarm' -> minutes)), totals (dict: state or 'alarm' ->
            minutes), utilization_rate), declarations (dict: hours
            (list[dict]: label, good, bad), average_good), oee_by_hour (dict:
            hours (list[dict]: label, availability, performance, quality,
            oee, future), average_oee), alerts (dict, see
            _nord_sync_overview_alerts), date (str, local today).
        """
        self.ensure_one()
        timeline = self._nord_sync_minute_timeline(1)
        start, end = timeline['start'], timeline['end']
        total_minutes, now_minute = timeline['minutes_in_range'], timeline['now_minute']
        in_calendar, minute_category = timeline['in_calendar'], timeline['minute_category']
        minute_of = timeline['minute_of']
        hours_in_day = -(-total_minutes // 60)

        # Each kind of line on its own, so a stop never hides the running
        # time it overlaps (the timeline's minute_category does, on purpose).
        covered = {'productive': [False] * now_minute, 'setup': [False] * now_minute, 'stop': [False] * now_minute}
        for line in timeline['lines']:
            flags = covered.get(line.nord_sync_time_category)
            if flags is None:
                continue
            line_end = min(line.date_end or timeline['now'], end)
            first = max(minute_of(max(line.date_start, start)), 0)
            last = min(int(-(-(line_end - start).total_seconds() // 60)), now_minute)
            for minute in range(first, last):
                flags[minute] = True

        def state_of(minute):
            if covered['productive'][minute]:
                return 'working'
            if covered['setup'][minute]:
                return 'setup'
            return 'idle' if in_calendar[minute] else 'offline'

        states = [state_of(minute) for minute in range(now_minute)]
        alarm = covered['stop']

        # ── Declarations: good from the finished work orders, bad from scrap ──
        good_by_hour = [0.0] * hours_in_day
        bad_by_hour = [0.0] * hours_in_day
        workorders = self.env['mrp.workorder'].search([
            ('workcenter_id', '=', self.id), ('state', '=', 'done'),
            ('date_finished', '>=', start), ('date_finished', '<', end),
        ])
        for workorder in workorders:
            hour = minute_of(workorder.date_finished) // 60
            if 0 <= hour < hours_in_day:
                good_by_hour[hour] += workorder.qty_produced
        scraps = self.env['stock.scrap'].search([
            ('state', '=', 'done'), ('date_done', '>=', start), ('date_done', '<', end),
            '|', ('workorder_id.workcenter_id', '=', self.id),
            '&', ('workorder_id', '=', False), ('production_id.workorder_ids.workcenter_id', '=', self.id),
        ])
        for scrap in scraps:
            hour = minute_of(scrap.date_done) // 60
            if 0 <= hour < hours_in_day:
                bad_by_hour[hour] += scrap.scrap_qty

        # ── Capacity: the work center's own, else today's work orders' pace ──
        capacity = self.nord_sync_capacity_per_hour
        capacity_source = 'workcenter' if capacity else False
        if not capacity:
            reference = self.env['mrp.workorder'].search([
                ('workcenter_id', '=', self.id), ('duration_expected', '>', 0),
                '|', ('state', '=', 'progress'),
                '&', '&', ('state', '=', 'done'), ('date_finished', '>=', start), ('date_finished', '<', end),
            ])
            expected_hours = sum(reference.mapped('duration_expected')) / 60
            if expected_hours:
                capacity = sum(reference.mapped('qty_production')) / expected_hours
                capacity_source = 'workorders'

        def factors(planned, worked, good, bad, hours):
            """Availability, performance, quality and OEE in %, for `planned`
            and `worked` minutes and the `hours` of capacity they had."""
            worked = min(worked, planned) if planned else worked
            produced = good + bad
            availability = worked / (planned or worked or 1) * 100
            if capacity:
                performance = produced / (capacity * hours) * 100 if hours else 0.0
            else:
                performance = 100.0 if produced or not hours else 0.0
            quality = good / produced * 100 if produced else (100.0 if not bad else 0.0)
            oee = max(0.0, min(100.0, availability * min(performance, 100.0) * quality / 10000))
            return availability, performance, quality, oee

        # ── OEE header ───────────────────────────────────────────────────────
        planned_minutes = sum(in_calendar[:now_minute])
        worked_minutes = states.count('working')
        base_hours = (planned_minutes or min(worked_minutes, now_minute)) / 60
        good, bad = sum(good_by_hour), sum(bad_by_hour)
        availability, performance, quality, oee = factors(
            planned_minutes, worked_minutes, good, bad, base_hours)
        oee_data = {
            'oee': round(oee, 1),
            'availability': round(availability, 1),
            'performance': round(performance, 1),
            'quality': round(quality, 1),
            'oee_target': self.oee_target,
            'planned_hours': round(planned_minutes / 60, 2),
            'worked_hours': round(min(worked_minutes, planned_minutes or worked_minutes) / 60, 2),
            'expected_production': round(capacity * base_hours, 1) if capacity else 0.0,
            'produced': good + bad,
            'good': good,
            'bad': bad,
            'capacity_per_hour': round(capacity, 2),
            'capacity_source': capacity_source,
        }

        # ── Working hours: 15 minute segments ────────────────────────────────
        size = self.NORD_SYNC_SEGMENT_MINUTES
        segments = []
        totals = dict.fromkeys((*self.NORD_SYNC_MACHINE_STATES, 'alarm'), 0)
        for first in range(0, total_minutes, size):
            last = min(first + size, total_minutes)
            minutes = dict.fromkeys((*self.NORD_SYNC_MACHINE_STATES, 'alarm'), 0)
            for minute in range(first, min(last, now_minute)):
                minutes[states[minute]] += 1
                minutes['alarm'] += alarm[minute]
            for state, value in minutes.items():
                totals[state] += value
            if first >= now_minute:
                status = 'future'
            elif minutes['working']:
                share = minutes['working'] / (last - first) * 100
                status = 'working_90' if share > 90 else 'working_60' if share > 60 else 'working_30'
            else:
                status = max(('setup', 'idle', 'offline'), key=lambda key: minutes[key])
            segments.append({
                'label': f'{first // 60:02d}:{first % 60:02d} - {last // 60:02d}:{last % 60:02d}',
                'status': status,
                'alarm': minutes['alarm'] > 0,
                'minutes': minutes,
            })
        utilization = {
            'current_status': states[-1] if states else 'offline',
            'in_alarm': bool(timeline['lines'].filtered(
                lambda line: line.nord_sync_time_category == 'stop' and not line.date_end)),
            'segments': segments,
            'totals': totals,
            'utilization_rate': round(worked_minutes / now_minute * 100, 1) if now_minute else 0.0,
        }

        # ── By hour: declarations and OEE ────────────────────────────────────
        declarations, oee_hours, active_hours = [], [], []
        for hour in range(hours_in_day):
            first, last = hour * 60, min(hour * 60 + 60, total_minutes)
            label = f'{hour:02d}:00'
            declarations.append({'label': label, 'good': good_by_hour[hour], 'bad': bad_by_hour[hour]})
            if first >= now_minute:
                oee_hours.append({'label': label, 'availability': 0.0, 'performance': 0.0,
                                  'quality': 0.0, 'oee': 0.0, 'future': True})
                continue
            upto = min(last, now_minute)
            planned = sum(in_calendar[first:upto])
            worked = states[first:upto].count('working')
            if planned or worked or good_by_hour[hour] or bad_by_hour[hour]:
                active_hours.append(hour)
            hour_availability, hour_performance, hour_quality, hour_oee = factors(
                planned, worked, good_by_hour[hour], bad_by_hour[hour], 1 if planned or worked else 0)
            if not (good_by_hour[hour] or bad_by_hour[hour]):
                # Nothing declared in the hour: no quality to speak of, and no
                # OEE either — the Kioda screen's own reading of an empty hour.
                hour_quality = hour_oee = 0.0
            oee_hours.append({
                'label': label,
                'availability': round(hour_availability, 1),
                'performance': round(hour_performance, 1),
                'quality': round(hour_quality, 1),
                'oee': round(hour_oee, 1),
                'future': False,
            })
        average_good = (sum(good_by_hour[hour] for hour in active_hours) / len(active_hours)) if active_hours else 0.0
        average_oee = (sum(oee_hours[hour]['oee'] for hour in active_hours) / len(active_hours)) if active_hours else 0.0

        return {
            'date': timeline['local_now'].date().isoformat(),
            'oee': oee_data,
            'utilization': utilization,
            'declarations': {'hours': declarations, 'average_good': round(average_good, 2)},
            'oee_by_hour': {'hours': oee_hours, 'average_oee': round(average_oee, 1)},
            'alerts': self._nord_sync_overview_alerts(timeline),
        }

    def _nord_sync_payload(self):
        """Payload sent to the Core to keep this work center's edge.resource
        up to date.

        No resource_kind key: the Core defaults a work center's
        edge.resource to 'machine' on its own when the key is absent
        (mirrors how hr.employee's own payload never sends one either,
        always resolved to 'human' Core-side) — 'tool' is a real, accepted
        value on the Core, just not something the stock client UI exposes
        a way to choose yet.

        autonomous_close/granular_push/contention_policy/chain_close/mirror_mode/
        close_notify_only/auto_idle_segments/idle_segment_reason/auto_tooling_segments/
        tooling_segment_reason stay hardcoded here, can't move to
        _nord_sync_configurable_payload() — the wire key
        is a renamed shorthand of the real field
        (nord_sync_autonomous_close, etc.), and that mechanism only ever
        sends a field under its own real name. name is the one key here
        that's genuinely "read this field off self" — per-company
        selectable via that mechanism instead (default: on, unchanged
        behavior).

        Keys:
            nord_resource_uids (list[str]): the Core's edge.resource(s) this
                work center is mapped to — self.resource_id.nord_sync_resource_id.
                mapped('uid'), empty list when unmapped. The Core never
                creates/guesses a resource from this payload; without at
                least one uid it just skips the entry, so nothing syncs for
                this work center until a human maps it (Configuration >
                Technical > Resources).
            autonomous_close (bool): let a port-driven Nord Alert close jobs
                on this resource without a human clicking "Mark Done".
            granular_push (bool): push work-session start/stop and job
                cancellation back to this work order in real time.
            prevent_mo_change_if_running (bool) / unassigned_work_behavior (str): the
                other two MO & Work Order rules, effective values (the Core keeps them
                on the resource and they sync both ways with the Cloud).
            mo_change_behavior (str): 'close_and_open' or 'start_without_close' — the
                work center's effective MO Change Behavior (its own, else the
                company's); the Core turns it into one work session at a time or
                parallel ones (edge.resource.timesheet_overlap_policy).
            contention_policy (str): 'block' or 'auto_close_previous' — what
                the Core does on a new session while one is already open.
            chain_close (bool): let starting a later operation of the same
                MO elsewhere auto-close this resource's own open session
                for that MO — see nord_sync_chain_close's own help text.
            mirror_mode (bool): let this resource's MOs' own state changes
                (client-side) additionally drive the matching Core job
                action — see nord_sync_mirror_mode's own help text.
            close_notify_only (bool): skip applying the declared
                quantities to this production order on close, posting
                only a chatter note with the declaration count instead —
                see nord_sync_close_notify_only's own help text.
            stop_tracking (bool): a stop mid-job is logged on the work
                order as an unjustified stop, the next start resumes the
                same MO, and a start right after another tracked work
                center's stop logs the gap as this one's setup — see
                nord_sync_stop_tracking's own help text.
            auto_idle_segments (bool): backfill the gap between two closed
                sessions of the same job on this resource with an Idle
                segment on the Core — see nord_sync_auto_idle_segments's
                own help text.
            idle_segment_reason (str): loss reason name for Idle segments.
            auto_tooling_segments (bool): backfill the gap between a job's
                first session on this resource being queued and it
                actually starting with a Tooling segment on the Core — see
                nord_sync_auto_tooling_segments's own help text.
            tooling_segment_reason (str): loss reason name for Tooling
                segments.
            resource_calendar_attendances (list[dict]): [{dayofweek,
                hour_from, hour_to, day_period}], one per attendance line on
                this work center's resource.calendar, empty list if none set.
        """
        self.ensure_one()
        return {
            **self._nord_sync_configurable_payload(),
            'current_production_id': self.nord_sync_current_production_id.id or False,
            'current_production_name': self.nord_sync_current_production_id.name or False,
            'nord_resource_uids': self.resource_id.nord_sync_resource_id.mapped('uid'),
            'autonomous_close': self.nord_sync_autonomous_close,
            'granular_push': self.nord_sync_granular_push,
            'mo_change_behavior': self._nord_sync_effective_mo_change_behavior(),
            'prevent_mo_change_if_running': self._nord_sync_effective_prevent_mo_change(),
            'unassigned_work_behavior': self._nord_sync_effective_unassigned_behavior(),
            'contention_policy': self.nord_sync_contention_policy,
            'chain_close': self.nord_sync_chain_close,
            'mirror_mode': self.nord_sync_mirror_mode,
            'close_notify_only': self.nord_sync_close_notify_only,
            'stop_tracking': self.nord_sync_stop_tracking,
            'auto_idle_segments': self.nord_sync_auto_idle_segments,
            'idle_segment_reason': self.nord_sync_idle_segment_reason_name,
            'auto_tooling_segments': self.nord_sync_auto_tooling_segments,
            'tooling_segment_reason': self.nord_sync_tooling_segment_reason_name,
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
