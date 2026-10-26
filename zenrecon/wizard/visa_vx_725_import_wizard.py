import base64
import logging
import re

from odoo import fields, models
from odoo.exceptions import UserError

from ..services.vx725_parser import REPORT_CODE, parse_system_date, parse_vx725

_logger = logging.getLogger(__name__)
_REPORT_RE = re.compile(r"\bREPORT\s+(VX-\d+)\b", re.IGNORECASE)


class VisaVX725ImportWizard(models.TransientModel):
    _name = "visa.vx.725.import.wizard"
    _description = "Import Visa VX-725 Report File"

    file = fields.Binary(string="VX-725 Text File", required=True, attachment=False)
    filename = fields.Char(string="Filename")

    def action_import(self):
        self.ensure_one()
        if not self.file:
            raise UserError("Please select a VX-725 text file to upload.")

        try:
            raw = base64.b64decode(self.file)
            text = raw.decode("utf-8", errors="replace")
        except Exception as error:
            raise UserError("Could not read the uploaded file: %s" % error)

        report_match = _REPORT_RE.search(text)
        detected = report_match.group(1).upper() if report_match else "Unknown"
        if detected != REPORT_CODE:
            raise UserError("Invalid report file. Expected VX-725 but detected %s." % detected)

        vals_list, unmatched = parse_vx725(text, source_file_name=self.filename or "")
        if not vals_list:
            raise UserError(
                "No Sales Draft Reversal records were found. Check that this is a VX-725 text export "
                "and that its layout matches the expected Visa report format."
            )

        imported_at = fields.Datetime.now()
        for vals in vals_list:
            if vals.get("system_date"):
                vals["system_date"] = parse_system_date(vals["system_date"])
            vals["imported_at"] = imported_at
            vals.setdefault("company_id", self.env.company.id)

        # visa.vx.725 is a normal models.Model, so imported data is persistent.
        batch = self.env['visa.import.batch'].create({
            'name': self.filename or 'VX-725 Import',
            'report_type': '725',
            'file': self.file,
            'file_size': len(raw),
            'company_id': self.env.company.id,
        })
        for vals in vals_list:
            vals['batch_id'] = batch.id

        created = self.env["visa.vx.725"].create(vals_list)

        if unmatched:
            _logger.warning(
                "VX-725 import (%s): %d unmatched line(s):\n%s",
                self.filename,
                len(unmatched),
                "\n".join(unmatched),
            )

        return {
            'type': 'ir.actions.act_window', 'name': 'Imported File',
            'res_model': 'visa.import.batch', 'res_id': batch.id,
            'view_mode': 'form', 'target': 'current',
        }
