{
    'name': 'Kioda Dashboards',
    'summary': 'Public dashboards for Kioda screens/devices',
    'author': 'ARXILEAD',
    'website': 'https://arxi.odoo.com/',
    'category': 'Manufacturing',
    'version': '19.0.1.0.0',
    'license': 'OPL-1',
    'depends': [
        'base',
        'web',
    ],
    'data': [
        'security/res_groups.xml',
        'security/ir.model.access.csv',
        'views/kioda_dashboards_views.xml',
        'views/js/main_dashboard_views.xml',
        'views/js/not_found_views.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'kioda_dashboards/static/src/owl/dashboards/*',
        ],
    },
    'icon': '/kioda_dashboards/static/description/icon.png',
    'installable': True,
    'application': True,
}
