# -*- coding: utf-8 -*-
import base64
import hashlib
import re

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from ..services.ipm_parser import amount_value, field_value, parse_ipm
from ..services.ipm_xlsx import build_complete_workbook


class BsrIpmImport(models.Model):
    _name = "bsr.ipm.import"
    _description = "Mastercard IPM Import"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc, id desc"

    name = fields.Char(default=lambda self: _("New"), readonly=True, copy=False, index=True, tracking=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )
    attachment_id = fields.Many2one(
        "ir.attachment",
        string="Source File",
        required=True,
        ondelete="restrict",
        index=True,
        tracking=True,
    )
    file_name = fields.Char(readonly=True, tracking=True)
    file_hash = fields.Char(string="SHA-256", readonly=True, copy=False, index=True)
    file_size = fields.Integer(readonly=True)
    physical_block_size = fields.Integer(readonly=True, default=1014)
    data_bytes_per_block = fields.Integer(readonly=True, default=1012)
    logical_size = fields.Integer(readonly=True)
    input_encoding = fields.Char(readonly=True)
    parser_version = fields.Char(readonly=True)
    metadata_json = fields.Json(readonly=True)

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("processing", "Processing"),
            ("completed", "Completed"),
            ("partial", "Completed with Errors"),
            ("failed", "Failed"),
        ],
        default="draft", required=True, readonly=True, tracking=True, index=True,
    )
    processing_started_at = fields.Datetime(readonly=True)
    processing_completed_at = fields.Datetime(readonly=True)
    processing_message = fields.Text(readonly=True)

    record_ids = fields.One2many("bsr.ipm.record", "import_id", string="IPM Records")
    error_ids = fields.One2many("bsr.ipm.parse.error", "import_id", string="Parse Errors")
    record_count = fields.Integer(compute="_compute_counts", store=True)
    field_count = fields.Integer(compute="_compute_counts", store=True)
    error_count = fields.Integer(compute="_compute_counts", store=True)

    _unique_file_record = models.Constraint(
        "UNIQUE(file_hash, company_id)",
        "This Mastercard file has already been registered for this company.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals.get("name") == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("bsr.ipm.import") or _("New")
        return super().create(vals_list)

    @api.depends("record_ids", "record_ids.field_ids", "error_ids")
    def _compute_counts(self):
        for batch in self:
            batch.record_count = len(batch.record_ids)
            batch.field_count = sum(len(record.field_ids) for record in batch.record_ids)
            batch.error_count = len(batch.error_ids)

    def _source_bytes(self):
        self.ensure_one()
        attachment = self.attachment_id
        if not attachment:
            raise UserError(_("The Mastercard source file is missing."))
        if attachment.raw:
            return bytes(attachment.raw)
        if attachment.datas:
            return base64.b64decode(attachment.datas)
        raise UserError(_("The Mastercard source file is empty."))

    def action_process(self):
        for batch in self:
            batch._process_one()
        failed = self.filtered(lambda row: row.state == "failed")
        partial = self.filtered(lambda row: row.state == "partial")
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Mastercard IPM Import"),
                "message": failed[:1].processing_message if failed else _(
                    "%s record(s) stored with %s parsing error(s)."
                ) % (sum(self.mapped("record_count")), sum(self.mapped("error_count"))),
                "type": "danger" if failed else ("warning" if partial else "success"),
                "sticky": bool(failed or partial),
            },
        }

    def _process_one(self):
        self.ensure_one()
        raw = self._source_bytes()
        filename = self.attachment_id.name or self.file_name or "mastercard.ipm"
        digest = hashlib.sha256(raw).hexdigest()
        duplicate = self.search([
            ("id", "!=", self.id), ("company_id", "=", self.company_id.id),
            ("file_hash", "=", digest), ("state", "in", ("completed", "partial")),
        ], limit=1)
        if duplicate:
            raise UserError(_("This exact Mastercard file was already processed in %s.") % duplicate.display_name)

        self.write({
            "state": "processing", "processing_started_at": fields.Datetime.now(),
            "processing_completed_at": False, "processing_message": False,
            "file_name": filename, "file_hash": digest, "file_size": len(raw),
        })
        self.record_ids.unlink()
        self.error_ids.unlink()
        try:
            document = parse_ipm(raw, filename=filename)
            metadata = document["file"]
            items = document["records"]
            records = self.env["bsr.ipm.record"].create([
                self._record_values(item) for item in items
            ]) if items else self.env["bsr.ipm.record"]
            field_rows = []
            error_rows = []
            for item, record in zip(items, records):
                for de, value in item.get("fields", {}).items():
                    field_rows.append({
                        "record_id": record.id,
                        "field_no": int(de),
                        "field_type": value.get("type"),
                        "data_class": value.get("data_class"),
                        "field_length": value.get("length"),
                        "value_text": value.get("value"),
                    })
                if item.get("status") == "error":
                    error_rows.append({
                        "import_id": self.id, "record_id": record.id,
                        "record_no": item["record_no"], "logical_offset": item["logical_offset"],
                        "error_stage": "ISO8583", "error_message": item.get("error") or _("Unknown error"),
                    })
            if field_rows:
                self.env["bsr.ipm.field"].create(field_rows)
            if error_rows:
                self.env["bsr.ipm.parse.error"].create(error_rows)
            self.write({
                "physical_block_size": metadata["physical_block_size"],
                "data_bytes_per_block": metadata["data_bytes_per_block"],
                "logical_size": metadata["logical_size"],
                "input_encoding": metadata["input_encoding"],
                "parser_version": metadata["parser_version"],
                "metadata_json": metadata,
                "state": "partial" if metadata["error_count"] else "completed",
                "processing_completed_at": fields.Datetime.now(),
                "processing_message": _("Stored %s Mastercard IPM record(s).") % metadata["record_count"],
            })
        except Exception as exc:
            self.env["bsr.ipm.parse.error"].create({
                "import_id": self.id,
                "record_no": 0,
                "logical_offset": 0,
                "error_stage": "RDW",
                "error_message": str(exc),
            })
            self.write({
                "state": "failed", "processing_completed_at": fields.Datetime.now(),
                "processing_message": str(exc),
            })
        return self

    def _record_values(self, item):
        parsed_fields = item.get("fields", {})
        return {
            "import_id": self.id,
            "record_no": item["record_no"],
            "logical_offset": item["logical_offset"],
            "declared_length": item["declared_length"],
            "input_encoding": item.get("encoding"),
            "mti": item.get("mti"),
            "function_code": item.get("function_code"),
            "record_type": item.get("record_type"),
            "bitmap_hex": item.get("bitmap_hex"),
            "present_fields": item.get("present_fields", []),
            "pan_masked": item.get("pan_masked"),
            "processing_code": field_value(item, 3),
            "transaction_amount": amount_value(item, 4),
            "transaction_currency": field_value(item, 49),
            "settlement_amount": amount_value(item, 5),
            "settlement_currency": field_value(item, 50),
            "stan": field_value(item, 11),
            "rrn": field_value(item, 37),
            "transaction_datetime": field_value(item, 12),
            "parse_status": item.get("status"),
            "consumed_bytes": item.get("consumed_bytes"),
            "unparsed_bytes": item.get("unparsed_bytes"),
            "fields_json": parsed_fields,
            "error_message": item.get("error"),
        }

    def _open_related(self, action_xmlid, domain):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(action_xmlid)
        action["domain"] = domain
        action["context"] = {"create": False}
        return action

    def action_open_records(self):
        return self._open_related("zenrecon.action_bsr_ipm_record", [("import_id", "=", self.id)])

    def action_open_fields(self):
        return self._open_related("zenrecon.action_bsr_ipm_field", [("import_id", "=", self.id)])

    def action_open_errors(self):
        return self._open_related("zenrecon.action_bsr_ipm_error", [("import_id", "=", self.id)])

    def action_download_complete_xlsx(self):
        self.ensure_one()
        record_fields = [
            "id", "record_no", "logical_offset", "declared_length", "input_encoding", "mti",
            "function_code", "record_type", "bitmap_hex", "present_fields", "pan_masked",
            "processing_code", "transaction_amount", "transaction_currency", "settlement_amount",
            "settlement_currency", "stan", "rrn", "transaction_datetime", "parse_status",
            "consumed_bytes", "unparsed_bytes", "error_message",
        ]
        records = self.env["bsr.ipm.record"].search_read(
            [("import_id", "=", self.id)], record_fields, order="record_no"
        )
        record_numbers = {row["id"]: row["record_no"] for row in records}
        for row in records:
            row.update({"import_name": self.name, "file_name": self.file_name})

        element_fields = ["record_id", "field_no", "field_type", "data_class", "field_length", "value_text"]
        elements = self.env["bsr.ipm.field"].search_read(
            [("import_id", "=", self.id)], element_fields, order="record_id, field_no"
        )
        for row in elements:
            record_id = row["record_id"][0]
            row.update({
                "record_id": record_id,
                "record_no": record_numbers.get(record_id),
                "import_name": self.name,
            })

        errors = self.env["bsr.ipm.parse.error"].search_read(
            [("import_id", "=", self.id)],
            ["record_no", "logical_offset", "error_stage", "error_message"],
            order="record_no",
        )
        for row in errors:
            row["import_name"] = self.name

        metadata = {
            "Import": self.name,
            "Source Filename": self.file_name,
            "Source File": self.attachment_id.name or self.file_name,
            "Company": self.company_id.display_name,
            "SHA-256": self.file_hash,
            "Source Size": self.file_size,
            "Physical Block Size": self.physical_block_size,
            "Data Bytes per Block": self.data_bytes_per_block,
            "Logical Size": self.logical_size,
            "Input Encoding": self.input_encoding,
            "Parser Version": self.parser_version,
            "Processing Status": dict(self._fields["state"].selection).get(self.state, self.state),
            "Record Count": self.record_count,
            "Data Element Count": self.field_count,
            "Error Count": self.error_count,
            "Processing Started At": fields.Datetime.to_string(self.processing_started_at) if self.processing_started_at else "",
            "Processing Completed At": fields.Datetime.to_string(self.processing_completed_at) if self.processing_completed_at else "",
        }
        content = build_complete_workbook(metadata, records, elements, errors)
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", self.name).strip("_")
        wizard = self.env["bsr.ipm.export.wizard"].create({
            "file_data": base64.b64encode(content),
            "file_name": f"{safe_name or 'Mastercard_IPM'}_complete.xlsx",
        })
        return {
            "type": "ir.actions.act_window",
            "name": _("Complete Mastercard XLSX"),
            "res_model": "bsr.ipm.export.wizard",
            "res_id": wizard.id,
            "view_mode": "form",
            "target": "new",
        }


