# -*- coding: utf-8 -*-
import base64
import hashlib
import os
from datetime import datetime
from pathlib import Path

from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


SOURCE_PARSERS = [
    ("visa_vss", "VISA VSS Settlement"),
    ("visa_vx705", "VISA VX-705"),
    ("visa_vx706", "VISA VX-706"),
    ("visa_vx707", "VISA VX-707"),
    ("visa_vx725", "VISA VX-725"),
    ("visa_vx727", "VISA VX-727"),
    ("mastercard_ipm", "Mastercard IPM"),
    ("mastercard_clearing", "Mastercard Clearing"),
    ("npsb_ocl", "NPSB OCL XML"),
    ("npsb_settlement", "NPSB Settlement PDF"),
    ("cms", "CMS Reconciliation"),
    ("cbs", "CBS Reconciliation"),
]

DEFAULT_SOURCE_FOLDERS = [
    (10, "VISA VSS", "visa_vss", "VISA", "Settlement", "IN/Issuing/VISA/VSS", "*.txt"),
    (20, "VISA VX-705", "visa_vx705", "VISA", "VX-705", "IN/Issuing/VISA/VX705", "*705*.txt"),
    (30, "VISA VX-706", "visa_vx706", "VISA", "VX-706", "IN/Issuing/VISA/VX706", "*706*.txt"),
    (40, "VISA VX-707", "visa_vx707", "VISA", "VX-707", "IN/Issuing/VISA/VX707", "*707*.txt"),
    (50, "VISA VX-725", "visa_vx725", "VISA", "VX-725", "IN/Issuing/VISA/VX725", "*725*.txt"),
    (60, "VISA VX-727", "visa_vx727", "VISA", "VX-727", "IN/Issuing/VISA/VX727", "*727*.txt"),
    (70, "Mastercard IPM", "mastercard_ipm", "Mastercard", "IPM", "IN/Issuing/Mastercard/IPM", "*"),
    (80, "Mastercard Clearing", "mastercard_clearing", "Mastercard", "Clearing", "IN/Issuing/Mastercard/Clearing", "*.txt"),
    (90, "NPSB OCL", "npsb_ocl", "NPSB", "OCL", "IN/Issuing/NPSB/OCL", "*.xml"),
    (100, "NPSB Settlement", "npsb_settlement", "NPSB", "Settlement", "IN/Issuing/NPSB/Settlement", "*.pdf"),
    (110, "CMS", "cms", "Reconciliation", "CMS", "IN/Reconciliation/CMS", "*"),
    (120, "CBS", "cbs", "Reconciliation", "CBS", "IN/Reconciliation/CBS", "*"),
]


