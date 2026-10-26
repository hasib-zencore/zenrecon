# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError


class VisaDetailImportWizard(models.TransientModel):
    _name = "visa.detail.import.wizard"
    _description = "Upload CMS/CBS Reconciliation File"

    source = fields.Selection([("cms", "CMS"), ("cbs", "CBS")], required=True)
    business_date = fields.Date(required=True, default=fields.Date.context_today)
    file = fields.Binary(required=True, attachment=False)
    filename = fields.Char(required=True)

    def action_upload(self):
        self.ensure_one()
        import_record = self.env["visa.detail.import"].create({
            "source": self.source, "business_date": self.business_date,
            "file": self.file, "filename": self.filename,
            "company_id": self.env.company.id,
        })
        import_record.action_process()
        return {
            "type": "ir.actions.act_window", "name": _("%s Import", self.source.upper()),
            "res_model": "visa.detail.import", "res_id": import_record.id,
            "view_mode": "form", "target": "current",
        }


class VisaDetailDailyWizard(models.TransientModel):
    _name = "visa.detail.daily.wizard"
    _description = "Daily VISA One-to-One Reconciliation"

    business_date = fields.Date(required=True, default=fields.Date.context_today)
    profile_id = fields.Many2one(
        "visa.detail.match.profile", required=True,
        domain="[('active', '=', True), ('company_id', '=', company_id)]",
    )
    # Retained for safe upgrades of open transient records. Daily files are now
    # collected centrally from Source Folders & Files.
    cms_file = fields.Binary(string="CMS File", attachment=False)
    cms_filename = fields.Char(string="CMS Filename")
    cbs_file = fields.Binary(string="CBS File", attachment=False)
    cbs_filename = fields.Char(string="CBS Filename")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company, required=True)

    def _create_import(self, source, file_data, filename):
        record = self.env["visa.detail.import"].create({
            "source": source, "business_date": self.business_date,
            "file": file_data, "filename": filename, "company_id": self.company_id.id,
        })
        record.action_process()
        return record

    def action_process(self):
        self.ensure_one()
        if self.profile_id.company_id != self.company_id:
            raise UserError(_("Select a matching profile for the active company."))
        Import = self.env["visa.detail.import"]
        base_domain = [
            ("business_date", "=", self.business_date),
            ("company_id", "=", self.company_id.id),
            ("state", "=", "processed"),
        ]
        cms_import = Import.search(base_domain + [("source", "=", "cms")], order="id desc", limit=1)
        cbs_import = Import.search(base_domain + [("source", "=", "cbs")], order="id desc", limit=1)
        if not cms_import or not cbs_import:
            missing = ", ".join(
                label for record, label in ((cms_import, "CMS"), (cbs_import, "CBS")) if not record
            )
            raise UserError(_(
                "No processed %(sources)s file was found for %(date)s. "
                "Export the missing source from Data Intake first.",
                sources=missing, date=fields.Date.to_string(self.business_date),
            ))
        run = self.env["visa.detail.reconciliation.run"].create({
            "business_date": self.business_date, "profile_id": self.profile_id.id,
            "cms_import_id": cms_import.id, "cbs_import_id": cbs_import.id,
            "company_id": self.company_id.id,
        })
        return run.action_reconcile()