class BsrIpmRecord(models.Model):
    _name = "bsr.ipm.record"
    _description = "Mastercard IPM Record"
    _order = "import_id desc, record_no"

    import_id = fields.Many2one("bsr.ipm.import", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="import_id.company_id", store=True, index=True)
    attachment_id = fields.Many2one(related="import_id.attachment_id", store=True, index=True)
    record_no = fields.Integer(required=True, index=True)
    logical_offset = fields.Integer(required=True)
    declared_length = fields.Integer(required=True)
    input_encoding = fields.Char()
    mti = fields.Char(index=True)
    function_code = fields.Char(index=True)
    record_type = fields.Char(index=True)
    bitmap_hex = fields.Char()
    present_fields = fields.Json()
    pan_masked = fields.Char(string="Masked PAN", index=True)
    processing_code = fields.Char(index=True)
    transaction_amount = fields.Float(digits=(20, 2))
    transaction_currency = fields.Char(index=True)
    settlement_amount = fields.Float(digits=(20, 2))
    settlement_currency = fields.Char(index=True)
    stan = fields.Char(index=True)
    rrn = fields.Char(index=True)
    transaction_datetime = fields.Char()
    parse_status = fields.Selection(
        [("parsed", "Parsed"), ("remainder", "Parsed with Remainder"), ("error", "Error")],
        required=True, index=True,
    )
    consumed_bytes = fields.Integer()
    unparsed_bytes = fields.Integer()
    fields_json = fields.Json()
    error_message = fields.Text()
    field_ids = fields.One2many("bsr.ipm.field", "record_id")

    _unique_record_no = models.Constraint(
        "UNIQUE(import_id, record_no)", "A record number may occur only once within an IPM import."
    )

    def action_download_complete_xlsx(self):
        imports = self.mapped("import_id")
        if len(imports) != 1:
            raise UserError(_("Select records from one Mastercard import only."))
        return imports.action_download_complete_xlsx()