class ZenreconSourceWorkspace(models.Model):
    _name = "zenrecon.source.workspace"
    _description = "ZenRecon Source Workspace"
    _order = "company_id, id"

    name = fields.Char(required=True, default="BankRecon")
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )
    root_path = fields.Char(
        string="Legacy Default Source Root",
        default=lambda self: os.path.expanduser("~/BankRecon"),
        help="Used only to initialize mappings. Each source folder keeps its own physical path.",
    )
    active = fields.Boolean(default=True)
    folder_ids = fields.One2many("zenrecon.source.folder", "workspace_id", string="Source Folders")
    file_ids = fields.One2many("zenrecon.source.file", "workspace_id", string="Discovered Files")
    configured_folder_count = fields.Integer(compute="_compute_dashboard")
    files_today_count = fields.Integer(compute="_compute_dashboard")
    processed_today_count = fields.Integer(compute="_compute_dashboard")
    issue_count = fields.Integer(compute="_compute_dashboard")
    folder_tree_html = fields.Html(compute="_compute_folder_tree", sanitize=False)

    _company_unique = models.Constraint(
        "UNIQUE(company_id)", "Only one source workspace is allowed per company."
    )

    @api.depends("folder_ids.active", "folder_ids.last_status", "file_ids.state", "file_ids.scan_date")
    def _compute_dashboard(self):
        today = fields.Date.context_today(self)
        File = self.env["zenrecon.source.file"]
        for workspace in self:
            workspace.configured_folder_count = len(workspace.folder_ids.filtered("active"))
            today_domain = [("workspace_id", "=", workspace.id), ("scan_date", "=", today)]
            workspace.files_today_count = File.search_count(today_domain)
            workspace.processed_today_count = File.search_count(today_domain + [("state", "=", "processed")])
            workspace.issue_count = len(
                workspace.folder_ids.filtered(lambda folder: folder.active and folder.last_status in ("missing", "error"))
            )

    @api.depends(
        "name", "folder_ids.domain_name", "folder_ids.stream_name",
        "folder_ids.relative_path", "folder_ids.source_path",
        "folder_ids.last_status", "folder_ids.active",
    )
    def _compute_folder_tree(self):
        status_icon = {
            "never": ("text-muted", "○"), "ready": ("text-info", "●"),
            "processed": ("text-success", "●"), "missing": ("text-danger", "●"),
            "error": ("text-danger", "●"),
        }
        for workspace in self:
            tree = {"children": {}}
            for folder in workspace.folder_ids.sorted(lambda item: (item.sequence, item.id)):
                if not folder.active:
                    continue
                node = tree
                for part in Path(folder.relative_path.replace("\\", "/")).parts:
                    node = node["children"].setdefault(part, {"children": {}, "folder": False})
                node["folder"] = folder

            def render_children(node, level=0):
                rows = []
                for label, child in node["children"].items():
                    folder = child.get("folder")
                    css = icon = status = ""
                    title = ""
                    if folder:
                        css, icon = status_icon.get(folder.last_status, status_icon["never"])
                        status = dict(folder._fields["last_status"].selection).get(folder.last_status, "")
                        title = folder.source_path or _("Physical path not configured")
                    folder_icon = "fa-folder-o" if not child["children"] else "fa-folder"
                    rows.append(Markup(
                        '<li><div class="o_zenrecon_tree_node" style="--zr-level:%s" title="%s">'
                        '<i class="fa %s me-2"/>%s%s</div>%s</li>'
                    ) % (
                        level, escape(title), escape(folder_icon), escape(label),
                        Markup(' <span class="%s ms-2">%s %s</span>')
                        % (escape(css), escape(icon), escape(status)) if folder else Markup(""),
                        render_children(child, level + 1),
                    ))
                return Markup('<ul class="o_zenrecon_tree_level">%s</ul>') % Markup("".join(map(str, rows)))

            workspace.folder_tree_html = Markup(
                '<div class="o_zenrecon_folder_tree">'
                '<div class="o_zenrecon_tree_root"><i class="fa fa-folder-open me-2"/>%s</div>%s</div>'
            ) % (escape("root/%s" % (workspace.name or "BankRecon")), render_children(tree))

    def _ensure_default_folders(self):
        Folder = self.env["zenrecon.source.folder"].sudo()
        for workspace in self:
            existing = set(workspace.folder_ids.mapped("parser_type"))
            initial_root = Path(os.path.expandvars(os.path.expanduser(
                workspace.root_path or "~/BankRecon"
            )))
            for folder in workspace.folder_ids.filtered(lambda item: not item.source_path):
                folder.source_path = str(initial_root / folder.relative_path.replace("\\", "/"))
            values = []
            for sequence, name, parser, domain_name, stream, path, pattern in DEFAULT_SOURCE_FOLDERS:
                if parser not in existing:
                    values.append({
                        "workspace_id": workspace.id,
                        "sequence": sequence,
                        "name": name,
                        "code": parser.upper(),
                        "parser_type": parser,
                        "domain_name": domain_name,
                        "stream_name": stream,
                        "relative_path": path,
                        "source_path": str(initial_root / path),
                        "file_pattern": pattern,
                    })
            if values:
                Folder.create(values)
        return self

    @api.model
    def _workspace_for_company(self, company=None):
        company = company or self.env.company
        workspace = self.sudo().search([("company_id", "=", company.id)], limit=1)
        if not workspace:
            workspace = self.sudo().create({"name": "BankRecon", "company_id": company.id})
        workspace._ensure_default_folders()
        return workspace

    @api.model
    def action_open_current(self):
        workspace = self._workspace_for_company()
        return {
            "type": "ir.actions.act_window",
            "name": _("Source Folders & Files"),
            "res_model": self._name,
            "res_id": workspace.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_open_export_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Export Source Files"),
            "res_model": "zenrecon.source.export.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_workspace_id": self.id, "default_scope": "all"},
        }

    def action_scan_now(self):
        self.ensure_one()
        scan_date = fields.Date.context_today(self)
        for folder in self.folder_ids.filtered("active"):
            folder._scan(scan_date)
        return {
            "type": "ir.actions.client", "tag": "display_notification",
            "params": {
                "title": _("Folder scan completed"),
                "message": _("Statuses were refreshed from the configured source directories."),
                "type": "success", "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "soft_reload"},
            },
        }

    def action_open_folder_configuration(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": _("Source Folder Configuration"),
            "res_model": "zenrecon.source.folder", "view_mode": "list,form",
            "domain": [("workspace_id", "=", self.id)],
            "context": {"default_workspace_id": self.id}, "target": "current",
        }

    def action_open_files(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": _("Source File Status"),
            "res_model": "zenrecon.source.file", "view_mode": "list,form",
            "domain": [("workspace_id", "=", self.id)], "target": "current",
        }


