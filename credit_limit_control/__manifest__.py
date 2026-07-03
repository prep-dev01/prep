{
    "name": "Credit Limit Control",
    "version": "19.0.1.0.0",
    "summary": "Choose between standard and custom sales credit limit modes",
    "category": "Accounting/Accounting",
    "author": "PREP DESK LLP",
    "license": "LGPL-3",
    "depends": ["sale_stock"],
    "data": [
        "views/res_config_settings_views.xml",
        "views/res_partner_views.xml",
        "views/stock_picking_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "credit_limit_control/static/src/fields/shared_credit_limit_boolean_field.js",
            "credit_limit_control/static/src/fields/shared_credit_limit_boolean_field.xml",
        ],
    },
    "installable": True,
    "application": False,
}
