{
    'name': 'Autonomous Sales Co-Pilot (NVIDIA AI)',
    'version': '1.0',
    'author': 'BuildOdoo Hackathon',
    'category': 'Sales/CRM',
    'summary': 'AI-driven RFQ to Draft Quotation agent powered by NVIDIA NIM',
    'depends': ['crm', 'sale_management', 'stock'],
    'data': [
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
        'views/crm_lead_views.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
