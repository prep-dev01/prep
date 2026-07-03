from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    show_custom_credit_limit = fields.Boolean(
        compute="_compute_show_custom_credit_limit",
        groups="account.group_account_invoice,account.group_account_readonly",
    )
    show_shared_credit_limit_companies = fields.Boolean(
        compute="_compute_show_custom_credit_limit",
        groups="account.group_account_invoice,account.group_account_readonly",
    )
    use_custom_partner_credit_limit = fields.Boolean(
        string="Partner Limit",
        groups="account.group_account_invoice,account.group_account_readonly",
        help="Use the total default credit limit of the selected companies.",
    )
    custom_credit_company_ids = fields.Many2many(
        comodel_name="res.company",
        relation="res_partner_custom_credit_company_rel",
        column1="partner_id",
        column2="company_id",
        string="Companies",
        domain=[("custom_credit_limit", "=", True)],
        groups="account.group_account_invoice,account.group_account_readonly",
    )
    custom_credit_limit_total = fields.Monetary(
        string="Total Credit Limit",
        currency_field="currency_id",
        compute="_compute_custom_credit_limit_total",
        inverse="_inverse_custom_credit_limit_total",
        groups="account.group_account_invoice,account.group_account_readonly",
    )
    custom_credit_limit_amount = fields.Monetary(
        string="Partner Credit Limit",
        currency_field="currency_id",
        groups="account.group_account_invoice,account.group_account_readonly",
    )

    @api.depends_context("company")
    def _compute_show_custom_credit_limit(self):
        for partner in self:
            partner.show_custom_credit_limit = self.env.company.custom_credit_limit
            partner.show_shared_credit_limit_companies = (
                self.env.company.combine_credit_limits_across_companies
            )

    @api.depends_context("company")
    @api.depends(
        "use_custom_partner_credit_limit",
        "custom_credit_limit_amount",
        "custom_credit_company_ids",
        "custom_credit_company_ids.default_credit_limit",
        "custom_credit_company_ids.currency_id",
    )
    def _compute_custom_credit_limit_total(self):
        target_company = self.env.company
        target_currency = target_company.currency_id
        conversion_date = fields.Date.context_today(self)
        shared_credit_limit_amount = float(
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("credit_limit_control.shared_credit_limit_amount", 0.0)
        )
        for partner in self:
            if not partner.use_custom_partner_credit_limit:
                partner.custom_credit_limit_total = 0.0
                continue
            if partner.custom_credit_limit_amount:
                partner.custom_credit_limit_total = partner.custom_credit_limit_amount
                continue
            if target_company.combine_credit_limits_across_companies:
                partner.custom_credit_limit_total = (
                    shared_credit_limit_amount * len(partner.custom_credit_company_ids)
                )
                continue
            companies = (
                target_company
            )
            partner.custom_credit_limit_total = sum(
                company.currency_id._convert(
                    company.default_credit_limit,
                    target_currency,
                    target_company,
                    conversion_date,
                )
                for company in companies
            )

    def _inverse_custom_credit_limit_total(self):
        for partner in self:
            partner.custom_credit_limit_amount = partner.custom_credit_limit_total

    @api.onchange("use_custom_partner_credit_limit")
    def _onchange_use_custom_partner_credit_limit(self):
        if (
            self.use_custom_partner_credit_limit
            and (
                not self.custom_credit_company_ids
                or not self.env.company.combine_credit_limits_across_companies
            )
            and self.env.company.custom_credit_limit
        ):
            self.custom_credit_company_ids = self.env.company
        if self.use_custom_partner_credit_limit and not self.custom_credit_limit_amount:
            self.custom_credit_limit_amount = self._origin.custom_credit_limit_total

    def _compute_credit_to_invoice(self):
        super()._compute_credit_to_invoice()
        company = self.env.company
        if not company.custom_credit_limit:
            return
        commercial_partners = self.commercial_partner_id & self
        if not commercial_partners:
            return
        sale_orders = self.env["sale.order"].search([
            ("company_id", "=", self.env.company.id),
            ("partner_invoice_id", "any", [
                ("commercial_partner_id", "in", commercial_partners.ids),
            ]),
            ("order_line", "any", [("untaxed_amount_to_invoice", ">", 0)]),
            ("state", "=", "sale"),
        ])
        for (partner, currency), orders in sale_orders.grouped(
            lambda order: (order.partner_invoice_id, order.currency_id),
        ).items():
            amount_to_invoice = sum(orders.mapped("amount_to_invoice"))
            converted_amount = currency._convert(
                amount_to_invoice,
                company.currency_id,
                company,
                fields.Date.context_today(self),
            )
            if company.custom_credit_limit:
                partner.commercial_partner_id.credit_to_invoice += converted_amount
