# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError


class NpsbSettlementUploadWizard(models.TransientModel):
    _name = "npsb.settlement.upload.wizard"
    _description = "Upload NPSB Settlement PDF"

    pdf_file = fields.Binary(string="Settlement PDF", required=True)
    filename = fields.Char(string="Filename")

    def action_upload_and_process(self):
        self.ensure_one()
        if not self.pdf_file:
            raise UserError(_("Please select a PDF file to upload."))

        report = self.env["npsb.settlement.report"].create({
            "pdf_file": self.pdf_file,
            "filename": self.filename or "settlement.pdf",
        })
        report.action_process_pdf()

        return {
            "name": _("Settlement Report"),
            "type": "ir.actions.act_window",
            "res_model": "npsb.settlement.report",
            "res_id": report.id,
            "view_mode": "form",
            "target": "current",
        }
