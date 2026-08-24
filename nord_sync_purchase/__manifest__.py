# -*- coding: utf-8 -*-
{
    'name': 'Nord Sync: Purchase',
    'version': '1.0.0',
    'category': 'Inventory/Purchase',
    'summary': 'Nord Sync source: purchase.order.',
    'description': """
Nord Sync: Purchase
=====================

`purchase.order` as a Nord Sync Source — produces a `nord.job` on the Core
on create, `operation_type='purchase'`.

Auto-installs the moment both `nord_sync` and `purchase` are present — never
a manual step, never its own tile on the Apps screen (`application: False`).
A client that never installs `purchase` never sees this addon exist at all.
    """,
    'author': 'NORD / Nordwire',
    'license': 'LGPL-3',
    'depends': ['nord_sync', 'purchase'],
    'data': [
        'data/nord_sync_automation.xml',
    ],
    'installable': True,
    'auto_install': True,
    'application': False,
}
