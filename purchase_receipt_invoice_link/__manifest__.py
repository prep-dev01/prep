{
    "name": "PURCHASE_RECEIPT_INVOICE_LINK",
    "version": "19.0.1.0.0",
    "summary": "Create vendor bills from purchase receipts",
    "category": "Purchases",
    "author": "PREP DESK LLP",
    "license": "LGPL-3",
    "depends": ["purchase_stock", "account"],
    "data": [
        "views/account_move_views.xml",
        "views/stock_picking_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "purchase_receipt_invoice_link/static/src/components/purchase_receipt_bill_uploader/purchase_receipt_bill_uploader.js",
            "purchase_receipt_invoice_link/static/src/components/purchase_receipt_bill_uploader/purchase_receipt_bill_uploader.xml",
        ],
    },
    "installable": True,
    "application": True,
}
