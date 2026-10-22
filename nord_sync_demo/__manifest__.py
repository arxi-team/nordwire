# -*- coding: utf-8 -*-
{
    'name': 'Nordwire: Demo Data Generator',
    'version': '1.0.0',
    'category': 'Manufacturing',
    'summary': 'Scheduled job that keeps generating finished SK Coffee MOs, to demo the Workorder Bridge live.',
    'description': """
Nordwire: Demo Data Generator
==============================

One cron, loaded only as demo data (never installed on a real client): every
few minutes it picks a real BOM and a real employee already in this
database, runs a full MO lifecycle (create, confirm, start the workorder as
that employee, pass its quality checks, finish, Mark Done), and lets the
existing Workorder/Resource Bridges push it to the Core as usual.

Exists purely to keep a demo environment visibly alive — the Core side
should pair with its own cron pulling the Nordwire sync queue on the same
cadence.
    """,
    'author': 'NORD / Nordwire',
    'license': 'LGPL-3',
    'depends': ['nord_sync_mrp'],
    'data': [],
    'demo': [
        'data/demo_cron.xml',
    ],
    'installable': True,
    'auto_install': False,
    'application': False,
}
