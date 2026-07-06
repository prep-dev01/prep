from collections import defaultdict

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
                ("name", "=", order.name),
                ("partner_id", "=", order.partner_id.id),
            ])

    def action_confirm(self):
        result = super().action_confirm()
        for order in self:
            if order.project_required:
                order._create_project_task()
            if order.manufacturing_required:
                order._create_manufacturing_orders()
            if order.auto_purchase_required:
                order._create_purchase_orders_for_missing_components()
        return result

    def _create_project_task(self):
        existing_task = self.env["project.task"].search([
            ("name", "=", self.name),
            ("partner_id", "=", self.partner_id.id),
        ], limit=1)
        if existing_task:
            return existing_task

        project = self.env["project.project"].search([], limit=1)
        if not project:
            project = self.env["project.project"].create({
                "name": "Sales Projects",
            })
        return self.env["project.task"].create({
            "name": self.name,
            "project_id": project.id,
            "partner_id": self.partner_id.id,
        })

    def _create_manufacturing_orders(self):
        for line in self.order_line.filtered(lambda sale_line: sale_line.product_id.type == "consu"):
            product = line.product_id
            if not product.product_tmpl_id.auto_manufacture_from_sale:
                continue

            bom = self._get_product_bom(product)
            if not bom:
                continue

            existing_mo = self.env["mrp.production"].search([
                ("origin", "=", self.name),
                ("product_id", "=", product.id),
            ], limit=1)
            if existing_mo:
                continue

            self.env["mrp.production"].create({
                "product_id": product.id,
                "product_qty": line.product_uom_qty,
                "product_uom_id": line.product_uom_id.id,
                "bom_id": bom.id,
                "origin": self.name,
                "company_id": self.company_id.id,
                "date_start": fields.Datetime.now(),
            })

    def _create_purchase_orders_for_missing_components(self):
        order_lines_by_vendor = defaultdict(list)

        for line in self.order_line.filtered(lambda sale_line: sale_line.product_id.type == "consu"):
            product = line.product_id
            if not product.product_tmpl_id.auto_purchase_missing_components:
                continue

            bom = self._get_product_bom(product)
            if not bom:
                continue

            factor = line.product_uom_qty / (bom.product_qty or 1.0)
            for bom_line in bom.bom_line_ids:
                component = bom_line.product_id
                required_qty = bom_line.product_qty * factor
                required_qty = bom_line.product_uom_id._compute_quantity(
                    required_qty,
                    component.uom_id,
                )
                missing_qty = required_qty - component.qty_available
                if missing_qty <= 0:
                    continue

                seller = component.seller_ids[:1]
                if not seller:
                    continue

                vendor = seller.partner_id
                order_lines_by_vendor[vendor].append((component, missing_qty, seller))

        for vendor, component_lines in order_lines_by_vendor.items():
            purchase_order = self.env["purchase.order"].search([
                ("partner_id", "=", vendor.id),
                ("origin", "=", self.name),
                ("state", "=", "draft"),
            ], limit=1)
            if not purchase_order:
                purchase_order = self.env["purchase.order"].create({
                    "partner_id": vendor.id,
                    "origin": self.name,
                    "company_id": self.company_id.id,
                })

            for component, missing_qty, seller in component_lines:
                existing_line = purchase_order.order_line.filtered(
                    lambda po_line: po_line.product_id == component
                )
                if existing_line:
                    continue

                self.env["purchase.order.line"].create({
                    "order_id": purchase_order.id,
                    "product_id": component.id,
                    "name": component.display_name,
                    "product_qty": missing_qty,
                    "product_uom_id": component.uom_id.id,
                    "price_unit": seller.price or component.standard_price,
                    "date_planned": fields.Datetime.now(),
                })

    def _get_product_bom(self, product):
        return self.env["mrp.bom"].search([
            ("type", "=", "normal"),
            "|",
            ("product_id", "=", product.id),
            "&",
            ("product_id", "=", False),
            ("product_tmpl_id", "=", product.product_tmpl_id.id),
        ], limit=1)
