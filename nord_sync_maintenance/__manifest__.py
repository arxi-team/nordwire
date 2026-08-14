# -*- coding: utf-8 -*-
{
    'name': 'Nord Sync: Maintenance',
    'version': '1.0.0',
    'category': 'Manufacturing',
    'summary': 'Nord Sync Source: bridges maintenance.request to a Nord Core nord.job.',
    'description': """
Nord Sync Source addon — installing this addon is how a client opts
`maintenance.request` into the Nord Sync bridge as a job-producing source.
Depends only on `nord_sync` (the generic queue/webhook/config machinery)
and `maintenance` — never forces installing any other business app.
    """,
    'author': 'NORD / Nordwire',
    'license': 'LGPL-3',
    'depends': ['nord_sync', 'maintenance'],
    'data': [
        'data/nord_sync_automation.xml',
    ],
    'installable': True,
    'auto_install': False,
    'post_init_hook': 'post_init_hook',
    'application': False,
}
