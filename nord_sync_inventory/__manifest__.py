# -*- coding: utf-8 -*-
{
    'name': 'Nord Sync: Inventory',
    'version': '1.0.0',
    'category': 'Inventory/Inventory',
    'summary': 'Nord Sync source: stock.picking.',
    'description': """
Nord Sync: Inventory
======================

`stock.picking` as a Nord Sync Source — produces a `nord.job` on the Core
on create, `operation_type='inventory'`.

Auto-installs the moment both `nord_sync` and `stock` are present — never a
manual step, never its own tile on the Apps screen (`application: False`). A
client that never installs `stock` never sees this addon exist at all.
    """,
    'author': 'NORD / Nordwire',
    'license': 'LGPL-3',
    'depends': ['nord_sync', 'stock'],
    'data': [
        'data/nord_sync_automation.xml',
    ],
    'installable': True,
    'auto_install': False,  # installed by the Sources step's action_confirm_sources, never auto
    'application': False,
}
