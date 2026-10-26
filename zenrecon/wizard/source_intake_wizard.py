# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ZenreconSourceExportWizard(models.TransientModel):
    _name = "zenrecon.source.export.wizard"
    _description = "Export and Process Source Files"

    workspace_id = fields.Many2one(
        "zenrecon.source.workspace", required=True,
        default=lambda self: self.env["zenrecon.source.workspace"]._workspace_for_company(),
    )
    scope = fields.Selection(
        [("all", "All configured folders"), ("selected", "Selected folders")],
        required=True, default="all",
    )
    folder_ids = fields.Many2many(
        "zenrecon.source.folder", string="Source folders",
        domain="[('workspace_id', '=', workspace_id), ('active', '=', True)]",
    )
    business_date = fields.Date(required=True, default=fields.Date.context_today)
    @api.onchange("workspace_id")
    def _onchange_workspace_id(self):
        if self.folder_ids.filtered(lambda folder: folder.workspace_id != self.workspace_id):
            self.folder_ids = False

    def action_export_and_process(self):
        self.ensure_one()
        folders = (
            self.workspace_id.folder_ids.filtered("active")
            if self.scope == "all"
            else self.folder_ids.filtered("active")
        )
        if not folders:
            raise UserError(_("Select at least one source folder."))

        discovered = self.env["zenrecon.source.file"]
        processed = errors = skipped = 0
        for folder in folders:
            files = folder._scan(self.business_date)
            discovered |= files
            folder_processed = folder_errors = folder_skipped = 0
            for source_file in files:
                if source_file.state == "processed":
                    skipped += 1
                    folder_skipped += 1
                    continue
                if source_file._process(self.business_date):
                    processed += 1
                    folder_processed += 1
                else:
                    errors += 1
                    folder_errors += 1
            if files:
                folder.sudo().write({
                    "last_status": "error" if files.filtered(lambda item: item.state == "error") else "processed",
                    "last_message": _(
                        "%(processed)s processed, %(errors)s error(s), %(skipped)s already completed.",
                        processed=folder_processed,
                        errors=folder_errors,
                        skipped=folder_skipped,
                    ),
                })

        message = _(
            "%(folders)s folder(s) checked: %(processed)s processed, %(errors)s error(s), "
            "%(skipped)s already completed.",
            folders=len(folders), processed=processed, errors=errors, skipped=skipped,
        )
        domain = [("workspace_id", "=", self.workspace_id.id), ("scan_date", "=", self.business_date)]
        if discovered:
            domain = [("id", "in", discovered.ids)]
        return {
            "type": "ir.actions.act_window", "name": _("Source File Results"),
            "res_model": "zenrecon.source.file", "view_mode": "list,form",
            "domain": domain, "target": "current",
            "context": {"zenrecon_result_message": message},
        }
