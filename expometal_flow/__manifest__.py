{
    'name': 'EXPOMETAL · Painel da linha de produção (Nordwire × Arxi × SK Coffee)',
    'summary': 'Painel de ecrã inteiro da linha: Ordens de Trabalho → Torra → Embalamento → Entregue, ao vivo deste Odoo',
    'description': """
Painel de ecrã inteiro do stand EXPOMETAL 2026, servido pelo próprio Odoo como ecrã 'Flow' das Dashboards Kioda (público):

* /flow/v5/?clean — Linha de produção (Ordens de Trabalho → Torra → Embalamento → Entregue)

Os dados vêm só deste Odoo, em leitura: ordens de fabrico, ordens de trabalho nos centros de torra e de embalamento
(sessões, paragens, operador), entregas prontas e o resumo de produção de cada entrega validada.
O endereço /flow/v5/?clean dá o modo de ecrã de stand.
""",
    'version': '19.0.2.0.0',
    'category': 'Manufacturing',
    'author': 'Arxi',
    'license': 'LGPL-3',
    'depends': ['mrp', 'sale_mrp', 'crm', 'kioda_dashboards'],
    'data': ['views/devices.xml', 'data/kioda_dashboard.xml'],
    'installable': True,
    'application': False,
}
