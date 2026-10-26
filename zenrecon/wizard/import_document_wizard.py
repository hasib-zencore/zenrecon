# -*- coding: utf-8 -*-
import base64
import hashlib

from odoo import fields, models, _
from odoo.exceptions import UserError


class BsrVssImportDocumentWizard(models.TransientModel):
    _name = "bsr.vss.import.document.wizard"
    _description = "Upload VSS File"

    file = fields.Binary(string="VSS File", required=True, attachment=False)
    filename = fields.Char(string="Filename")

    @staticmethod
    def _open_import(batch):
        return {
            "type": "ir.actions.act_window",
            "name": _("VSS Import"),
            "res_model": "bsr.vss.import",
            "res_id": batch.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_import_and_process(self):
        self.ensure_one()
        if not self.file:
            raise UserError(_("Select a Visa settlement .txt file to upload."))
        file_name = self.filename or ""
        if not file_name.lower().endswith(".txt"):
            raise UserError(_("Please upload a .txt Visa settlement file."))

        try:
            raw_bytes = base64.b64decode(self.file, validate=True)
        except Exception as error:
            raise UserError(_("Could not read the uploaded file: %s") % error) from error
        if not raw_bytes:
            raise UserError(_("The selected source file is empty."))

        file_hash = hashlib.sha256(raw_bytes).hexdigest()
        duplicate = self.env["bsr.vss.import"].search(
            [("file_hash", "=", file_hash), ("state", "in", ("completed", "partial"))],
            limit=1,
        )
        if duplicate:
            # One physical source file corresponds to one import/report set. Open
            # the existing set instead of creating another set that could confuse
            # reconciliation users.
            return self._open_import(duplicate)

        attachment = self.env["ir.attachment"].create({
            "name": file_name,
            "datas": self.file,
            "mimetype": "text/plain",
            "company_id": self.env.company.id,
        })
        batch = self.env["bsr.vss.import"].create({
            "attachment_id": attachment.id,
            "file_name": file_name,
            "file_hash": file_hash,
            "file_size": len(raw_bytes),
        })
        attachment.write({"res_model": batch._name, "res_id": batch.id})
        batch._process_one()
        return self._open_import(batch)
