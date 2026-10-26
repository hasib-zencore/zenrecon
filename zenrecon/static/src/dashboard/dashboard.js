/** @odoo-module **/

import { Component, onWillStart, onMounted, onWillUnmount, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadJS } from "@web/core/assets";

export class BankReconciliationDashboard extends Component {
    static template = "zenrecon.Dashboard";

    setup() {
        this.action = useService("action");
        this.orm = useService("orm");
        this.chartRef = useRef("reconChart");
        this.chartInstance = null;

        this.state = useState({
            loading: true,
            configurations: 0,
            ready_configurations: 0,
            incomplete_rules: 0,
            reports: 0,
            exceptions: 0,
            pending_vouchers: 0,
            transactions_processed: 0,
            transactions_trend: 0,
            schemes_reconciled: 0,
            schemes_total: 0,
            unreconciled_amount: 0,
            files_missing: 0,
            files_missing_detail: "",
            recon_rate: 0,
            recon_pending: 0,
            recon_exceptions: 0,
            schemes: [],
            recent_activity: [],
            business_date: "",
            last_updated: "",
        });

        onWillStart(async () => {
            await this.loadData();
        });

        onMounted(() => {
            // Load Chart.js only if needed – never block the component
            this._initChart();
        });

        onWillUnmount(() => {
            if (this.chartInstance) {
                this.chartInstance.destroy();
                this.chartInstance = null;
            }
        });
    }

    async loadData(businessDate = null) {
        this.state.loading = true;
        try {
            const data = await this.orm.call(
                "bsr.accounting.configuration",
                "get_dashboard_data",
                [],
                { business_date: businessDate || this.state.business_date_raw || false }
            );
            Object.assign(this.state, data || {});
        } catch (e) {
            console.error("Dashboard data load failed", e);
        } finally {
            this.state.loading = false;
            this.renderChart();
        }
    }

    onBusinessDateChange(ev) {
        const value = ev.target.value;          // YYYY-MM-DD
        if (value) {
            this.loadData(value);
        }
    }

    async onRefresh() {
        await this.loadData(this.state.business_date_raw);
    }

    async _initChart() {
        try {
            await loadJS("/web/static/lib/Chart/Chart.js");
            this.renderChart();
        } catch (e) {
            console.warn("Chart.js could not be loaded", e);
        }
    }

    renderChart() {
        if (!this.chartRef.el || typeof Chart === "undefined") {
            return;
        }
        if (this.chartInstance) {
            this.chartInstance.destroy();
        }

        const ctx = this.chartRef.el.getContext("2d");
        this.chartInstance = new Chart(ctx, {
            type: "doughnut",
            data: {
                labels: ["Reconciled", "Pending", "Exceptions"],
                datasets: [{
                    data: [
                        this.state.recon_rate || 0,
                        this.state.recon_pending || 0,
                        this.state.recon_exceptions || 0,
                    ],
                    backgroundColor: ["#55a934", "#e8a317", "#cf3b35"],
                    borderWidth: 0,
                    cutout: "72%",
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => `${ctx.label}: ${ctx.raw}%`,
                        },
                    },
                },
            },
        });
    }

    formatNumber(value) {
        return Number(value || 0).toLocaleString("en-US");
    }

    formatAmount(value) {
        return "৳" + Number(value || 0).toLocaleString("en-IN");
    }

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
    openRuns() {
        return this.action.doAction("zenrecon.action_bsr_accounting_run");
    }

}

registry.category("actions").add(
    "zenrecon.dashboard",
    BankReconciliationDashboard
);