class BsrIpmField(models.Model):
    _name = "bsr.ipm.field"
    _description = "Mastercard IPM Data Element"
    _order = "record_id, field_no"

    record_id = fields.Many2one("bsr.ipm.record", required=True, ondelete="cascade", index=True)
    import_id = fields.Many2one(related="record_id.import_id", store=True, index=True)
    company_id = fields.Many2one(related="record_id.company_id", store=True, index=True)
    field_no = fields.Integer(string="DE", required=True, index=True)
    field_type = fields.Char()
    data_class = fields.Char()
    field_length = fields.Integer()
    value_text = fields.Text(string="Value")

    _unique_record_field = models.Constraint(
        "UNIQUE(record_id, field_no)", "A data element may occur only once within an IPM record."
    )


class BsrIpmParseError(models.Model):
    _name = "bsr.ipm.parse.error"
    _description = "Mastercard IPM Parse Error"
    _order = "import_id desc, record_no"

    import_id = fields.Many2one("bsr.ipm.import", required=True, ondelete="cascade", index=True)
    record_id = fields.Many2one("bsr.ipm.record", ondelete="cascade", index=True)
    company_id = fields.Many2one(related="import_id.company_id", store=True, index=True)
    record_no = fields.Integer(index=True)
    logical_offset = fields.Integer()
    error_stage = fields.Char(required=True, index=True)
    error_message = fields.Text(required=True)
