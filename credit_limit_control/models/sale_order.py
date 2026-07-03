from odoo import api, models
from odoo.exceptions import ValidationError


class SaleOrder(models.Model):
    _inherit = "sale.order"

    @api.depends(
        "company_id",
        "company_id.block_sales_order_on_credit_limit",
        "partner_id",
        "amount_total",
    )
    def _compute_partner_credit_warning(self):
        super()._compute_partner_credit_warning()
        for order in self.filtered(
            lambda item: (
                item.state in ("draft", "sent")
                and item.company_id.custom_credit_limit
                and not item.company_id.exclude_sales_order_amount_from_credit_limit
            )
        ):
            order.partner_credit_warning = self.env[
                "account.move"
            ]._build_custom_credit_warning_message(
                order,
                current_amount=order.amount_total / order.currency_rate,
            )
    def _check_partner_credit_limit_on_save(self):
        for order in self.filtered(
            lambda item: (
                item.state in ("draft", "sent")
                and (
                    item.company_id.account_use_credit_limit
                    or item.company_id.custom_credit_limit
                )
                and item.company_id.block_sales_order_on_credit_limit
                and item.partner_credit_warning
            )
        ):
            raise ValidationError(order.partner_credit_warning)

    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        orders._check_partner_credit_limit_on_save()
        return orders

    def write(self, vals):
        result = super().write(vals)
        self._check_partner_credit_limit_on_save()
        return result

    def action_confirm(self):
        self._check_partner_credit_limit_on_save()
        return super().action_confirm()