class ZenreconSourceFolder(models.Model):
    _name = "zenrecon.source.folder"
    _description = "ZenRecon Source Folder"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    workspace_id = fields.Many2one("zenrecon.source.workspace", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="workspace_id.company_id", store=True, index=True)
    name = fields.Char(required=True)
    code = fields.Char(required=True)
    domain_name = fields.Char(string="Domain", required=True)
    stream_name = fields.Char(string="Stream", required=True)
    parser_type = fields.Selection(SOURCE_PARSERS, string="File Format / Parser", required=True)
    relative_path = fields.Char(
        string="Logical Folder",
        required=True,
        help="Fixed folder shown in the ZenRecon hierarchy; it is independent from the physical path.",
    )
    source_path = fields.Char(
        string="PC / Shared Folder Path",
        help="Exact absolute directory visible to the Odoo server for this source stream.",
    )
    file_pattern = fields.Char(required=True, default="*")
    expected_by = fields.Char(default="06:30")
    active = fields.Boolean(default=True)
    last_status = fields.Selection(
        [("never", "Not Scanned"), ("ready", "Ready"), ("processed", "Processed"),
         ("missing", "Missing"), ("error", "Error")],
        default="never", required=True, readonly=True, index=True,
    )
    last_scan_at = fields.Datetime(readonly=True)
    last_file_id = fields.Many2one("zenrecon.source.file", readonly=True, ondelete="set null")
    last_message = fields.Char(readonly=True)
    file_ids = fields.One2many("zenrecon.source.file", "folder_id")

    _code_unique = models.Constraint(
        "UNIQUE(workspace_id, code)", "The source code must be unique within a workspace."
    )

    @api.constrains("relative_path")
    def _check_relative_path(self):
        for folder in self:
            raw_path = (folder.relative_path or "").strip().replace("\\", "/")
            path = Path(raw_path)
            if path.is_absolute() or ".." in path.parts:
                raise ValidationError(_("Logical Folder must be a safe relative hierarchy path."))

    @api.constrains("source_path")
    def _check_source_path(self):
        for folder in self.filtered("source_path"):
            expanded = os.path.expandvars(os.path.expanduser(folder.source_path.strip()))
            if not Path(expanded).is_absolute():
                raise ValidationError(_("PC / Shared Folder Path must be an absolute path."))

    def _resolved_path(self):
        self.ensure_one()
        path_text = os.path.expandvars(os.path.expanduser((self.source_path or "").strip()))
        if not path_text:
            raise UserError(_("Configure the PC / Shared Folder Path for %s.") % self.name)
        return Path(path_text).resolve()

    def _expanded_pattern(self, business_date):
        value = fields.Date.to_date(business_date)
        replacements = {
            "{YYYYMMDD}": value.strftime("%Y%m%d"),
            "{DDMMYYYY}": value.strftime("%d%m%Y"),
            "{DDMMYY}": value.strftime("%d%m%y"),
            "{YYYY-MM-DD}": value.strftime("%Y-%m-%d"),
            "{YYYYMM}": value.strftime("%Y%m"),
        }
        pattern = self.file_pattern or "*"
        for token, replacement in replacements.items():
            pattern = pattern.replace(token, replacement)
        return pattern

    def _scan(self, business_date):
        self.ensure_one()
        now = fields.Datetime.now()
        try:
            folder_path = self._resolved_path()
            if not folder_path.is_dir():
                self.sudo().write({
                    "last_status": "missing", "last_scan_at": now,
                    "last_message": _("Folder not found: %s") % folder_path,
                })
                return self.env["zenrecon.source.file"]
            paths = sorted(
                (path for path in folder_path.glob(self._expanded_pattern(business_date)) if path.is_file()),
                key=lambda path: (path.stat().st_mtime, path.name),
            )
        except (OSError, UserError) as error:
            self.sudo().write({"last_status": "error", "last_scan_at": now, "last_message": str(error)})
            return self.env["zenrecon.source.file"]

        if not paths:
            self.sudo().write({
                "last_status": "missing", "last_scan_at": now,
                "last_message": _("No file matches %s") % self._expanded_pattern(business_date),
            })
            return self.env["zenrecon.source.file"]

        File = self.env["zenrecon.source.file"].sudo()
        discovered = File.browse()
        for path in paths:
            try:
                raw = path.read_bytes()
                digest = hashlib.sha256(raw).hexdigest()
                record = File.search([
                    ("folder_id", "=", self.id), ("digest", "=", digest),
                ], limit=1)
                values = {
                    "file_name": path.name,
                    "relative_file_path": str(Path(self.relative_path) / path.name),
                    "absolute_path": str(path),
                    "file_size": len(raw),
                    "modified_at": datetime.fromtimestamp(path.stat().st_mtime),
                    "scan_date": business_date,
                    "last_seen_at": now,
                }
                if record:
                    record.write(values)
                else:
                    values.update({"folder_id": self.id, "digest": digest, "state": "ready"})
                    record = File.create(values)
                discovered |= record
            except OSError as error:
                self.sudo().write({"last_status": "error", "last_scan_at": now, "last_message": str(error)})

        if discovered:
            latest = discovered.sorted(lambda item: (item.modified_at or fields.Datetime.now(), item.id))[-1]
            status = "processed" if all(item.state == "processed" for item in discovered) else "ready"
            self.sudo().write({
                "last_status": status, "last_scan_at": now, "last_file_id": latest.id,
                "last_message": _("%(count)s matching file(s) found.", count=len(discovered)),
            })
        return discovered.with_env(self.env)

    def action_open_export_wizard(self):
        workspace = self.mapped("workspace_id") if self else self.env["zenrecon.source.workspace"]._workspace_for_company()
        if len(workspace) != 1:
            raise UserError(_("Select folders from one workspace."))
        selected = self if self else self.env["zenrecon.source.folder"]
        return {
            "type": "ir.actions.act_window", "name": _("Export Source Files"),
            "res_model": "zenrecon.source.export.wizard", "view_mode": "form", "target": "new",
            "context": {
                "default_workspace_id": workspace.id,
                "default_scope": "selected" if selected else "all",
                "default_folder_ids": [(6, 0, selected.ids)],
            },
        }


