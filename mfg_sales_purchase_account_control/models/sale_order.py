from odoo import fields, models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    project_required = fields.Boolean(string="Project Required")
    manufacturing_required = fields.Boolean(string="Manufacturing Required")
    auto_purchase_required = fields.Boolean(string="Auto Purchase Required")
    expected_delivery_date = fields.Date(string="Expected Delivery Date")
    profitability_margin = fields.Float(string="Profit Margin %")

    manufacturing_order_count = fields.Integer(compute="_compute_related_counts")
    purchase_order_count = fields.Integer(compute="_compute_related_counts")
    project_task_count = fields.Integer(compute="_compute_related_counts")

    def _compute_related_counts(self):
        for order in self:
            order.manufacturing_order_count = self.env["mrp.production"].search_count([
                ("origin", "=", order.name)
            ])
            order.purchase_order_count = self.env["purchase.order"].search_count([
                ("origin", "=", order.name)
            ])
            order.project_task_count = self.env["project.task"].search_count([
                ("sale_order_id", "=", order.id)
            ])

    def action_confirm(self):
        result = super().action_confirm()
        for order in self:
            if order.project_required:
                order._create_project_task()
        return result

    def _create_project_task(self):
        project = self.env["project.project"].search([], limit=1)
        if not project:
            project = self.env["project.project"].create({
                "name": "Sales Projects",
            })
        self.env["project.task"].create({
            "name": self.name,
            "project_id": project.id,
            "partner_id": self.partner_id.id,
            "sale_order_id": self.id,
        })