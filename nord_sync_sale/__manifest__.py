# -*- coding: utf-8 -*-
{
    'name': 'Nordwire: Sales',
    'version': '17.0.1.0.1',
    'category': 'Sales',
    'summary': 'Nordwire source: sale.order.',
    'description': """
Nordwire: Sales
=================

`sale.order` as a Nordwire Source — produces a `nord.job` on the Core on
create, `operation_type='sale'`.

Auto-installs the moment both `nord_sync` and `sale` are present — never a
manual step, never its own tile on the Apps screen (`application: False`). A
client that never installs `sale` never sees this addon exist at all.
    """,
    'author': 'NORD / Nordwire',
    'license': 'LGPL-3',
    'depends': ['nord_sync', 'sale'],
    'data': [
        'data/nord_sync_automation.xml',
    ],
    'installable': True,
    'auto_install': False,  # installed by the Sources step's action_confirm_sources, never auto
    'application': False,
}
