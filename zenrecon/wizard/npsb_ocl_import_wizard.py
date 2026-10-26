import base64

from odoo import _, fields, models
from odoo.exceptions import UserError

from ..services.npsb_ocl_parser import OICXMLParseError, parse_oic_xml


class NpsbOclImportWizard(models.TransientModel):
    _name = "npsb.ocl.import.wizard"
    _description = "Import NPSB OCL XML Transaction File"

    file = fields.Binary(string="OIC XML File", required=True, attachment=False)
    filename = fields.Char(string="Filename")
    skip_duplicates = fields.Boolean(
        string="Skip Duplicate DRN",
        default=True,
        help="When enabled, records with a DRN already saved for this company are skipped.",
    )

    def action_import(self):
        self.ensure_one()
        if not self.file:
            raise UserError(_("Please select an XML file to upload."))

        try:
            raw = base64.b64decode(self.file)
        except Exception as error:
            raise UserError(_("Could not read the uploaded file: %s") % error) from error

        try:
            _header, vals_list = parse_oic_xml(raw, source_file_name=self.filename or "")
        except OICXMLParseError as error:
            raise UserError(str(error)) from error

        imported_at = fields.Datetime.now()
        company_id = self.env.company.id
        for vals in vals_list:
            vals["imported_at"] = imported_at
            vals["company_id"] = company_id

        skipped = 0
        if self.skip_duplicates:
            drns = [vals["drn"] for vals in vals_list if vals.get("drn")]
            existing_drns = set()
            if drns:
                existing = self.env["npsb.ocl.transaction"].search([
                    ("company_id", "=", company_id),
                    ("drn", "in", drns),
                ])
                existing_drns = set(existing.mapped("drn"))

            unique_vals = []
            seen_in_file = set()
            for vals in vals_list:
                drn = vals.get("drn")
                if drn and (drn in existing_drns or drn in seen_in_file):
                    skipped += 1
                    continue
                if drn:
                    seen_in_file.add(drn)
                unique_vals.append(vals)
            vals_list = unique_vals

        if not vals_list:
            raise UserError(
                _("No new transaction was imported. %s duplicate record(s) were skipped.") % skipped
            )

        batch = self.env["npsb.ocl.import"].create({
            'name': self.filename or 'OIC XML Import',
            'file': self.file,
            'file_size': len(raw),
            'company_id': self.env.company.id,
        })
        for vals in vals_list:
            vals['batch_id'] = batch.id

        self.env["npsb.ocl.transaction"].create(vals_list)

        return {
            'type': 'ir.actions.act_window', 'name': 'Imported OIC File',
            'res_model': 'npsb.ocl.import', 'res_id': batch.id,
            'view_mode': 'form', 'target': 'current',
        }
