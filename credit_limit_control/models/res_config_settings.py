from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    custom_credit_limit = fields.Boolean(
        related="company_id.custom_credit_limit",
        readonly=False,
    )
    company_currency_id = fields.Many2one(
        related="company_id.currency_id",
    )
    company_default_credit_limit = fields.Monetary(
        related="company_id.default_credit_limit",
        currency_field="company_currency_id",
        readonly=False,
    )
    combine_credit_limits_across_companies = fields.Boolean(
        related="company_id.combine_credit_limits_across_companies",
        readonly=False,
    )
    exclude_sales_order_amount_from_credit_limit = fields.Boolean(
        related="company_id.exclude_sales_order_amount_from_credit_limit",
        readonly=False,
    )
    block_sales_order_on_credit_limit = fields.Boolean(
        related="company_id.block_sales_order_on_credit_limit",
        readonly=False,
    )
    exclude_delivery_amount_from_credit_limit = fields.Boolean(
        related="company_id.exclude_delivery_amount_from_credit_limit",
        readonly=False,
    )
    block_delivery_on_credit_limit = fields.Boolean(
        related="company_id.block_delivery_on_credit_limit",
        readonly=False,
    )
    exclude_invoice_amount_from_credit_limit = fields.Boolean(
        related="company_id.exclude_invoice_amount_from_credit_limit",
        readonly=False,
    )
    block_invoice_on_credit_limit = fields.Boolean(
        related="company_id.block_invoice_on_credit_limit",
        readonly=False,
    )
    shared_credit_limit_amount = fields.Float(
        string="Shared Credit Limit Amount",
        config_parameter="credit_limit_control.shared_credit_limit_amount",
    )
    all_companies_use_custom_credit_limit = fields.Boolean(
        compute="_compute_all_companies_use_custom_credit_limit",
    )
    all_companies_use_same_currency = fields.Boolean(
        compute="_compute_all_companies_use_custom_credit_limit",
    )

    @api.depends("custom_credit_limit")
    def _compute_all_companies_use_custom_credit_limit(self):
        companies = self.env["res.company"].search([])
        for settings in self:
            settings.all_companies_use_custom_credit_limit = bool(companies) and all(
                company.custom_credit_limit or company == settings.company_id and settings.custom_credit_limit
                for company in companies
            )
            settings.all_companies_use_same_currency = len(companies.currency_id) <= 1

    @api.onchange("custom_credit_limit")
    def _onchange_custom_credit_limit(self):
        if self.custom_credit_limit:
            self.account_use_credit_limit = False
        else:
            self.combine_credit_limits_across_companies = False

    @api.onchange("account_use_credit_limit")
    def _onchange_account_use_credit_limit(self):
        if self.account_use_credit_limit:
            self.custom_credit_limit = False
            self.combine_credit_limits_across_companies = False
