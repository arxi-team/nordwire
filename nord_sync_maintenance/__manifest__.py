# -*- coding: utf-8 -*-
{
    'name': 'Nordwire: Maintenance',
    'version': '1.0.0',
    'category': 'Manufacturing/Maintenance',
    'summary': 'Nordwire source: maintenance.request.',
    'description': """
Nordwire: Maintenance
========================

`maintenance.request` as a Nordwire Source — produces a `nord.job` on the
Core on create, `operation_type='maintenance'`.

Auto-installs the moment both `nord_sync` and `maintenance` are present —
never a manual step, never its own tile on the Apps screen
(`application: False`). A client that never installs `maintenance` never
sees this addon exist at all.
    """,
    'author': 'NORD / Nordwire',
    'license': 'LGPL-3',
    'depends': ['nord_sync', 'maintenance'],
    'data': [
        'data/nord_sync_automation.xml',
    ],
    'installable': True,
    'auto_install': False,  # installed by the Sources step's action_confirm_sources, never auto
    'application': False,
}
