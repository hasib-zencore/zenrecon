# -*- coding: utf-8 -*-
import base64
import hashlib

from odoo import fields, models, _
from odoo.exceptions import UserError


class BsrIpmImportWizard(models.TransientModel):
    _name = "bsr.ipm.import.wizard"
    _description = "Import Mastercard IPM File"

    upload_file = fields.Binary(string="Mastercard IPM File", required=True, attachment=False)
    upload_filename = fields.Char()

    def _open_import(self, batch):
        return {
            "type": "ir.actions.act_window", "name": _("Mastercard Import"),
            "res_model": "bsr.ipm.import", "res_id": batch.id,
            "view_mode": "form", "target": "current",
        }

    def _uploaded_bytes(self):
        if not self.upload_file:
            raise UserError(_("Select a Mastercard IPM file to upload."))
        try:
            raw = base64.b64decode(self.upload_file, validate=True)
        except Exception as error:
            raise UserError(_("Could not read the uploaded file: %s") % error) from error
        if not raw:
            raise UserError(_("The selected Mastercard file is empty."))
        return raw

    def action_import_and_process(self):
        self.ensure_one()
        raw = self._uploaded_bytes()
        filename = self.upload_filename or "mastercard.ipm"
        digest = hashlib.sha256(raw).hexdigest()
        duplicate = self.env["bsr.ipm.import"].search([
            ("company_id", "=", self.env.company.id), ("file_hash", "=", digest),
        ], limit=1)
        if duplicate:
            return self._open_import(duplicate)
        attachment = self.env["ir.attachment"].create({
            "name": filename,
            "datas": self.upload_file,
            "mimetype": "application/octet-stream",
            "company_id": self.env.company.id,
        })
        batch = self.env["bsr.ipm.import"].create({
            "attachment_id": attachment.id,
            "company_id": self.env.company.id,
            "file_name": filename,
            "file_hash": digest,
            "file_size": len(raw),
        })
        attachment.write({"res_model": batch._name, "res_id": batch.id})
        batch._process_one()
        return self._open_import(batch)
