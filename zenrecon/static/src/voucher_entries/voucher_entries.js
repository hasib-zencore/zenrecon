/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class VoucherEntriesPage extends Component {
    static template = "zenrecon.VoucherEntries";

    setup() {
        this.action = useService("action");
        this.orm = useService("orm");

        this.state = useState({
            loading: true,
            business_date: "",
            business_date_raw: "",
            schemes: [],
            detail: null,
            selectedScheme: null,
        });

        onWillStart(async () => {
            await this.loadData();
        });
    }

    async loadData(businessDate = null) {
        this.state.loading = true;
        try {
            const data = await this.orm.call(
                "bsr.accounting.configuration",
                "get_voucher_entries_data",
                [],
                { business_date: businessDate || this.state.business_date_raw || false }
            );
            Object.assign(this.state, data || {});
            // Auto-select first Pending Approval or first row
            const prefer = (data.schemes || []).find((s) => s.voucher_status === "Pending Approval")
                || (data.schemes || [])[0];
            this.state.selectedScheme = prefer ? prefer.scheme : null;
        } catch (e) {
            console.error("Voucher entries load failed", e);
        } finally {
            this.state.loading = false;
        }
    }

    onBusinessDateChange(ev) {
        const value = ev.target.value;
        if (value) {
            this.loadData(value);
        }
    }

    async onRefresh() {
        await this.loadData(this.state.business_date_raw);
    }

    selectScheme(scheme) {
        this.state.selectedScheme = scheme.scheme;
        // For now detail is already loaded; later we can fetch per-scheme
    }

    formatAmount(value) {
        return "৳" + Number(value || 0).toLocaleString("en-IN");
    }

    // Navigation (same as dashboard)
    openDashboard() {
        return this.action.doAction("zenrecon.action_bsr_suite_dashboard");
    }
    openProcess() {
        return this.action.doAction("zenrecon.action_bsr_vss_import_document_wizard");
    }
    openReconciliation() {
        return this.action.doAction("zenrecon.action_bsr_vss_import");
    }
    openTransactionReconciliation() {
        return this.action.doAction("zenrecon.action_visa_detail_runs");
    }
    openVoucherEntries() {
        return this.action.doAction("zenrecon.action_bsr_voucher_entries");
    }
    openNotifications() {
        return this.action.doAction("zenrecon.action_bsr_notifications");
    }
    openUsersAccess() {
        return this.action.doAction("zenrecon.action_bsr_users_access");
    }
    openRolesPermissions() {
        return this.action.doAction("zenrecon.action_bsr_roles_permissions");
    }
    openMappings() {
        return this.action.doAction("zenrecon.action_bsr_accounting_configuration");
    }
    openReports() {
        return this.action.doAction("zenrecon.action_bsr_accounting_report");
    }

    openVoucher(reportId) {
        if (!reportId) return;
        return this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "bsr.accounting.report",
            res_id: reportId,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

registry.category("actions").add(
    "zenrecon.voucher_entries",
    VoucherEntriesPage
);
