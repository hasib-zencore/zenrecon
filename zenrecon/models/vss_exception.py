# -*- coding: utf-8 -*-
from odoo import fields, models


class BsrVssException(models.Model):
    _name = "bsr.vss.exception"
    _description = "VSS Parsing Exception"
    _order = "create_date desc, id desc"

    import_id = fields.Many2one("bsr.vss.import", required=True, ondelete="cascade", index=True)
    # Legacy link retained for safe upgrades from the first prototype.
    report_id = fields.Many2one("bsr.vss.report", ondelete="set null", index=True)
    attachment_id = fields.Many2one(related="import_id.attachment_id", store=True, index=True)
    report_code = fields.Char(string="Report ID", index=True)
    source_report_sequence = fields.Integer(string="Source Report #", index=True)
    reporting_for = fields.Char(index=True)
    severity = fields.Selection(
        [("warning", "Warning"), ("error", "Error")],
        required=True,
        default="error",
        index=True,
    )
    message = fields.Text(required=True)
    source_line_no = fields.Integer(index=True)
    raw_line = fields.Text(readonly=True)
