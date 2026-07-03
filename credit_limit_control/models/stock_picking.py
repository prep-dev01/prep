from odoo import api, fields, models
from odoo.exceptions import ValidationError


class StockPicking(models.Model):
    _inherit = "stock.picking"

    partner_credit_warning = fields.Text(compute="_compute_partner_credit_warning")

    @api.depends(
        "company_id",
        "partner_id",
        "picking_type_code",
        "return_id",
        "move_ids.sale_line_id.order_id",
        "sale_id",
        "sale_id.amount_total",
        "state",
    )
    def _compute_partner_credit_warning(self):
        for picking in self:
            picking.partner_credit_warning = picking._get_partner_credit_warning()

    def _get_partner_credit_warning(self):
        self.ensure_one()
        if not (
            self._is_credit_limit_delivery_flow()
            and self.state not in ("done", "cancel")
            and (self.company_id.account_use_credit_limit or self.company_id.custom_credit_limit)
            and self.partner_id
        ):
            return ""
        current_amount = 0.0
        sale_order = self._get_credit_limit_sale_order()
        if sale_order:
            current_amount = sale_order.amount_total / sale_order.currency_rate
        if self.company_id.custom_credit_limit:
            return self.env["account.move"]._build_custom_credit_warning_message(
                sale_order or self,
                current_amount=current_amount,
            )
        return self.env["account.move"]._build_credit_warning_message(
            sale_order or self,
            current_amount=current_amount,
        )

    def _get_credit_limit_sale_order(self):
        self.ensure_one()
        sale_order = self.sale_id or self.move_ids.sale_line_id.order_id[:1]
        if not sale_order and self.return_id:
            sale_order = self.return_id._get_credit_limit_sale_order()
        return sale_order

    def _is_credit_limit_delivery_flow(self):
        self.ensure_one()
        return bool(
            self.picking_type_code == "outgoing"
            or self._get_credit_limit_sale_order()
            or self.return_id
        )

    def _check_partner_credit_limit_before_delivery(self):
        for picking in self.filtered(
            lambda item: (
                item._is_credit_limit_delivery_flow()
                and (
                    item.company_id.account_use_credit_limit
                    or item.company_id.custom_credit_limit
                )
                and item.company_id.block_delivery_on_credit_limit
                and item.partner_id
            )
        ):
            message = picking.partner_credit_warning
            if message:
                raise ValidationError(message)

    def button_validate(self):
        self._check_partner_credit_limit_before_delivery()
        return super().button_validate()
