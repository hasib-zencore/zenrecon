/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class UsersAccessPage extends Component {
    static template = "zenrecon.UsersAccess";

    setup() {
        this.action = useService("action");
        this.orm = useService("orm");
        this.state = useState({
            loading: true,
            users: [],
            summary: { total: 0, roles: 0, inactive: 0 },
            available_roles: [],
            available_schemes: [],
            search: "",
            selectedUser: null,
            showEdit: false,
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
                "get_users_access_data",
                []
            );
            if (data) {
                this.state.users = data.users || [];
                this.state.summary = data.summary || this.state.summary;
                this.state.available_roles = data.available_roles || [];
                this.state.available_schemes = data.available_schemes || [];
            }
        } catch (e) {
            console.error("Users access load failed", e);
        } finally {
            this.state.loading = false;
        }
    }

    get filteredUsers() {
        const q = (this.state.search || "").toLowerCase();
        if (!q) return this.state.users;
        return this.state.users.filter(
            (u) =>
                (u.name || "").toLowerCase().includes(q) ||
                (u.email || "").toLowerCase().includes(q) ||
                (u.department || "").toLowerCase().includes(q)
        );
    }

    onSearch(ev) {
        this.state.search = ev.target.value;
    }

    openUser(user) {
        this.state.selectedUser = {
            ...user,
            roles: [...(user.roles || [])],
            role_ids: [...(user.role_ids || [])],
            scheme_access: [...(user.scheme_access || [])],
        };
        this.state.showEdit = true;
    }

    async saveUser() {
        const u = this.state.selectedUser;
        if (!u || !u.id) return;
        try {
            await this.orm.call(
                "bsr.accounting.configuration",
                "save_user_access",
                [u.id, {
                    name: u.name,
                    email: u.email,
                    active: !!u.active,
                    role_ids: u.role_ids || [],
                }]
            );
            await this.loadData();
            this.closeEdit();
        } catch (e) {
            console.error(e);
        }
    }

    async openUserInOdoo() {
        const u = this.state.selectedUser;
        if (!u || !u.id) return;
        const action = await this.orm.call(
            "bsr.accounting.configuration",
            "action_open_user_form",
            [u.id]
        );
        return this.action.doAction(action);
    }

    addUser() {
        return this.action.doAction({
            type: "ir.actions.act_window",
            name: "New User",
            res_model: "res.users",
            views: [[false, "form"]],
            target: "current",
            context: { form_view_initial_mode: "edit" },
        });
    }

    isRoleSelected(roleId) {
        return (this.state.selectedUser?.role_ids || []).includes(roleId);
    }

    toggleRole(roleId, ev) {
        const roleIds = this.state.selectedUser?.role_ids || [];
        this.state.selectedUser.role_ids = ev.target.checked
            ? [...new Set([...roleIds, roleId])]
            : roleIds.filter((id) => id !== roleId);
    }

    async resetPassword() {
        const u = this.state.selectedUser;
        if (!u || !u.id) return;
        return this.openUserInOdoo();
    }

    closeEdit() {
        this.state.showEdit = false;
        this.state.selectedUser = null;
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
    "zenrecon.users_access",
    UsersAccessPage
);