class ZenreconSourceFile(models.Model):
    _name = "zenrecon.source.file"
    _description = "ZenRecon Source File Status"
    _order = "scan_date desc, modified_at desc, id desc"

    folder_id = fields.Many2one("zenrecon.source.folder", required=True, ondelete="cascade", index=True)
    workspace_id = fields.Many2one(related="folder_id.workspace_id", store=True, index=True)
    company_id = fields.Many2one(related="folder_id.company_id", store=True, index=True)
    parser_type = fields.Selection(related="folder_id.parser_type", store=True)
    file_name = fields.Char(required=True, index=True)
    relative_file_path = fields.Char(string="Logical File Location", required=True)
    source_directory = fields.Char(
        related="folder_id.source_path", string="PC / Shared Folder Path", readonly=True
    )
    absolute_path = fields.Char(groups="base.group_system")
    file_size = fields.Integer()
    modified_at = fields.Datetime()
    scan_date = fields.Date(required=True, index=True)
    last_seen_at = fields.Datetime()
    digest = fields.Char(required=True, index=True)
    state = fields.Selection(
        [("ready", "Ready"), ("processing", "Processing"), ("processed", "Processed"),
         ("error", "Error"), ("missing", "Missing")],
        default="ready", required=True, index=True,
    )
    message = fields.Text()
    processed_at = fields.Datetime()
    processed_by_id = fields.Many2one("res.users")
    import_model = fields.Char(readonly=True)
    import_res_id = fields.Integer(readonly=True)

    _folder_digest_unique = models.Constraint(
        "UNIQUE(folder_id, digest)", "This exact file was already discovered for the source folder."
    )

    def _wizard_payload(self, encoded, business_date):
        self.ensure_one()
        filename = self.file_name
        return {
            "visa_vss": ("bsr.vss.import.document.wizard", {"file": encoded, "filename": filename}, "action_import_and_process"),
            "visa_vx705": ("visa.vx.705.import.wizard", {"file": encoded, "filename": filename}, "action_import"),
            "visa_vx706": ("visa.vx.706.import.wizard", {"file": encoded, "filename": filename}, "action_import"),
            "visa_vx707": ("visa.vx.707.import.wizard", {"file": encoded, "filename": filename}, "action_import"),
            "visa_vx725": ("visa.vx.725.import.wizard", {"file": encoded, "filename": filename}, "action_import"),
            "visa_vx727": ("visa.vx.727.import.wizard", {"file": encoded, "filename": filename}, "action_import"),
            "mastercard_ipm": ("bsr.ipm.import.wizard", {"upload_file": encoded, "upload_filename": filename}, "action_import_and_process"),
            "mastercard_clearing": ("mastercard.clearing.import.wizard", {"file": encoded, "filename": filename}, "action_process"),
            "npsb_ocl": ("npsb.ocl.import.wizard", {"file": encoded, "filename": filename, "skip_duplicates": True}, "action_import"),
            "npsb_settlement": ("npsb.settlement.upload.wizard", {"pdf_file": encoded, "filename": filename}, "action_upload_and_process"),
            "cms": ("visa.detail.import.wizard", {"source": "cms", "business_date": business_date, "file": encoded, "filename": filename}, "action_upload"),
            "cbs": ("visa.detail.import.wizard", {"source": "cbs", "business_date": business_date, "file": encoded, "filename": filename}, "action_upload"),
        }[self.parser_type]

    def _process(self, business_date):
        self.ensure_one()
        if self.state == "processed":
            return True
        self.sudo().write({"state": "processing", "message": False})
        try:
            path = Path(self.absolute_path).resolve()
            try:
                path.relative_to(self.folder_id._resolved_path())
            except ValueError as error:
                raise UserError(_("The source file is outside its configured folder.")) from error
            if not path.is_file():
                raise UserError(_("Source file is no longer available: %s") % path)
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != self.digest:
                raise UserError(_("The source file changed after scanning. Scan the folder again."))
            model_name, values, method_name = self._wizard_payload(base64.b64encode(raw), business_date)
            with self.env.cr.savepoint():
                wizard = self.env[model_name].create(values)
                action = getattr(wizard, method_name)() or {}
            self.sudo().write({
                "state": "processed", "processed_at": fields.Datetime.now(),
                "processed_by_id": self.env.user.id,
                "import_model": action.get("res_model"), "import_res_id": action.get("res_id") or 0,
                "message": _("Processed successfully."),
            })
            return True
        except Exception as error:
            self.sudo().write({"state": "error", "message": str(error)})
            return False

    def action_open_import(self):
        self.ensure_one()
        if not self.import_model or not self.import_res_id:
            raise UserError(_("No imported business record is linked to this file."))
        return {
            "type": "ir.actions.act_window", "name": self.file_name,
            "res_model": self.import_model, "res_id": self.import_res_id,
            "view_mode": "form", "target": "current",
        }
