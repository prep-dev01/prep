from odoo import fields, models, _
from odoo.exceptions import UserError


class StockPicking(models.Model):
    _inherit = "stock.picking"

    purchase_receipt_bill_ids = fields.Many2many(
        "account.move",
        compute="_compute_purchase_receipt_bills",
        string="Vendor Bills",
    )
    purchase_receipt_bill_count = fields.Integer(
        compute="_compute_purchase_receipt_bills",
        string="Vendor Bill Count",
    )

    def _compute_purchase_receipt_bills(self):
        AccountMove = self.env["account.move"]
        for picking in self:
            bills = AccountMove.search(
                [
                    ("purchase_receipt_picking_id", "=", picking.id),
                    ("move_type", "in", ("in_invoice", "in_refund")),
                ]
            )
            picking.purchase_receipt_bill_ids = bills
            picking.purchase_receipt_bill_count = len(bills)

    def action_view_purchase_receipt_bills(self):
        self.ensure_one()
        bills = self.purchase_receipt_bill_ids
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "account.action_move_in_invoice_type"
        )
        if len(bills) == 1:
            action["views"] = [(self.env.ref("account.view_move_form").id, "form")]
            action["res_id"] = bills.id
        else:
            action["domain"] = [("id", "in", bills.ids)]
        action["context"] = {
            "default_move_type": "in_invoice",
            "default_partner_id": self.partner_id.id,
        }
        return action

    def action_create_vendor_bill_from_purchase_receipt(self, attachment_ids=False):
        self.ensure_one()
        purchase_order = self.purchase_id
        if not purchase_order:
            raise UserError(_("This receipt is not linked to a purchase order."))

        invoice_lines = []
        for purchase_line in self.move_ids.purchase_line_id:
            receipt_qty = self._get_purchase_receipt_qty(purchase_line)
            billed_qty = self._get_purchase_receipt_billed_qty(purchase_line)
            quantity = receipt_qty - billed_qty
            if purchase_line.product_uom_id.compare(quantity, 0.0) <= 0:
                continue

            line_vals = purchase_line._prepare_account_move_line()
            line_vals.update(
                {
                    "quantity": quantity,
                    "purchase_receipt_picking_id": self.id,
                }
            )
            invoice_lines.append((0, 0, line_vals))

        if not invoice_lines:
            raise UserError(
                _(
                    "There is no remaining received quantity to bill for receipt %(receipt)s.",
                    receipt=self.name,
                )
            )

        invoice_vals = purchase_order.with_company(
            purchase_order.company_id
        )._prepare_invoice()
        invoice_vals.update(
            {
                "invoice_origin": "%s, %s" % (purchase_order.name, self.name),
                "purchase_receipt_picking_id": self.id,
                "invoice_line_ids": invoice_lines,
            }
        )
        bill = self.env["account.move"].with_context(
            default_move_type="in_invoice"
        ).create(invoice_vals)

        self._attach_uploaded_files_to_move(bill, attachment_ids)
        return purchase_order.action_view_invoice(bill)

    def _get_purchase_receipt_qty(self, purchase_line):
        self.ensure_one()
        quantity = 0.0
        moves = self.move_ids.filtered(
            lambda move: move.purchase_line_id == purchase_line
            and move.state != "cancel"
        )
        for move in moves:
            move_qty = move.quantity or move.product_uom_qty
            quantity += move.product_uom._compute_quantity(
                move_qty,
                purchase_line.product_uom_id,
                round=False,
            )
        return quantity

    def _get_purchase_receipt_billed_qty(self, purchase_line):
        self.ensure_one()
        lines = self.env["account.move.line"].search(
            [
                ("purchase_receipt_picking_id", "=", self.id),
                ("purchase_line_id", "=", purchase_line.id),
                ("move_id.state", "!=", "cancel"),
                ("move_id.move_type", "in", ("in_invoice", "in_refund")),
            ]
        )
        quantity = 0.0
        for line in lines:
            sign = -1 if line.move_id.move_type == "in_refund" else 1
            quantity += sign * line.product_uom_id._compute_quantity(
                line.quantity,
                purchase_line.product_uom_id,
                round=False,
            )
        return quantity

    def _attach_uploaded_files_to_move(self, move, attachment_ids=False):
        attachments = self.env["ir.attachment"].browse(attachment_ids or [])
        if not attachments:
            return
        move.with_context(skip_is_manually_modified=True)._extend_with_attachments(
            move._to_files_data(attachments),
            new=True,
        )
        move.message_post(attachment_ids=attachments.ids)
        attachments.write({"res_model": "account.move", "res_id": move.id})
