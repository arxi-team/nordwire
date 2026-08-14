# -*- coding: utf-8 -*-
{
    'name': 'Nord Sync: Purchase',
    'version': '1.0.0',
    'category': 'Purchases',
    'summary': 'Nord Sync Source: bridges purchase.order to a Nord Core nord.job.',
    'description': """
Nord Sync Source addon — installing this addon is how a client opts
`purchase.order` into the Nord Sync bridge as a job-producing source.
Depends only on `nord_sync` (the generic queue/webhook/config machinery)
and `purchase` — never forces installing any other business app.

Same minimal shape as `nord_sync_maintenance` (create-only, no product/
declaration/result push) — see that addon for the reference pattern this
mirrors.
    """,
    'author': 'NORD / Nordwire',
    'license': 'LGPL-3',
    'depends': ['nord_sync', 'purchase'],
    'data': [
        'data/nord_sync_automation.xml',
    ],
    'installable': True,
    'auto_install': False,
    'post_init_hook': 'post_init_hook',
    'application': False,
}
