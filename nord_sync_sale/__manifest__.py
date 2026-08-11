# -*- coding: utf-8 -*-
{
    'name': 'Nord Sync: Sale',
    'version': '1.0.0',
    'category': 'Sales',
    'summary': 'Nord Sync Source: bridges sale.order to a Nord Core nord.job.',
    'description': """
Nord Sync Source addon — installing this addon is how a client opts
`sale.order` into the Nord Sync bridge as a job-producing source. Depends
only on `nord_sync` (the generic queue/webhook/config machinery) and `sale`
— never forces installing any other business app.

Same minimal shape as `nord_sync_maintenance` (create-only, no product/
declaration/result push) — see that addon for the reference pattern this
mirrors.
    """,
    'author': 'NORD / Nordwire',
    'license': 'LGPL-3',
    'depends': ['nord_sync', 'sale'],
    'data': [
        'data/nord_sync_automation.xml',
    ],
    'installable': True,
    'auto_install': False,
    'application': False,
}
