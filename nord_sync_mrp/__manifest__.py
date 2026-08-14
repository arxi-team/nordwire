# -*- coding: utf-8 -*-
{
    'name': 'Nord Sync: MRP',
    'version': '1.0.0',
    'category': 'Manufacturing',
    'summary': 'Nord Sync Source: bridges mrp.production (plus BOM/Resource/Timesheet) to the Nord Core.',
    'description': """
Nord Sync Source addon — installing this addon is how a client opts
`mrp.production` into the Nord Sync bridge as a job-producing source. Also
carries the BOM/Resource/Timesheet Bridge, which only makes sense with
mrp.production active. Depends on `nord_sync` (the generic queue/webhook/
config machinery), `mrp`, and `mrp_workorder` (Enterprise Shop Floor) —
the latter only for its `employee_assigned_ids` field, so the Workorder
Bridge can name the person allocated to a workorder, not just its
work center. Never forces installing `sale`/`project`/`maintenance`.
    """,
    'author': 'NORD / Nordwire',
    'license': 'LGPL-3',
    'depends': ['nord_sync', 'mrp', 'mrp_workorder'],
    'data': [
        'data/nord_sync_automation.xml',
    ],
    'installable': True,
    'auto_install': False,
    'post_init_hook': 'post_init_hook',
    'application': False,
}
