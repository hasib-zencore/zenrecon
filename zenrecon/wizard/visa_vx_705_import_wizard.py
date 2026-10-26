import base64
import logging
import re

from odoo import fields, models
from odoo.exceptions import UserError

from ..services.vx705_parser import REPORT_CODE, parse_system_date, parse_vx705

_logger = logging.getLogger(__name__)
_REPORT_RE = re.compile(r"\bREPORT\s+(VX-\d+)\b", re.IGNORECASE)


class VisaVX705ImportWizard(models.TransientModel):
    _name = "visa.vx.705.import.wizard"
    _description = "Import Visa VX-705 Report File"

    file = fields.Binary(string="VX-705 Text File", required=True, attachment=False)
    filename = fields.Char(string="Filename")

    def action_import(self):
        self.ensure_one()
        if not self.file:
            raise UserError("Please select a VX-705 text file to upload.")

        try:
            raw = base64.b64decode(self.file)
            text = raw.decode("utf-8", errors="replace")
        except Exception as error:
            raise UserError("Could not read the uploaded file: %s" % error)

        report_match = _REPORT_RE.search(text)
        detected = report_match.group(1).upper() if report_match else "Unknown"
        if detected != REPORT_CODE:
            raise UserError("Invalid report file. Expected VX-705 but detected %s." % detected)

        vals_list, unmatched = parse_vx705(text, source_file_name=self.filename or "")
        if not vals_list:
            raise UserError(
                "No Sales Draft records were found. Check that this is a VX-705 text export "
                "and that its layout matches the expected Visa report format."
            )

        imported_at = fields.Datetime.now()
        for vals in vals_list:
            if vals.get("system_date"):
                vals["system_date"] = parse_system_date(vals["system_date"])
            vals["imported_at"] = imported_at
            vals.setdefault("company_id", self.env.company.id)

        # visa.vx.705 is a normal models.Model, not a TransientModel.
        # These records therefore remain permanently in PostgreSQL until a user deletes them.
        batch = self.env['visa.import.batch'].create({
            'name': self.filename or 'VX-705 Import',
            'report_type': '705',
            'file': self.file,
            'file_size': len(raw),
            'company_id': self.env.company.id,
        })
        for vals in vals_list:
            vals['batch_id'] = batch.id

        created = self.env["visa.vx.705"].create(vals_list)

        if unmatched:
            _logger.warning(
                "VX-705 import (%s): %d unmatched line(s):\n%s",
                self.filename,
                len(unmatched),
                "\n".join(unmatched),
            )

        return {
            'type': 'ir.actions.act_window', 'name': 'Imported File',
            'res_model': 'visa.import.batch', 'res_id': batch.id,
            'view_mode': 'form', 'target': 'current',
        }
