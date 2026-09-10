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
    _inherit = ['mrp.workcenter', 'nord_sync.notify.mixin']

    # ── Nord Sync Resource Mapping ───────────────────────────────────────────
    # The real field lives on resource.resource (nord_sync_mrp/models/
    # resource_resource.py) — shared with hr.employee via the resource_id both
    # already carry, see that file's own docstring for why. Exposed here too,
    # related+editable, purely so mapping a work center doesn't require
    # leaving this form for the generic Resources screen (ADR 0026's own
    # mapping mechanism is unchanged — this is only a second, more
    # convenient door onto the same field).

    nord_sync_resource_id = fields.Many2one(
        'nord_sync.resource', string='Nord Core Resource',
        related='resource_id.nord_sync_resource_id', readonly=False,
        help='Which edge.resource on the Nord Core this work center is. The Resource Bridge '
             'only ever updates an already-mapped Core resource — it never creates one, so '
             'nothing below syncs for this work center until this is set.',
    )

    # ── Nord Sync Autonomous Resource Policies ───────────────────────────────
    # Authored here — mirrored onto the Core's edge.resource by the Resource
    # Bridge, never enforced client-side.

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
    nord_sync_chain_close = fields.Boolean(
        string='Chain Close',
        default=False,
        help='Off (default): a session left open on this resource stays open regardless of '
             'what happens elsewhere. On: starting a later operation of the same MO on any '
             'other resource automatically closes this resource\'s own open session for that '
             'MO first. Mirrors the Zerynth app\'s automatic_close_next_order — covers an '
             'operator moving on to the next step without explicitly closing the previous '
             'one. A different axis from Resource Contention Policy above: that one reacts on '
             'THIS resource when a new session starts here; this one reacts on THIS resource '
             'when a later operation starts somewhere else.',
    )
    nord_sync_mirror_mode = fields.Boolean(
        string='Mirror Mode',
        default=False,
        help='Off (default): the Core only ever advances a job past a human/device action on '
             "the Core itself (NordGo, a port-driven alert) — this resource's MOs' own state "
             'is paperwork, not real production. On: an MO on this resource reaching '
             'Confirmed/In Progress/Done on the client additionally drives the matching action '
             "on the Core job (no result push back for a Done reached this way — the client's "
             'own qty is already final by then). Cancelling always cancels the job either way, '
             'this toggle only adds the other three. Per work center, not company-wide — moved '
             'here from Nord Sync > Configuration. Deliberately outside Control Mode below — a '
             'special case a client opts into on top of either preset, not an axis "Odoo" or '
             '"Nord" has a stance on; picking either preset never touches it.',
    )

    # ── Automatic Idle/Tooling Segments ──────────────────────────────────────
    # Authored here purely for a familiar place to configure it — the Core
    # never actually needs client data to compute either segment (it's pure
    # session timing on edge.resource, ADR 0030), same "config lives on the
    # workcenter, computation doesn't need it" split as the rest of this
    # bridge's autonomy policies. Also outside Control Mode: a reporting/OEE
    # concern, not floor-event or job-state authority.

    nord_sync_auto_idle_segments = fields.Boolean(
        string='Automatic Idle Segments',
        default=False,
        help='Off (default): a resource has no session at all between two jobs. On: stopping '
             'work opens an unclassified downtime session on the Core, closed by the next '
             'start — no gap ever goes unexplained, and it\'s excluded from worked time.',
    )
    nord_sync_idle_segment_reason_name = fields.Char(
        string='Idle Segment Reason',
        default='Idle',
        help='Unused for now — downtime segments open without a reason.',
    )
    nord_sync_auto_tooling_segments = fields.Boolean(
        string='Automatic Tooling Segments',
        default=False,
        help='Unused for now.',
    )
    nord_sync_tooling_segment_reason_name = fields.Char(
        string='Tooling Segment Reason',
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
        ('odoo', 'Odoo'), ('nord', 'Nord'), ('custom', 'Custom'),
    ], string='Control Mode', compute='_compute_nord_sync_control_mode', inverse='_inverse_nord_sync_control_mode',
        help='Shortcut over the four floor-event fields above, not a fact of its own — always '
             'reflects their current values, never drifts. "Odoo": this Odoo stays in control '
             '(no autonomous close, no live push, refuses contention, no chain close). "Nord": '
             'the Core is handed full autonomy on all four. Picking either writes all four '
             'fields at once; editing any of them by hand afterwards silently falls back to '
             "\"Custom\" — there is nothing to keep in sync, it's recomputed from the same "
             'four fields every time. Mirror Mode is not part of this — see its own help text.',
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

    def _nord_sync_source_key(self):
        return 'mrp.production'

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
        auto_idle_segments/idle_segment_reason/auto_tooling_segments/tooling_segment_reason
        stay hardcoded here, can't move to _nord_sync_configurable_payload() — the wire key
        is a renamed shorthand of the real field
        (nord_sync_autonomous_close, etc.), and that mechanism only ever
        sends a field under its own real name. name is the one key here
        that's genuinely "read this field off self" — per-company
        selectable via that mechanism instead (default: on, unchanged
        behavior).

        Keys:
            nord_resource_uid (str or False): the Core's edge.resource this
                work center is mapped to (Nord Sync Resource Mapping, ADR
                0026) — self.resource_id.nord_sync_resource_id.uid, False
                when unmapped. The Core never creates/guesses a resource
                from this payload; without this key it just skips the
                entry, so nothing syncs for this work center until a human
                maps it (Configuration > Technical > Resources).
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
            'nord_resource_uid': self.resource_id.nord_sync_resource_id.uid or False,
            'autonomous_close': self.nord_sync_autonomous_close,
            'granular_push': self.nord_sync_granular_push,
            'contention_policy': self.nord_sync_contention_policy,
            'chain_close': self.nord_sync_chain_close,
            'mirror_mode': self.nord_sync_mirror_mode,
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
