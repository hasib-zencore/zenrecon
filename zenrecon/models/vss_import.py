# -*- coding: utf-8 -*-
import base64
import hashlib
from decimal import Decimal

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from ..services.vss_parser import VSSParser


LINE_MODEL_BY_REPORT = {
    "VSS-110": "bsr.vss.110.line",
    "VSS-120": "bsr.vss.120.line",
    "VSS-130": "bsr.vss.130.line",
    "VSS-140": "bsr.vss.140.line",
    "VSS-210": "bsr.vss.210.line",
}
TARGET_REPORTS = tuple(LINE_MODEL_BY_REPORT)


class BsrVssImport(models.Model):
    _name = "bsr.vss.import"
    _description = "VSS File Import"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc, id desc"

    name = fields.Char(default=lambda self: _("New"), copy=False, readonly=True, tracking=True, index=True)
    attachment_id = fields.Many2one(
        "ir.attachment",
        string="Source File",
        required=True,
        ondelete="restrict",
        tracking=True,
        index=True,
    )
    file_name = fields.Char(readonly=True, tracking=True)
    file_hash = fields.Char(readonly=True, copy=False, index=True)
    file_size = fields.Integer(readonly=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("processing", "Processing"),
            ("completed", "Completed"),
            ("partial", "Completed with Exceptions"),
            ("failed", "Failed"),
        ],
        default="draft",
        required=True,
        tracking=True,
        index=True,
    )
    processing_started_at = fields.Datetime(readonly=True)
    processing_completed_at = fields.Datetime(readonly=True)
    processing_message = fields.Text(readonly=True)

    # Five consolidated report tables for this one imported text file.
    vss_110_line_ids = fields.One2many("bsr.vss.110.line", "import_id", string="VSS-110")
    vss_120_line_ids = fields.One2many("bsr.vss.120.line", "import_id", string="VSS-120")
    vss_130_line_ids = fields.One2many("bsr.vss.130.line", "import_id", string="VSS-130")
    vss_140_line_ids = fields.One2many("bsr.vss.140.line", "import_id", string="VSS-140")
    vss_210_line_ids = fields.One2many("bsr.vss.210.line", "import_id", string="VSS-210")

    exception_ids = fields.One2many("bsr.vss.exception", "import_id", string="Parsing Exceptions")

    # Legacy prototype logical reports are retained for safe upgrades only. New
    # processing deletes/does not recreate them.
    report_ids = fields.One2many("bsr.vss.report", "import_id", string="Legacy Logical Reports")

    # Consolidated report/table counts.
    vss_110_line_count = fields.Integer(compute="_compute_counts", store=True)
    vss_120_line_count = fields.Integer(compute="_compute_counts", store=True)
    vss_130_line_count = fields.Integer(compute="_compute_counts", store=True)
    vss_140_line_count = fields.Integer(compute="_compute_counts", store=True)
    vss_210_line_count = fields.Integer(compute="_compute_counts", store=True)
    consolidated_report_count = fields.Integer(compute="_compute_counts", store=True)
    exception_count = fields.Integer(compute="_compute_counts", store=True)

    # Source scanning statistics. NO DATA blocks are counted for audit but never
    # inserted into the five business tables.
    source_block_count = fields.Integer(readonly=True)
    data_block_count = fields.Integer(readonly=True)
    no_data_block_count = fields.Integer(readonly=True)
    error_block_count = fields.Integer(readonly=True)

    vss_110_source_count = fields.Integer(readonly=True)
    vss_120_source_count = fields.Integer(readonly=True)
    vss_130_source_count = fields.Integer(readonly=True)
    vss_140_source_count = fields.Integer(readonly=True)
    vss_210_source_count = fields.Integer(readonly=True)

    # Compatibility fields from the prototype. They now represent consolidated
    # line counts / high-level processing totals instead of logical report rows.
    report_count = fields.Integer(compute="_compute_counts", store=True)
    data_report_count = fields.Integer(compute="_compute_counts", store=True)
    no_data_report_count = fields.Integer(readonly=True)
    error_report_count = fields.Integer(readonly=True)
    vss_110_count = fields.Integer(compute="_compute_counts", store=True)
    vss_120_count = fields.Integer(compute="_compute_counts", store=True)
    vss_130_count = fields.Integer(compute="_compute_counts", store=True)
    vss_140_count = fields.Integer(compute="_compute_counts", store=True)
    vss_210_count = fields.Integer(compute="_compute_counts", store=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals.get("name") == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("bsr.vss.import") or _("New")
        return super().create(vals_list)

    @api.depends(
        "vss_110_line_ids",
        "vss_120_line_ids",
        "vss_130_line_ids",
        "vss_140_line_ids",
        "vss_210_line_ids",
        "exception_ids",
    )
    def _compute_counts(self):
        for rec in self:
            counts = {
                "110": len(rec.vss_110_line_ids),
                "120": len(rec.vss_120_line_ids),
                "130": len(rec.vss_130_line_ids),
                "140": len(rec.vss_140_line_ids),
                "210": len(rec.vss_210_line_ids),
            }
            rec.vss_110_line_count = counts["110"]
            rec.vss_120_line_count = counts["120"]
            rec.vss_130_line_count = counts["130"]
            rec.vss_140_line_count = counts["140"]
            rec.vss_210_line_count = counts["210"]
            rec.consolidated_report_count = sum(1 for value in counts.values() if value > 0)
            rec.exception_count = len(rec.exception_ids)

            rec.report_count = rec.consolidated_report_count
            rec.data_report_count = rec.consolidated_report_count
            rec.vss_110_count = counts["110"]
            rec.vss_120_count = counts["120"]
            rec.vss_130_count = counts["130"]
            rec.vss_140_count = counts["140"]
            rec.vss_210_count = counts["210"]

    def _get_source_bytes(self):
        self.ensure_one()
        attachment = self.attachment_id
        if not attachment:
            raise UserError(_("The source file is missing."))
        raw = attachment.raw
        if raw:
            return bytes(raw)
        if attachment.datas:
            return base64.b64decode(attachment.datas)
        raise UserError(_("The source attachment is empty."))

    @staticmethod
    def _decode_source(raw_bytes):
        for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                return raw_bytes.decode(encoding), encoding
            except UnicodeDecodeError:
                continue
        raise UserError(_("The source file could not be decoded as text."))

    @staticmethod
    def _clean_value(value):
        if isinstance(value, Decimal):
            return float(value)
        return value

    @classmethod
    def _clean_vals(cls, values):
        return {key: cls._clean_value(value) for key, value in values.items()}

    @staticmethod
    def _display_entity(ref, name):
        return " ".join(value for value in (ref, name) if value)

    def _common_line_vals(self, header):
        """Header/context copied to every extracted body row."""
        return {
            "import_id": self.id,
            "source_report_sequence": header.get("sequence_no") or 0,
            "report_code": header.get("report_code"),
            "report_name": header.get("report_name"),
            "service_name": header.get("service_name"),
            "reporting_for_ref": header.get("reporting_for_ref"),
            "reporting_for_name": header.get("reporting_for_name"),
            "reporting_for_display": self._display_entity(
                header.get("reporting_for_ref"), header.get("reporting_for_name")
            ),
            "rollup_to_ref": header.get("rollup_to_ref"),
            "rollup_to_name": header.get("rollup_to_name"),
            "rollup_to_display": self._display_entity(header.get("rollup_to_ref"), header.get("rollup_to_name")),
            "funds_xfer_entity_ref": header.get("funds_xfer_entity_ref"),
            "funds_xfer_entity_name": header.get("funds_xfer_entity_name"),
            "funds_xfer_entity_display": self._display_entity(
                header.get("funds_xfer_entity_ref"), header.get("funds_xfer_entity_name")
            ),
            "settlement_currency": header.get("settlement_currency"),
            "processing_date": header.get("processing_date"),
            "report_date": header.get("report_date"),
        }

    def action_process(self):
        for rec in self:
            rec._process_one()
        if any(rec.state == "failed" for rec in self):
            level = "danger"
            title = _("VSS Processing Failed")
        elif any(rec.state == "partial" for rec in self):
            level = "warning"
            title = _("VSS Processing Completed with Exceptions")
        else:
            level = "success"
            title = _("VSS Processing Complete")
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": title,
                "message": _("Five consolidated VSS report tables were rebuilt for this source file."),
                "type": level,
                "sticky": level != "success",
            },
        }

    def _process_one(self):
        """Process only this import's source file into five consolidated tables.

        For each target report code, all data-bearing logical blocks are appended
        to one table. Explicit ``NO DATA`` blocks are skipped completely. No
        parsed row from another import can enter this import's five tables.
        """
        self.ensure_one()
        if not self.attachment_id:
            raise UserError(_("Upload a source file first."))
        attachment = self.attachment_id
        file_name = attachment.name or self.file_name or ""
        if not file_name.lower().endswith(".txt"):
            raise UserError(_("Only .txt Visa settlement files are supported in this version."))

        raw_bytes = self._get_source_bytes()
        current_hash = hashlib.sha256(raw_bytes).hexdigest()
        duplicate = self.search(
            [
                ("id", "!=", self.id),
                ("file_hash", "=", current_hash),
                ("state", "in", ("completed", "partial")),
            ],
            limit=1,
        )
        if duplicate:
            raise UserError(_("This exact file was already processed in %s.") % duplicate.display_name)

        self.write(
            {
                "state": "processing",
                "file_name": file_name,
                "file_hash": current_hash,
                "file_size": len(raw_bytes),
                "processing_started_at": fields.Datetime.now(),
                "processing_completed_at": False,
                "processing_message": False,
                "source_block_count": 0,
                "data_block_count": 0,
                "no_data_block_count": 0,
                "error_block_count": 0,
                "no_data_report_count": 0,
                "error_report_count": 0,
                "vss_110_source_count": 0,
                "vss_120_source_count": 0,
                "vss_130_source_count": 0,
                "vss_140_source_count": 0,
                "vss_210_source_count": 0,
            }
        )

        try:
            text, encoding = self._decode_source(raw_bytes)
            parsed_reports, global_issues = VSSParser().parse(text)

            # Database replacement is atomic. If storing the rebuilt tables fails,
            # the previous derived report data remains available for investigation.
            with self.env.cr.savepoint():
                for model_name in LINE_MODEL_BY_REPORT.values():
                    self.env[model_name].search([("import_id", "=", self.id)]).unlink()
                self.exception_ids.unlink()
                # Remove prototype logical reports/legacy child rows for this batch.
                self.report_ids.unlink()

                for issue in global_issues:
                    self.env["bsr.vss.exception"].create(
                        {
                            "import_id": self.id,
                            "severity": issue.severity,
                            "message": issue.message,
                            "source_line_no": issue.source_line_no,
                            "raw_line": issue.raw_line,
                        }
                    )

                source_counts = {code: 0 for code in TARGET_REPORTS}
                sequence_by_code = {code: 0 for code in TARGET_REPORTS}
                data_blocks = no_data_blocks = error_blocks = 0

                for parsed in parsed_reports:
                    header = self._clean_vals(dict(parsed.header))
                    code = header.get("report_code")
                    if code not in LINE_MODEL_BY_REPORT:
                        continue
                    source_counts[code] += 1
                    status = header.get("data_status")

                    # Preserve parser issues without creating a separate logical
                    # report record. The exception identifies its source block.
                    for issue in parsed.issues:
                        self.env["bsr.vss.exception"].create(
                            {
                                "import_id": self.id,
                                "report_code": code,
                                "source_report_sequence": header.get("sequence_no") or 0,
                                "reporting_for": self._display_entity(
                                    header.get("reporting_for_ref"), header.get("reporting_for_name")
                                ),
                                "severity": issue.severity,
                                "message": issue.message,
                                "source_line_no": issue.source_line_no,
                                "raw_line": issue.raw_line,
                            }
                        )

                    if status == "no_data":
                        # Explicit business requirement: skip this block and
                        # continue searching for the next same report ID.
                        no_data_blocks += 1
                        continue

                    if status in ("parse_error", "incomplete"):
                        error_blocks += 1
                        continue

                    if status != "data" or not parsed.lines:
                        continue

                    data_blocks += 1
                    common_vals = self._common_line_vals(header)
                    create_vals = []
                    for line in parsed.lines:
                        sequence_by_code[code] += 1
                        vals = self._clean_vals(dict(line))
                        vals.update(common_vals)
                        vals["sequence"] = sequence_by_code[code]
                        create_vals.append(vals)
                    if create_vals:
                        self.env[LINE_MODEL_BY_REPORT[code]].create(create_vals)

                exceptions = self.env["bsr.vss.exception"].search([("import_id", "=", self.id)])
                has_error_exceptions = bool(exceptions.filtered(lambda e: e.severity == "error"))
                total_rows = sum(sequence_by_code.values())
                if not parsed_reports:
                    final_state = "failed"
                elif error_blocks or has_error_exceptions:
                    final_state = "partial"
                else:
                    final_state = "completed"

                summary = (
                    "Processed only %(file)s using %(encoding)s encoding. "
                    "Source blocks: %(blocks)s; data blocks appended: %(data)s; "
                    "NO DATA blocks skipped: %(nodata)s; block errors: %(errors)s. "
                    "Consolidated rows — VSS-110: %(r110)s, VSS-120: %(r120)s, "
                    "VSS-130: %(r130)s, VSS-140: %(r140)s, VSS-210: %(r210)s."
                ) % {
                    "file": file_name,
                    "encoding": encoding,
                    "blocks": len(parsed_reports),
                    "data": data_blocks,
                    "nodata": no_data_blocks,
                    "errors": error_blocks,
                    "r110": sequence_by_code["VSS-110"],
                    "r120": sequence_by_code["VSS-120"],
                    "r130": sequence_by_code["VSS-130"],
                    "r140": sequence_by_code["VSS-140"],
                    "r210": sequence_by_code["VSS-210"],
                }
                self.write(
                    {
                        "state": final_state,
                        "processing_completed_at": fields.Datetime.now(),
                        "processing_message": summary,
                        "source_block_count": len(parsed_reports),
                        "data_block_count": data_blocks,
                        "no_data_block_count": no_data_blocks,
                        "error_block_count": error_blocks,
                        "no_data_report_count": no_data_blocks,
                        "error_report_count": error_blocks,
                        "vss_110_source_count": source_counts["VSS-110"],
                        "vss_120_source_count": source_counts["VSS-120"],
                        "vss_130_source_count": source_counts["VSS-130"],
                        "vss_140_source_count": source_counts["VSS-140"],
                        "vss_210_source_count": source_counts["VSS-210"],
                    }
                )
        except Exception as exc:
            self.write(
                {
                    "state": "failed",
                    "processing_completed_at": fields.Datetime.now(),
                    "processing_message": str(exc),
                }
            )
            self.env["bsr.vss.exception"].create(
                {
                    "import_id": self.id,
                    "severity": "error",
                    "message": str(exc),
                }
            )

    def _open_consolidated_report(self, code):
        self.ensure_one()
        action_by_code = {
            "VSS-110": "zenrecon.action_bsr_vss_110_consolidated",
            "VSS-120": "zenrecon.action_bsr_vss_120_consolidated",
            "VSS-130": "zenrecon.action_bsr_vss_130_consolidated",
            "VSS-140": "zenrecon.action_bsr_vss_140_consolidated",
            "VSS-210": "zenrecon.action_bsr_vss_210_consolidated",
        }
        action = self.env["ir.actions.actions"]._for_xml_id(action_by_code[code])
        action["domain"] = [("import_id", "=", self.id)]
        action["context"] = {
            "create": False,
            "edit": False,
            "delete": False,
            "search_default_import_id": self.id,
        }
        action["name"] = _("%s — %s") % (code, self.file_name or self.name)
        return action

    def action_open_vss_110(self):
        return self._open_consolidated_report("VSS-110")

    def action_open_vss_120(self):
        return self._open_consolidated_report("VSS-120")

    def action_open_vss_130(self):
        return self._open_consolidated_report("VSS-130")

    def action_open_vss_140(self):
        return self._open_consolidated_report("VSS-140")

    def action_open_vss_210(self):
        return self._open_consolidated_report("VSS-210")

    def action_open_exceptions(self):
        self.ensure_one()
        action = self.env.ref("zenrecon.action_bsr_vss_exception").read()[0]
        action["domain"] = [("import_id", "=", self.id)]
        return action

    # Compatibility method retained so stale browser actions/buttons from the
    # prototype do not crash after module upgrade.
    def action_open_reports(self):
        self.ensure_one()
        return self.action_open_vss_110()
