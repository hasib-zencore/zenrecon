# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


class MastercardClearingImport(models.Model):
    _name = "mastercard.clearing.import"
    _description = "Mastercard Clearing Import"
    _order = "id desc"

    name = fields.Char(required=True, copy=False, default=lambda self: _("New"))
    file = fields.Binary(string="Clearing File", attachment=True)
    filename = fields.Char(string="Filename")
    state = fields.Selection(
        [("draft", "Draft"), ("done", "Processed"), ("error", "Error")],
        default="draft",
    )
    line_ids = fields.One2many("mastercard.clearing.line", "import_id", string="Lines")
    line_count = fields.Integer(compute="_compute_line_count")
    log = fields.Text(readonly=True)

    @api.depends("line_ids")
    def _compute_line_count(self):
        for record in self:
            record.line_count = len(record.line_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            if not values.get("name") or values.get("name") == _("New"):
                values["name"] = self.env["ir.sequence"].next_by_code(
                    "mastercard.clearing.import"
                ) or _("New")
        return super().create(vals_list)

    def action_open_upload_wizard(self):
        return {
            "type": "ir.actions.act_window",
            "name": _("Upload Mastercard Clearing File"),
            "res_model": "mastercard.clearing.import.wizard",
            "view_mode": "form",
            "target": "new",
        }

    def action_view_lines(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Mastercard Clearing Lines"),
            "res_model": "mastercard.clearing.line",
            "view_mode": "list,form",
            "domain": [("import_id", "=", self.id)],
            "context": {"default_import_id": self.id},
        }


class MastercardClearingLine(models.Model):
    _name = "mastercard.clearing.line"
    _description = "Mastercard Clearing Line"
    _order = "import_id desc, sequence, id"

    import_id = fields.Many2one(
        "mastercard.clearing.import",
        string="Import",
        required=True,
        ondelete="cascade",
        index=True,
    )
    sequence = fields.Integer(default=10)
    report_id = fields.Char(string="Report ID", index=True)
    settled_coll_only = fields.Char(string="SETTLED / Coll Only")
    mastercard_cycle = fields.Char(string="Mastercard Cycle")
    ack_notification = fields.Char(string="Acknowledgement / Notification")
    business_service_level = fields.Char(string="Business Service Level")
    business_service_id = fields.Char(string="Business Service ID")
    file_id = fields.Char(string="File ID")
    member_id = fields.Char(string="Member ID", index=True)
    run_date = fields.Date(string="Run Date")
    clearing_date = fields.Date(string="Clearing Date")
    trans_func = fields.Char(string="Transaction Function")
    proc_code = fields.Char(string="Processing Code")
    ird = fields.Char(string="IRD")
    counts = fields.Integer(string="Count")
    recon_amount = fields.Float(string="Reconciliation Amount", digits=(16, 2))
    recon_dr_cr = fields.Selection([("DR", "DR"), ("CR", "CR")], string="Reconciliation DR/CR")
    recon_curr_code = fields.Char(string="Reconciliation Currency")
    trans_fee = fields.Float(string="Transaction Fee", digits=(16, 2))
    fee_dr_cr = fields.Selection([("DR", "DR"), ("CR", "CR")], string="Fee DR/CR")
    fee_curr_code = fields.Char(string="Fee Currency")
    net_amount = fields.Float(string="Net Amount", digits=(16, 2))
    net_dr_cr = fields.Selection([("DR", "DR"), ("CR", "CR")], string="Net DR/CR")
    is_day_total = fields.Boolean(string="Day Total")
    raw_line = fields.Char(string="Source Line")
