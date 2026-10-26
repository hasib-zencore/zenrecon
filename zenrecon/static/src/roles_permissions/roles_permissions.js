/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class RolesPermissionsPage extends Component {
    static template = "zenrecon.RolesPermissions";

    setup() {
        this.action = useService("action");
        this.orm = useService("orm");
        this.state = useState({
            loading: true,
            roles: [],
            modules: [],
            actions: [],
            selectedRoleId: null,
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
                "get_roles_permissions_data",
                []
            );
            if (data) {
                this.state.roles = data.roles || [];
                this.state.modules = data.modules || [];
                this.state.actions = data.actions || [];
                if (this.state.roles.length && !this.state.selectedRoleId) {
                    this.state.selectedRoleId = this.state.roles[0].id;
                }
            }
        } catch (e) {
            console.error("Roles permissions load failed", e);
        } finally {
            this.state.loading = false;
        }
    }

    get selectedRole() {
        return (this.state.roles || []).find((r) => r.id === this.state.selectedRoleId) || null;
    }

    selectRole(roleId) {
        this.state.selectedRoleId = roleId;
    }

    hasPerm(module, action) {
        const role = this.selectedRole;
        if (!role || !role.permissions || !role.permissions[module]) return false;
        return !!role.permissions[module][action];
    }

    async openRoleInOdoo() {
        const role = this.selectedRole;
        if (!role) return;
        const action = await this.orm.call(
            "bsr.accounting.configuration",
            "action_open_group_form",
            [role.id]
        );
        return this.action.doAction(action);
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
    "zenrecon.roles_permissions",
    RolesPermissionsPage
);
