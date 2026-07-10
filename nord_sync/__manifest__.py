{
    'name': 'Nord Sync',
    'summary': 'Sync production data to Nord via a local queue and outbound webhook',
    'description': """
Phase 1 (Fundação): sync queue mechanism, install wizard, the native
Odoo->Cloud webhook leg (Automation Rule + "Send Webhook Notification" server
action, no custom POST/retry code), and the authenticated pull-by-seq endpoint
for the Nord Core to consume. No source-model (mrp.production) logic yet - see
docs/PLAN.md for the full roadmap.
""",
    'version': '19.0.1.0.0',
    'category': 'Manufacturing',
    'author': 'Nordwire Electronics',
    'license': 'LGPL-3',
    'depends': ['base', 'base_automation'],
    'data': [
        'security/nord_sync_security.xml',
        'security/ir.model.access.csv',
        'views/nord_sync_queue_views.xml',
        'views/nord_sync_config_views.xml',
        'wizard/nord_sync_setup_wizard_views.xml',
        'views/nord_sync_menus.xml',
        'data/nord_sync_automation.xml',
    ],
    'installable': True,
    'application': False,
}
