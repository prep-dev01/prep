from odoo import api, models, _
from odoo.exceptions import ValidationError
from odoo.tools import formatLang


class AccountMove(models.Model):
    _inherit = "account.move"

    @api.depends(
        "company_id",
        "company_id.block_invoice_on_credit_limit",
        "partner_id",
        "tax_totals",
        "currency_id",
    )
    def _compute_partner_credit_warning(self):
        super()._compute_partner_credit_warning()
        for move in self.filtered(
            lambda item: (
                item.state == "draft"
                and item.move_type == "out_invoice"
                and item.company_id.custom_credit_limit
            )
        ):
            total_field = (
                "total_amount_currency"
                if move.currency_id == move.company_currency_id
                else "total_amount"
            )
            move.partner_credit_warning = self._build_custom_credit_warning_message(
                move,
                current_amount=move.tax_totals[total_field],
                exclude_amount=move._get_partner_credit_warning_exclude_amount(),
            )
    def _build_custom_credit_warning_message(
        self, record, current_amount=0.0, exclude_amount=0.0
    ):
        partner = record.partner_id.commercial_partner_id
        if partner.use_custom_partner_credit_limit:
            credit_limit = partner.custom_credit_limit_total
        elif record.company_id.combine_credit_limits_across_companies:
            credit_limit = float(
                self.env["ir.config_parameter"]
                .sudo()
                .get_param("credit_limit_control.shared_credit_limit_amount", 0.0)
            )
        else:
            credit_limit = record.company_id.default_credit_limit
        total_credit = (
            partner.credit
            + partner.credit_to_invoice
            - exclude_amount
            + current_amount
        )
        if not credit_limit or total_credit <= credit_limit:
            return ""
        return _(
            "%(partner_name)s has reached its credit limit of: %(credit_limit)s",
            partner_name=partner.name,
            credit_limit=formatLang(
                self.env,
                credit_limit,
                currency_obj=record.company_id.currency_id,
            ),
        )

    def _check_partner_credit_limit_on_save(self):
        for move in self.filtered(
            lambda item: (
                item.state == "draft"
                and item.move_type == "out_invoice"
                and (
                    item.company_id.account_use_credit_limit
                    or item.company_id.custom_credit_limit
                )
                and item.company_id.block_invoice_on_credit_limit
                and item.partner_credit_warning
            )
        ):
            raise ValidationError(move.partner_credit_warning)

    @api.model_create_multi
    def create(self, vals_list):
        moves = super().create(vals_list)
        moves._check_partner_credit_limit_on_save()
        return moves

    def write(self, vals):
        result = super().write(vals)
        self._check_partner_credit_limit_on_save()
        return result

    def action_post(self):
        self._check_partner_credit_limit_on_save()
        return super().action_post()
