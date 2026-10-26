# -*- coding: utf-8 -*-
import base64

from odoo import _, fields, models
from odoo.exceptions import UserError

from ..services.mastercard_clearing_parser import parse_clearing_report


class MastercardClearingImportWizard(models.TransientModel):
    _name = "mastercard.clearing.import.wizard"
    _description = "Upload Mastercard Clearing File"

    file = fields.Binary(string="Clearing File", required=True, attachment=False)
    filename = fields.Char(string="Filename")

    def action_process(self):
        self.ensure_one()
        if not self.file:
            raise UserError(_("Please select a Mastercard clearing file."))

        import_model = self.env["mastercard.clearing.import"]
        name = self.filename or self.env["ir.sequence"].next_by_code(
            "mastercard.clearing.import"
        ) or _("Import")
        clearing_import = import_model.create({
            "name": name,
            "file": self.file,
            "filename": self.filename,
        })

        try:
            raw = base64.b64decode(self.file, validate=True)
        except (TypeError, ValueError) as error:
            clearing_import.write({"state": "error", "log": str(error)})
            raise UserError(_("Could not read the uploaded file: %s") % error) from error
        if not raw:
            clearing_import.write({"state": "error", "log": _("The uploaded file is empty.")})
            raise UserError(_("The uploaded file is empty."))

        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")

        try:
            parsed = parse_clearing_report(text)
        except Exception as error:
            clearing_import.write({"state": "error", "log": str(error)})
            raise UserError(_("Could not read the file: %s") % error) from error

        if not parsed:
            message = _(
                "No notification, acknowledgement, or clearing-day-total rows were found."
            )
            clearing_import.write({"state": "error", "log": message})
            raise UserError(message)

        for row in parsed:
            row["import_id"] = clearing_import.id
        self.env["mastercard.clearing.line"].create(parsed)
        members = sorted({row["member_id"] for row in parsed if row.get("member_id")})
        clearing_import.write({
            "state": "done",
            "log": _("Imported %(count)s rows for member(s) %(members)s.") % {
                "count": len(parsed),
                "members": ", ".join(members) or "-",
            },
        })
        return {
            "type": "ir.actions.act_window",
            "name": _("Mastercard Clearing"),
            "res_model": "mastercard.clearing.import",
            "res_id": clearing_import.id,
            "view_mode": "form",
            "target": "current",
        }
