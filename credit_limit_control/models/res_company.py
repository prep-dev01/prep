from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ResCompany(models.Model):
    _inherit = "res.company"

    custom_credit_limit = fields.Boolean(
        string="Custom Credit Limit",
        help="Enable the custom credit limit mode instead of the standard sales credit limit.",
    )

    default_credit_limit = fields.Monetary(
        string="Default Credit Limit",
        currency_field="currency_id",
    )

    combine_credit_limits_across_companies = fields.Boolean(
        string="Use Shared Credit Limit Across Companies",
        help="Allow a partner credit limit to combine the default limits of multiple companies.",
    )

    exclude_sales_order_amount_from_credit_limit = fields.Boolean(
        string="Exclude Sales Order Amount from Credit Limit",
        help="Allow sales orders to bypass credit-limit checks and exclude their amounts from the customer's consumed credit.",
    )

    block_sales_order_on_credit_limit = fields.Boolean(
        string="Block Sales Orders on Credit Limit",
        help="Prevent saving or confirming sales orders when the customer exceeds the active credit limit.",
    )

    exclude_delivery_amount_from_credit_limit = fields.Boolean(
        string="Exclude Delivery Amount from Credit Limit",
        help="Allow deliveries to bypass credit-limit checks.",
    )

    block_delivery_on_credit_limit = fields.Boolean(
        string="Block Deliveries on Credit Limit",
        help="Prevent validating deliveries when the customer exceeds the active credit limit.",
    )

    exclude_invoice_amount_from_credit_limit = fields.Boolean(
        string="Exclude Invoice Amount from Credit Limit",
        help="Allow customer invoices to bypass credit-limit checks.",
    )

    block_invoice_on_credit_limit = fields.Boolean(
        string="Block Invoices on Credit Limit",
        help="Prevent saving or posting customer invoices when the customer exceeds the active credit limit.",
    )

    def write(self, vals):
        vals = dict(vals)
        if vals.get("custom_credit_limit"):
            vals["account_use_credit_limit"] = False
        elif vals.get("account_use_credit_limit"):
            vals["custom_credit_limit"] = False
        if vals.get("combine_credit_limits_across_companies"):
            companies = self.search([])
            if any(
                not (
                    company.custom_credit_limit
                    or company in self and vals.get("custom_credit_limit")
                )
                for company in companies
            ):
                raise ValidationError(
                    "Enable Custom Credit Limit for every company before using shared credit limits across companies."
                )
            if len(companies.currency_id) > 1:
                raise ValidationError(
                    "All companies must use the same base currency before using shared credit limits across companies."
                )
        if vals.get("custom_credit_limit") is False:
            self.search([]).with_context(skip_shared_credit_limit_sync=True).write(
                {"combine_credit_limits_across_companies": False}
            )
        result = super().write(vals)
        if (
            vals.get("combine_credit_limits_across_companies")
            and not self.env.context.get("skip_shared_credit_limit_sync")
        ):
            self.search([]).default_credit_limit = 0.0
        if (
            "combine_credit_limits_across_companies" in vals
            and not self.env.context.get("skip_shared_credit_limit_sync")
        ):
            (self.search([]) - self).with_context(skip_shared_credit_limit_sync=True).write(
                {
                    "combine_credit_limits_across_companies": vals[
                        "combine_credit_limits_across_companies"
                    ]
                }
            )
        return result

    @api.constrains(
        "account_use_credit_limit",
        "custom_credit_limit",
        "combine_credit_limits_across_companies",
        "currency_id",
    )
    def _check_credit_limit_mode(self):
        companies = self.search([])
        for company in self:
            if company.account_use_credit_limit and company.custom_credit_limit:
                raise ValidationError(
                    "Sales Credit Limit and Custom Credit Limit cannot be enabled at the same time."
                )
            if (
                company.combine_credit_limits_across_companies
                and companies.filtered(lambda item: not item.custom_credit_limit)
            ):
                raise ValidationError(
                    "Enable Custom Credit Limit for every company before using shared credit limits across companies."
                )
            if (
                company.combine_credit_limits_across_companies
                and len(companies.currency_id) > 1
            ):
                raise ValidationError(
                    "All companies must use the same base currency before using shared credit limits across companies."
                )
