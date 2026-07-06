from odoo import fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    purchase_receipt_picking_id = fields.Many2one(
        "stock.picking",
        string="Purchase Receipt",
        copy=False,
        index=True,
    )
    purchase_receipt_picking_count = fields.Integer(
        compute="_compute_purchase_receipt_picking_count",
        string="Purchase Receipt Count",
    )

    def _compute_purchase_receipt_picking_count(self):
        for move in self:
            move.purchase_receipt_picking_count = (
                1 if move.purchase_receipt_picking_id else 0
            )

    def action_view_purchase_receipt_picking(self):
        self.ensure_one()
        picking = self.purchase_receipt_picking_id
        action = self.env["ir.actions.actions"]._for_xml_id(
            "stock.action_picking_tree_all"
        )
        action["context"] = {
            "default_partner_id": self.partner_id.id,
            "default_origin": self.invoice_origin,
        }
        action["domain"] = [("id", "=", picking.id)]
        action["views"] = [
            (self.env.ref("stock.view_picking_form").id, "form"),
            *[
                (view_id, view_type)
                for view_id, view_type in action.get("views", [])
                if view_type != "form"
            ],
        ]
        action["res_id"] = picking.id
        return action


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    purchase_receipt_picking_id = fields.Many2one(
        "stock.picking",
        string="Purchase Receipt",
        copy=False,
        index=True,
    )
