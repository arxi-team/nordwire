# -*- coding: utf-8 -*-
from odoo import api, fields, models, release
from odoo.exceptions import UserError
from odoo.tools import config

from ..models.nord_sync_config import JOB_NAMING_MODES

SUPPORTED_MAJOR_VERSIONS = (19,)

RUN_BEFORE_PREFIX = 'run_before_'
RUN_AFTER_PREFIX = 'run_after_'

# 'own'/'both' start from this instead of a blank list — a starting point to
# edit, not a forced vocabulary.
JOB_STAGE_SUGGESTED_NAMES = ['Queued', 'In Progress', 'Quality Check', 'Done']


class NordSyncInstallWizard(models.TransientModel):
    """Install wizard, 7 steps — pre-flight, sources, connection, job
    stages, mapping, job naming, finish. Job stages and mapping used to be one combined
    step; split into two so the person configuring this only has to think
    about one thing at a time (name the stages, then map states to them),
    matching how the rest of the wizard already isolates one concern per step.

    Multi-step shape (state + _steps + run_before_/run_after_ per-step
    hooks) is a small self-contained step machine — no reusable abstract
    base, since Nord Sync is the only wizard using it today.

    The Sources step exists because the Mapping step can only show a
    source's native states once that source's addon is installed —
    choosing a Nord Sync Source *is* installing its addon (nord_sync_mrp,
    nord_sync_maintenance, ...), there's no separate enable/disable toggle.
    A wizard auto-opened right after installing just the base `nord_sync`
    module, with no source addon selected alongside it, would otherwise land
    on an empty mapping step with no way to know why.

    Its "Next" (action_confirm_sources, not the generic action_next_step)
    installs whatever got checked via button_immediate_install() — same call
    the Apps screen's own Install button makes. Installing an app can add
    menus/views/JS assets the already-loaded page doesn't know about, so a
    reload has to happen — but rather than a blind full-page reload,
    action_confirm_sources points a dedicated ir.actions.todo at this exact
    record first, which is what Odoo's own post-install continuation
    mechanism (ir.module.module.next(), called from inside
    button_immediate_install() itself) picks up and reopens automatically:
    the client lands back on this same wizard, continuing right where it
    left off, now correctly seeing the newly installed source's native
    states once it reaches Job Stages/Mapping.
    """
    _name = 'nord_sync.install.wizard'
    _description = 'Nord Sync Installation Wizard'

    _steps = [
        ('step_preflight', 'Pre-flight'),
        ('step_sources', 'Sources'),
        ('step_connection', 'Connection'),
        ('step_job_stages', 'Job Stages'),
        ('step_mapping', 'Mapping'),
        ('step_job_naming', 'Job Naming'),
        ('step_finish', 'Finish'),
    ]

    state = fields.Char(default='step_preflight')
    state_index = fields.Integer(compute='_compute_state_index_and_visibility')
    show_previous = fields.Boolean(compute='_compute_state_index_and_visibility')
    show_next = fields.Boolean(compute='_compute_state_index_and_visibility')
    show_finish = fields.Boolean(compute='_compute_state_index_and_visibility')

    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company,
    )
    company_uid = fields.Char(string='Nord Company UID')
    cloud_base_url = fields.Char(
        string='Nord Cloud URL',
        help='Same value as the nord_sync.cloud_base_url system parameter — editable '
             'from either place. Set here too (not just in Settings > Technical > '
             'System Parameters) because every push this wizard makes from Job Stages '
             'onward needs it already in place: without it, the wake webhook is '
             "silently skipped (nord.sync.queue entries land 'pending') and, once "
             'the pull cursor moves past them, nothing retries them automatically.',
    )

    available_source_ids = fields.One2many(
        'nord_sync.install.wizard.source.line', 'wizard_id', string='Nord Sync Sources',
    )

    job_stage_mode = fields.Selection([
        ('native', 'Map native states'),
        ('own', 'Define my own'),
        ('both', 'Both'),
    ], default='native', string='Job Stages',
        help='Native: one stage per state this Odoo already tracks on Manufacturing '
             'Orders, no typing needed. Own: a free list you define from scratch. '
             'Both: the native ones, plus whatever you add on top.',
    )
    job_stage_line_ids = fields.One2many(
        'nord_sync.install.wizard.stage.line', 'wizard_id', string='Stages',
    )

    mapping_line_ids = fields.One2many(
        'nord_sync.install.wizard.mapping.line', 'wizard_id', string='Mapping',
    )

    job_naming_mode = fields.Selection(
        JOB_NAMING_MODES, default='sequence', string='Job Naming',
        help='How jobs created on the Nord Core from this company\'s synced '
             "records get their name/reference — the Core's own sequence, "
             "the originating document's own name (e.g. a Manufacturing "
             "Order's WH/MO/00019), or a custom prefix on the Core sequence.",
    )
    job_naming_custom_prefix = fields.Char(
        string='Custom Job Naming Prefix',
        help='Only used when Job Naming is Custom Prefix — Core ir.sequence '
             'prefix syntax, e.g. "ACME-JOB/%(year)s/".',
    )

    cron_active = fields.Boolean(string='Scheduler Active', readonly=True)
    odoo_version_supported = fields.Boolean(string='Odoo Version Supported', readonly=True)
    preflight_ok = fields.Boolean(readonly=True)
    preflight_message = fields.Char(readonly=True)

    # ── step machine ────────────────────────────────────────────────────────────

    def get_steps(self):
        return self._steps

    @api.depends('state', 'preflight_ok')
    def _compute_state_index_and_visibility(self):
        for wiz in self:
            steps = wiz.get_steps()
            keys = [s[0] for s in steps]
            index = keys.index(wiz.state) if wiz.state in keys else 0
            wiz.state_index = index
            wiz.show_previous = index != 0
            can_advance = wiz.state != 'step_preflight' or wiz.preflight_ok
            wiz.show_next = (index + 1 != len(steps)) and can_advance
            wiz.show_finish = (index + 1 == len(steps))

    def run_step_action(self, prefix):
        self.ensure_one()
        method = getattr(self, prefix + self.state, None)
        if not method:
            return True
        return method()

    def _reopen(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_next_step(self):
        self.ensure_one()
        if self.run_step_action(RUN_AFTER_PREFIX):
            steps = self.get_steps()
            self.state = steps[self.state_index + 1][0]
            self.run_step_action(RUN_BEFORE_PREFIX)
        return self._reopen()

    def action_previous_step(self):
        self.ensure_one()
        steps = self.get_steps()
        self.state = steps[self.state_index - 1][0]
        self.run_step_action(RUN_BEFORE_PREFIX)
        return self._reopen()

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        Line = self.env['nord_sync.install.wizard.mapping.line']
        SourceLine = self.env['nord_sync.install.wizard.source.line']
        for wiz in records:
            # Created directly server-side, not via an X2M command in
            # vals_list/default_get — real bug found live (2026-08-10 for
            # mapping_line_ids, 2026-08-11 for available_source_ids):
            # Odoo's web client omits readonly fields from an X2M row's
            # create payload (treated as "not user-editable, nothing to
            # send back"), which silently dropped source_value/module_id on
            # every row despite default_get/onchange setting it correctly
            # server-side (module_id NULL violates its own not-null
            # constraint). Creating the lines here sidesteps the client's
            # round-trip entirely, so a readonly field here can't recur.
            if not wiz.mapping_line_ids:
                Line.create([dict(vals, wizard_id=wiz.id) for vals in wiz._mapping_line_vals()])
            wiz._default_mapping_targets()
            if not wiz.available_source_ids:
                SourceLine.create([dict(vals, wizard_id=wiz.id) for vals in wiz._available_source_line_vals()])
        return records

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        company = self.env['res.company'].browse(vals['company_id']) if vals.get('company_id') else self.env.company
        config_rec = self.env['nord_sync.config']._get_for_company(company)
        if config_rec:
            vals.setdefault('company_uid', config_rec.company_uid)
            vals.setdefault('job_naming_mode', config_rec.job_naming_mode)
            vals.setdefault('job_naming_custom_prefix', config_rec.job_naming_custom_prefix)
        vals.setdefault('cloud_base_url', self.env['nord_sync.config']._get_cloud_base_url())
        vals.update(self._run_preflight())
        # Computed once here (not re-triggered on every step re-entry) so a
        # user who deliberately empties the list and navigates back/forward
        # doesn't get it silently repopulated — see _onchange_job_stage_mode.
        # mapping_line_ids is deliberately NOT populated here — see create()'s
        # docstring comment for why it's created server-side instead.
        if 'job_stage_line_ids' in fields_list:
            vals['job_stage_line_ids'] = self._job_stage_line_commands(vals.get('job_stage_mode', 'native'))
        # available_source_ids is deliberately NOT populated here either —
        # same reason as mapping_line_ids above, see create()'s comment.
        return vals

    # ── Step 1: Pre-flight ───────────────────────────────────────────────────────

    @api.model
    def _run_preflight(self):
        cron_active = (config.get('max_cron_threads') or 0) > 0
        version_supported = release.version_info[0] in SUPPORTED_MAJOR_VERSIONS
        problems = []
        if not cron_active:
            problems.append(
                'The task scheduler (cron) is disabled on this server '
                '(max_cron_threads=0) — periodic reconciliation will never run.'
            )
        if not version_supported:
            problems.append(
                f'This addon targets Odoo {SUPPORTED_MAJOR_VERSIONS[0]}, but the '
                f'server is running Odoo {release.version_info[0]}.'
            )
        return {
            'cron_active': cron_active,
            'odoo_version_supported': version_supported,
            'preflight_ok': cron_active and version_supported,
            'preflight_message': ' '.join(problems) or 'Environment ready to configure Nord Sync.',
        }

    def action_refresh_preflight(self):
        self.ensure_one()
        self.write(self._run_preflight())
        return self._reopen()

    def run_after_step_preflight(self):
        if not self.preflight_ok:
            raise UserError('Fix the environment issues before continuing (see pre-flight message).')
        return True

    # ── Step 2: Sources ──────────────────────────────────────────────────────────

    @api.model
    def _discover_source_modules(self):
        """Any `ir.module.module` named `nord_sync_*` (never `nord_sync`
        itself) — naming convention, not a hardcoded list, so a future
        source addon shows up here without touching this wizard."""
        candidates = self.env['ir.module.module'].sudo().search([('name', 'like', 'nord_sync')])
        return candidates.filtered(lambda m: m.name.startswith('nord_sync_'))

    @api.model
    def _available_source_line_vals(self):
        return [
            {'module_id': m.id, 'selected': m.state == 'installed'}
            for m in self._discover_source_modules()
        ]

    def action_confirm_sources(self):
        """Sources step's own "Next" — a dedicated button, not the generic
        action_next_step, because installing something here has to go
        through Odoo's own install-then-continue mechanism instead of just
        reopening this wizard by hand.

        button_immediate_install() reloads the registry — installing a real
        app (sale, stock, ...) can add menus/views/JS assets the
        already-loaded page has no way to know about. A first attempt
        manually rebuilt an Environment and kept editing this same wizard
        in place to avoid a reload entirely — broke live: the Job Stages &
        Mapping step's dropdowns crashed (OwlError) right after installing
        nord_sync_sale mid-session, the browser's view/asset cache was still
        the pre-install one and none of the hand-rolled bookkeeping made
        that consistent again.

        button_immediate_install() already has a built-in, proven way to
        chain a wizard after an install without a blind full-page reload:
        it calls ir.module.module.next(), which looks for an open
        ir.actions.todo and opens whatever action it points to directly
        (the same mechanism every Odoo app's own post-install setup wizard
        uses). Pointing our own dedicated resume todo's action at this exact
        record (context.res_id) before installing is what makes the client
        land back on this same wizard, continuing right where it left off,
        through a path Odoo's own client already knows how to handle
        consistently — not a bespoke one.
        """
        self.ensure_one()
        to_install = self.available_source_ids.filtered(
            lambda line: line.selected and not line.installed
        ).module_id
        if not to_install:
            return self.action_next_step()
        steps = self.get_steps()
        self.state = steps[self.state_index + 1][0]
        resume_action = self.env.ref('nord_sync.action_nord_sync_install_wizard_resume')
        resume_action.sudo().write({'context': repr({'res_id': self.id})})
        self.env.ref('nord_sync.todo_nord_sync_install_wizard_resume').sudo().write({'state': 'open'})
        return to_install.sudo().button_immediate_install()

    # ── Step 3: Connection ───────────────────────────────────────────────────────

    def run_after_step_connection(self):
        if not self.company_uid:
            raise UserError('Fill in the company UID before continuing.')
        if not self.cloud_base_url:
            raise UserError('Fill in the Nord Cloud URL before continuing.')
        # Written immediately (not deferred to Finish, like company_uid/job_naming
        # are) — every push from Job Stages onward needs this system parameter to
        # already exist, or the wake webhook is silently skipped and that entry is
        # never retried once the pull cursor moves past it (real incident,
        # 2026-08-17: a fresh install's own Job Stage/Mapping bootstrap landed
        # 'pending' forever because this was set by hand only after Finish).
        self.env['nord_sync.config']._set_cloud_base_url(self.cloud_base_url)
        return True

    def run_before_step_job_stages(self):
        """Recomputes job_stage_line_ids/mapping_line_ids, but only if the
        set of registered source models actually changed since they were
        last generated — covers a source installed via the Sources step
        earlier in this same wizard (that record's own lines were generated
        once, at create() time, which predates any install the Sources step
        itself triggered — the resume after that install lands back on
        Connection, not here, so create()'s snapshot is never touched again
        on its own) without wiping manual edits (job stage renames, job
        stage picks) on the common case of just going back to this step
        from Finish and forward again with nothing installed meanwhile.

        Fires on the way into the Job Stages step (not Mapping, even though
        it also refreshes mapping_line_ids) — both need to be ready before
        either step is shown, and Job Stages always comes first, so doing it
        once here means the Mapping step needs no refresh hook of its own.
        """
        self.ensure_one()
        registered_models = {s['source_model'] for s in self._nord_sync_available_native_sources()}
        current_models = set(self.mapping_line_ids.mapped('source_model'))
        if registered_models == current_models:
            return True
        self.job_stage_line_ids = self._job_stage_line_commands(self.job_stage_mode)
        self.mapping_line_ids.unlink()
        Line = self.env['nord_sync.install.wizard.mapping.line']
        Line.create([dict(vals, wizard_id=self.id) for vals in self._mapping_line_vals()])
        self._default_mapping_targets()
        return True

    # ── Steps 4-5: Job Stages & Mapping ──────────────────────────────────────────

    @api.model
    def _nord_sync_available_native_sources(self):
        """Thin delegate to nord_sync.config's registry — kept as a method
        here too so the rest of this file (and existing tests) can keep calling
        self._nord_sync_available_native_sources() unchanged.
        """
        return self.env['nord_sync.config']._nord_sync_available_native_sources()

    @api.model
    def _native_state_labels(self):
        labels = []
        for source in self._nord_sync_available_native_sources():
            selection = self.env[source['source_model']]._fields[source['source_field']].selection
            for _value, label in selection:
                if label not in labels:
                    labels.append(label)
        return labels

    @api.model
    def _job_stage_line_commands(self, mode):
        # 'both' concatenates the native labels with the suggested list —
        # the two can genuinely share a name (mrp.production's own native
        # states already include 'In Progress'/'Done', both also in
        # JOB_STAGE_SUGGESTED_NAMES), which would violate nord_sync.job.
        # stage's per-company name uniqueness on Confirm. Deduped here,
        # across both lists together, not just within each — native wins
        # the earlier sequence slot since it's added first.
        names = []
        if mode in ('native', 'both'):
            names += self._native_state_labels()
        if mode in ('own', 'both'):
            names += JOB_STAGE_SUGGESTED_NAMES
        names = list(dict.fromkeys(names))
        return [(5, 0, 0)] + [
            (0, 0, {'name': name, 'sequence': (i + 1) * 10}) for i, name in enumerate(names)
        ]

    @api.onchange('job_stage_mode')
    def _onchange_job_stage_mode(self):
        """Optional by design — an empty list here just means no job stage
        granularity, nord.job.state alone still works on the Core. Re-picking
        a mode replaces the list outright rather than trying
        to merge with whatever was there — simpler to reason about than a
        diff, and nothing is pushed yet at this point (Confirm is what
        creates real records), so there's nothing costly to throw away.
        """
        for wiz in self:
            # Old stage lines are gone the instant job_stage_line_ids is
            # replaced below — any mapping row still pointing at one of them
            # would be stale, so every row's stage choice is cleared first
            # rather than only conditionally, then re-defaulted against the
            # fresh list. mapping_line_ids itself (the fixed set of native
            # source values) never changes with job_stage_mode — only which
            # stages are available to pick for each row does.
            wiz.mapping_line_ids.target_job_stage_line_id = False
            wiz.job_stage_line_ids = wiz._job_stage_line_commands(wiz.job_stage_mode)
            wiz._default_mapping_targets()

    # ── Mapping ──────────────────────────────────────────────────────────────

    @api.model
    def _mapping_line_vals(self):
        """One row per native value of every registered source model — the
        full range each source's own Nord Sync State Mapping mechanism
        supports, not narrowed to whichever values today's shipped Automation
        Rules happen to send. The client edits Automation Rules directly,
        so any of these could reach the bridge; a row left blank
        is simply unmapped, not removed — see the line model's own docstring.
        Rows from different sources are told apart by source_model, appended
        in whatever order _nord_sync_available_native_sources returns them.

        Plain vals dicts, not (0, 0, vals) O2M commands — see create()'s
        comment for why these are created directly server-side instead of
        going through mapping_line_ids in a create/default_get payload.
        """
        vals = []
        sequence = 0
        for source in self._nord_sync_available_native_sources():
            selection = self.env[source['source_model']]._fields[source['source_field']].selection
            for value, label in selection:
                sequence += 10
                vals.append({
                    'sequence': sequence,
                    'source_model': source['source_model'],
                    'source_label': source.get('label') or source['source_model'],
                    'source_value': value,
                    'source_value_label': label,
                })
        return vals

    def _default_mapping_targets(self):
        """Best-effort per-row default: native/both modes create a stage
        literally named after the row's own label (mirrors the source
        field's own labels, e.g. a 'Confirmed' row gets the 'Confirmed'
        stage), so pre-select those — own mode has no such anchor, stays
        blank for the client to pick (or leave unmapped) by hand. Only fills
        in what's currently unset, never overwrites a deliberate choice —
        callers that want a clean slate reset target_job_stage_line_id first
        themselves (see _onchange_job_stage_mode).
        """
        self.ensure_one()
        stage_line_by_name = {line.name: line for line in self.job_stage_line_ids}
        for map_line in self.mapping_line_ids:
            if not map_line.target_job_stage_line_id:
                match = stage_line_by_name.get(map_line.source_value_label)
                if match:
                    map_line.target_job_stage_line_id = match.id

    # ── Step: Job Naming ─────────────────────────────────────────────────────────

    def run_after_step_job_naming(self):
        if self.job_naming_mode == 'custom_prefix' and not self.job_naming_custom_prefix:
            raise UserError('Fill in the custom prefix before continuing.')
        return True

    # ── Step: Finish ─────────────────────────────────────────────────────────────

    def action_confirm(self):
        """Finish: saves the config, then hands off to the "Nord Sync:
        Automation Rules" list (data/nord_sync_automation.xml) instead of
        just closing — so the trigger criteria shipped by whichever Nord
        Sync Source addons are installed are the very next thing the person
        configuring this sees, ready to narrow if needed. Generic on
        purpose — the base wizard can't assume any one source's automation
        rule exists.
        """
        self.ensure_one()
        if not self.preflight_ok:
            raise UserError('Fix the environment issues before continuing (see pre-flight message).')
        config_rec = self.env['nord_sync.config']._get_or_create_for_company(self.company_id)
        config_rec.write({
            'enabled': True, 'company_uid': self.company_uid,
            'job_naming_mode': self.job_naming_mode,
            'job_naming_custom_prefix': self.job_naming_custom_prefix,
        })
        # Real records (and their push to the Core) only happen here, once
        # config.enabled is actually True — matches _nord_sync_notify's own
        # guard, and means nothing pushes for a wizard that gets cancelled.
        stage_lines = self.job_stage_line_ids
        real_stages = self.env['nord_sync.job.stage'].create([
            {'name': line.name, 'sequence': line.sequence, 'company_id': self.company_id.id}
            for line in stage_lines
        ])
        # create_multi preserves vals_list order, so this zip is a real
        # correspondence — the only way to translate a transient line (chosen
        # in each mapping row's target_job_stage_line_id) into the real stage
        # id the mapping row actually needs to point at.
        real_stage_id_by_line_id = dict(zip(stage_lines.ids, real_stages.ids))
        for map_line in self.mapping_line_ids:
            # Job state is never a wizard choice at all (see the line
            # model's own docstring) — only a real job-stage choice is
            # worth a persisted/pushed row.
            if not map_line.target_job_stage_line_id:
                continue
            config_rec._ensure_state_mapping(
                map_line.source_model, map_line.source_value,
                target_job_stage_id=real_stage_id_by_line_id.get(map_line.target_job_stage_line_id.id, False),
            )
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'base.automation',
            'domain': [('name', 'like', 'Nord Sync')],
            'view_mode': 'list,form',
            'target': 'current',
        }
