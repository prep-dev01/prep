from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    auto_manufacture_from_sale = fields.Boolean(string="Auto Manufacture From Sale")
    auto_purchase_missing_components = fields.Boolean(string="Auto Purchase Missing Components")