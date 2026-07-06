{
    "name": "Manufacturing Sales Purchase Accounting Control",
    "version": "19.0.1.0.0",
    "summary": "Connect sales, purchase, MRP, inventory, accounting, project and timesheets",
    "category": "Operations",
    "author": "PREP DESK LLP",
    "license": "LGPL-3",
    "depends": [
        "sale_management",
        "purchase",
        "stock",
        "mrp",
        "account",
        "project",
        "hr_timesheet",
    ],
    "data": [
        "views/sale_order_views.xml",
        "views/product_template_views.xml",
        "views/menu_views.xml",
    ],
    "installable": True,
    "application": True,
}