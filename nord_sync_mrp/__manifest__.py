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
mrp.production active. Depends only on `nord_sync` (the generic queue/
webhook/config machinery) and `mrp` — never forces installing
`sale`/`project`/`maintenance`.
    """,
    'author': 'NORD / Nordwire',
    'license': 'LGPL-3',
    'depends': ['nord_sync', 'mrp'],
    'data': [
        'data/nord_sync_automation.xml',
    ],
    'installable': True,
    'auto_install': False,
    'application': False,
}
