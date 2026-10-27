# -*- coding: utf-8 -*-
from odoo import api, fields, models


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
    _name = 'mrp.workcenter'
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

    NORD_SYNC_CONTROL_MODE_PRESETS = {
        'odoo': {
            'nord_sync_autonomous_close': False, 'nord_sync_granular_push': False,
            'nord_sync_contention_policy': 'block', 'nord_sync_chain_close': False,
        },
        'nord': {
            'nord_sync_autonomous_close': True, 'nord_sync_granular_push': True,
            'nord_sync_contention_policy': 'auto_close_previous', 'nord_sync_chain_close': True,
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

    @api.depends(
        'nord_sync_autonomous_close', 'nord_sync_granular_push',
        'nord_sync_contention_policy', 'nord_sync_chain_close',
    )
    def _compute_nord_sync_control_mode(self):
        for workcenter in self:
            current = {
                field: workcenter[field] for field in self.NORD_SYNC_CONTROL_MODE_PRESETS['odoo']
            }
            workcenter.nord_sync_control_mode = next(
                (mode for mode, preset in self.NORD_SYNC_CONTROL_MODE_PRESETS.items() if preset == current),
                'custom',
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
        result = super().write(vals)
        self._nord_sync_notify('write')
        return result

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
            'nord_resource_uids': self.resource_id.nord_sync_resource_id.mapped('uid'),
            'autonomous_close': self.nord_sync_autonomous_close,
            'granular_push': self.nord_sync_granular_push,
            'contention_policy': self.nord_sync_contention_policy,
            'chain_close': self.nord_sync_chain_close,
            'mirror_mode': self.nord_sync_mirror_mode,
            'close_notify_only': self.nord_sync_close_notify_only,
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
