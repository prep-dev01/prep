import { _t } from "@web/core/l10n/translation";
import { CheckBox } from "@web/core/checkbox/checkbox";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { BooleanField, booleanField } from "@web/views/fields/boolean/boolean_field";

export class SharedCreditLimitBooleanField extends BooleanField {
    static template = "credit_limit_control.SharedCreditLimitBooleanField";
    static components = { CheckBox };

    setup() {
        super.setup();
        this.dialogService = useService("dialog");
    }

    onChange(value) {
        if (!value) {
            super.onChange(value);
            return;
        }
        this.state.value = value;
        const resetSharedCreditLimit = () => super.onChange(false);
        this.dialogService.add(ConfirmationDialog, {
            body: _t(
                "Enabling shared credit limits will reset the Default Credit Limit to 0 for every company. Do you want to continue?"
            ),
            confirmLabel: _t("Yes"),
            cancelLabel: _t("No"),
            confirm: () => {
                this.state.value = value;
                return this.props.record.update({
                    [this.props.name]: value,
                    company_default_credit_limit: 0,
                });
            },
            cancel: resetSharedCreditLimit,
            dismiss: resetSharedCreditLimit,
        });
    }
}

export const sharedCreditLimitBooleanField = {
    ...booleanField,
    component: SharedCreditLimitBooleanField,
};

registry.category("fields").add(
    "shared_credit_limit_boolean",
    sharedCreditLimitBooleanField
);
