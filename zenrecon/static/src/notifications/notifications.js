/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class NotificationsPage extends Component {
    static template = "zenrecon.Notifications";

    setup() {
        this.action = useService("action");
        this.orm = useService("orm");

        this.state = useState({
            loading: true,
            filter: "all",
            notifications: [],
            alert_rules: [],
            counts: { all: 0, critical: 0, warning: 0, info: 0, unread: 0 },
        });

        onWillStart(async () => {
            await this.loadData();
        });
    }

    async loadData() {
        this.state.loading = true;
        try {
            const data = await this.orm.call(
                "bsr.accounting.configuration",
                "get_notifications_data",
                []
            );
            Object.assign(this.state, data || {});
        } catch (e) {
            console.error("Notifications load failed", e);
        } finally {
            this.state.loading = false;
        }
    }

    get filteredNotifications() {
        const list = this.state.notifications || [];
        if (this.state.filter === "all") return list;
        if (this.state.filter === "unread") return list.filter((n) => n.unread);
        return list.filter((n) => n.type === this.state.filter);
    }

    setFilter(filter) {
        this.state.filter = filter;
    }

    // Navigation
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
}

registry.category("actions").add(
    "zenrecon.notifications",
    NotificationsPage
);
