# -*- coding: utf-8 -*-
from odoo import api, fields, models


REPORT_SELECTION = [
    ("VSS-110", "VSS-110"),
    ("VSS-120", "VSS-120"),
    ("VSS-130", "VSS-130"),
    ("VSS-140", "VSS-140"),
    ("VSS-210", "VSS-210"),
]
DIRECTION_SELECTION = [("CR", "CR"), ("DB", "DB")]


class BsrVssReport(models.Model):
    _name = "bsr.vss.report"
    _description = "VSS Logical Report"
    _order = "import_id desc, sequence_no, id"
    _rec_name = "name"

    name = fields.Char(compute="_compute_name", store=True, index=True)
    import_id = fields.Many2one("bsr.vss.import", required=True, ondelete="cascade", index=True)
    attachment_id = fields.Many2one(related="import_id.attachment_id", store=True, index=True)
    company_id = fields.Many2one(related="import_id.company_id", store=True, index=True)
    sequence_no = fields.Integer(required=True, default=1, index=True)

    report_code = fields.Selection(REPORT_SELECTION, required=True, index=True)
    report_name = fields.Char(required=True)
    service_name = fields.Char(index=True)

    reporting_for_ref = fields.Char(string="Reporting For ID", index=True)
    reporting_for_name = fields.Char(string="Reporting For Name", index=True)
    rollup_to_ref = fields.Char(string="Rollup To ID", index=True)
    rollup_to_name = fields.Char(string="Rollup To Name")
    funds_xfer_entity_ref = fields.Char(string="Funds Xfer Entity ID", index=True)
    funds_xfer_entity_name = fields.Char(string="Funds Xfer Entity Name")

    # Flat display values match the business report layout requested by the user.
    reporting_for_display = fields.Char(string="Reporting For", compute="_compute_entity_displays", store=True, index=True)
    rollup_to_display = fields.Char(string="Rollup To", compute="_compute_entity_displays", store=True, index=True)
    funds_xfer_entity_display = fields.Char(string="Funds Xfer Entity", compute="_compute_entity_displays", store=True, index=True)

    settlement_currency = fields.Char(index=True)
    clearing_currencies = fields.Char(help="Distinct clearing currencies found across the report pages.")
    processing_date = fields.Date(index=True)
    report_date = fields.Date(index=True)

    first_page = fields.Integer(default=1)
    last_page = fields.Integer(default=1)
    page_count = fields.Integer(default=1)
    source_start_line = fields.Integer()
    source_end_line = fields.Integer()

    funds_transfer_amount = fields.Float(digits=(20, 2))
    funds_transfer_direction = fields.Selection(DIRECTION_SELECTION, string="Funds Transfer CR/DB")

    data_status = fields.Selection(
        [
            ("data", "Data"),
            ("no_data", "No Data"),
            ("parse_error", "Parse Error"),
            ("incomplete", "Incomplete"),
        ],
        required=True,
        default="data",
        index=True,
    )
    processing_status = fields.Selection(
        [("success", "Success"), ("warning", "Warning"), ("error", "Error")],
        required=True,
        default="success",
        index=True,
    )
    line_count = fields.Integer(compute="_compute_line_count", store=True)
    raw_header = fields.Text(readonly=True)

    line_110_ids = fields.One2many("bsr.vss.110.line", "report_id", string="VSS-110 Lines")
    line_120_ids = fields.One2many("bsr.vss.120.line", "report_id", string="VSS-120 Lines")
    line_130_ids = fields.One2many("bsr.vss.130.line", "report_id", string="VSS-130 Lines")
    line_140_ids = fields.One2many("bsr.vss.140.line", "report_id", string="VSS-140 Lines")
    line_210_ids = fields.One2many("bsr.vss.210.line", "report_id", string="VSS-210 Lines")
    exception_ids = fields.One2many("bsr.vss.exception", "report_id", string="Processing Exceptions")

    @api.depends(
        "report_code",
        "reporting_for_ref",
        "reporting_for_name",
        "processing_date",
    )
    def _compute_name(self):
        for rec in self:
            entity = " ".join(x for x in (rec.reporting_for_ref, rec.reporting_for_name) if x)
            date_text = fields.Date.to_string(rec.processing_date) if rec.processing_date else ""
            rec.name = " - ".join(x for x in (rec.report_code, entity, date_text) if x) or "VSS Report"

    @api.depends(
        "reporting_for_ref",
        "reporting_for_name",
        "rollup_to_ref",
        "rollup_to_name",
        "funds_xfer_entity_ref",
        "funds_xfer_entity_name",
    )
    def _compute_entity_displays(self):
        for rec in self:
            rec.reporting_for_display = " ".join(
                x for x in (rec.reporting_for_ref, rec.reporting_for_name) if x
            )
            rec.rollup_to_display = " ".join(
                x for x in (rec.rollup_to_ref, rec.rollup_to_name) if x
            )
            rec.funds_xfer_entity_display = " ".join(
                x for x in (rec.funds_xfer_entity_ref, rec.funds_xfer_entity_name) if x
            )

    @api.depends(
        "report_code",
        "line_110_ids",
        "line_120_ids",
        "line_130_ids",
        "line_140_ids",
        "line_210_ids",
    )
    def _compute_line_count(self):
        for rec in self:
            mapping = {
                "VSS-110": len(rec.line_110_ids),
                "VSS-120": len(rec.line_120_ids),
                "VSS-130": len(rec.line_130_ids),
                "VSS-140": len(rec.line_140_ids),
                "VSS-210": len(rec.line_210_ids),
            }
            rec.line_count = mapping.get(rec.report_code, 0)

    def action_open_full_report(self):
        """Compatibility helper for legacy prototype records.

        New processing no longer exposes one record per logical source block. If
        an old record is opened after upgrade, take the user to the consolidated
        table for that import/report type instead.
        """
        self.ensure_one()
        action_by_code = {
            "VSS-110": "zenrecon.action_bsr_vss_110_consolidated",
            "VSS-120": "zenrecon.action_bsr_vss_120_consolidated",
            "VSS-130": "zenrecon.action_bsr_vss_130_consolidated",
            "VSS-140": "zenrecon.action_bsr_vss_140_consolidated",
            "VSS-210": "zenrecon.action_bsr_vss_210_consolidated",
        }
        action = self.env["ir.actions.actions"]._for_xml_id(action_by_code[self.report_code])
        action["domain"] = [("import_id", "=", self.import_id.id)]
        action["context"] = {"create": False, "edit": False, "delete": False}
        action["name"] = f"{self.report_code} — {self.import_id.file_name or self.import_id.name}"
        return action
