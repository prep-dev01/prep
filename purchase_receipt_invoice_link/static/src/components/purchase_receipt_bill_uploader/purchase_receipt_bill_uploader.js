import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { FileUploader } from "@web/views/fields/file_handler";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

import { Component } from "@odoo/owl";


export class PurchaseReceiptBillUploader extends Component {
    static template = "purchase_receipt_invoice_link.PurchaseReceiptBillUploader";
    static components = { FileUploader };
    static props = {
        ...standardWidgetProps,
    };

    setup() {
        this.action = useService("action");
        this.notification = useService("notification");
        this.orm = useService("orm");
        this.attachmentIds = [];
    }

    get pickingId() {
        return this.props.record.resId || this.props.record.data.id;
    }

    async onFileUploaded(file) {
        const [attachmentId] = await this.orm.create("ir.attachment", [{
            name: file.name,
            mimetype: file.type,
            datas: file.data,
        }]);
        this.attachmentIds.push(attachmentId);
    }

    async onUploadComplete() {
        if (!this.attachmentIds.length) {
            return;
        }
        const attachmentIds = this.attachmentIds;
        this.attachmentIds = [];
        const action = await this.orm.call(
            "stock.picking",
            "action_create_vendor_bill_from_purchase_receipt",
            [[this.pickingId], attachmentIds]
        );
        this.notification.add(_t("Vendor bill created from purchase receipt."), {
            type: "success",
        });
        this.action.doAction(action);
    }
}

export const purchaseReceiptBillUploader = {
    component: PurchaseReceiptBillUploader,
    fieldDependencies: [
        { name: "id", type: "integer" },
    ],
};

registry.category("view_widgets").add(
    "purchase_receipt_bill_uploader",
    purchaseReceiptBillUploader
);
