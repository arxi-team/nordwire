# -*- coding: utf-8 -*-
{
    'name': 'Nord Sync: Manufacturing',
    'version': '1.0.0',
    'category': 'Manufacturing',
    'summary': 'Nord Sync source: mrp.production, plus the BOM/Resource/Employee/Workorder/Quality '
               'Check Bridges that support it.',
    'description': """
Nord Sync: Manufacturing
=========================

`mrp.production` as a Nord Sync Source (produces `nord.job` on the Core), and
every model that only exists to support it — `mrp.workcenter`/`hr.employee`
(Resource/Employee Bridge, `edge.resource`), `mrp.bom` (BOM Bridge,
`nord.bom`), `mrp.workorder` (Workorder Bridge, `nord.job.resource`),
`quality.check` (Quality Check Bridge, `nord.tasks`). None of these support
models are Nord Sync Sources of their own — they never produce a `nord.job`
by themselves, only alongside the MO they belong to, so they live here
instead of getting their own addon each.

Auto-installs the moment both `nord_sync` and `mrp` (`mrp_workorder` too, for
the Workorder Bridge) are present — never a manual step, never its own tile
on the Apps screen (`application: False`). A client that never installs
`mrp` never sees this addon exist at all.
    """,
    'author': 'NORD / Nordwire',
    'license': 'LGPL-3',
    'depends': ['nord_sync', 'mrp', 'mrp_workorder'],
    'data': [
        'data/nord_sync_automation.xml',
        'views/mrp_workcenter_views.xml',
    ],
    'installable': True,
    'auto_install': False,  # installed by the Sources step's action_confirm_sources, never auto
    'application': False,
    'post_init_hook': 'post_init_hook',
}
