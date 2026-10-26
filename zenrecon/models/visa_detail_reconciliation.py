# -*- coding: utf-8 -*-
import base64
import hashlib
import json
import re
from collections import defaultdict, deque

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from ..services.dynamic_table_parser import parse_dynamic_file


VISA_MODELS = {
    "705": "visa.vx.705",
    "706": "visa.vx.706",
    "707": "visa.vx.707",
    "725": "visa.vx.725",
    "727": "visa.vx.727",
}
TECHNICAL_FIELDS = {
    "id", "display_name", "create_uid", "create_date", "write_uid", "write_date",
    "__last_update", "batch_id", "company_id", "active", "imported_at",
}


def _normal_account(value):
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _masked(value):
    value = str(value or "")
    return ("•" * max(len(value) - 4, 0)) + value[-4:] if value else ""


class VisaDetailAccountType(models.Model):
    _name = "visa.detail.account.type"
    _description = "VISA Account Type"
    _order = "name"

    name = fields.Char(required=True, index=True)
    code = fields.Char(index=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )
    rule_ids = fields.One2many("visa.detail.account.rule", "account_type_id", string="Prefix Rules")

    _name_company_unique = models.Constraint(
        "UNIQUE(company_id, name)", "The account type name must be unique per company."
    )


class VisaDetailAccountRule(models.Model):
    _name = "visa.detail.account.rule"
    _description = "VISA Account Type Prefix Rule"
    _rec_name = "prefix"
    _order = "prefix_length desc, priority desc, id"

    prefix = fields.Char(required=True, help="Beginning characters of the account number.")
    prefix_normalized = fields.Char(compute="_compute_prefix", store=True, index=True)
    prefix_length = fields.Integer(compute="_compute_prefix", store=True)
    account_type_id = fields.Many2one(
        "visa.detail.account.type", required=True, ondelete="restrict", index=True
    )
    priority = fields.Integer(default=10, help="Used when equally specific rules overlap.")
    valid_from = fields.Date()
    valid_to = fields.Date()
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )

    _prefix_company_unique = models.Constraint(
        "UNIQUE(company_id, prefix_normalized)",
        "The normalized account prefix must be unique per company.",
    )

    @api.depends("prefix")
    def _compute_prefix(self):
        for rule in self:
            rule.prefix_normalized = _normal_account(rule.prefix)
            rule.prefix_length = len(rule.prefix_normalized)

    @api.constrains("prefix_normalized", "valid_from", "valid_to", "account_type_id", "company_id")
    def _check_rule(self):
        for rule in self:
            if not rule.prefix_normalized:
                raise ValidationError(_("Enter at least one letter or digit in the prefix."))
            if rule.valid_from and rule.valid_to and rule.valid_from > rule.valid_to:
                raise ValidationError(_("Valid To cannot be earlier than Valid From."))
            if rule.account_type_id.company_id != rule.company_id:
                raise ValidationError(_("The rule and account type must belong to the same company."))

    @api.model
    def _rule_data(self, company_id, on_date=None):
        on_date = fields.Date.to_date(on_date) if on_date else fields.Date.context_today(self)
        rules = self.search([("company_id", "=", company_id), ("active", "=", True)])
        rules = rules.filtered(
            lambda r: (not r.valid_from or r.valid_from <= on_date)
            and (not r.valid_to or r.valid_to >= on_date)
        )
        return [
            (rule.prefix_normalized, rule.account_type_id.id)
            for rule in rules.sorted(lambda r: (-r.prefix_length, -r.priority, r.id))
        ]

    @api.model
    def resolve(self, account_number, company_id, on_date=None):
        account = _normal_account(account_number)
        for prefix, account_type_id in self._rule_data(company_id, on_date):
            if account.startswith(prefix):
                return account_type_id
        return False

    def action_apply_to_existing(self):
        company_ids = self.mapped("company_id").ids or [self.env.company.id]
        total = 0
        for company_id in company_ids:
            rules = self._rule_data(company_id)
            for model_name in VISA_MODELS.values():
                model = self.env[model_name]
                last_id = 0
                while True:
                    records = model.search(
                        [("company_id", "=", company_id), ("id", ">", last_id)],
                        order="id", limit=2000,
                    )
                    if not records:
                        break
                    grouped = defaultdict(lambda: model.browse())
                    for record in records:
                        normalized = _normal_account(record.account_number)
                        account_type_id = next(
                            (type_id for prefix, type_id in rules if normalized.startswith(prefix)), False
                        )
                        grouped[account_type_id] |= record
                    for account_type_id, group in grouped.items():
                        group.write({"account_type_id": account_type_id})
                    total += len(records)
                    last_id = records[-1].id
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Account types refreshed"),
                "message": _("Applied the active rules to %(count)s VISA rows.", count=total),
                "type": "success",
                "sticky": False,
            },
        }


class VisaDetailSourceField(models.Model):
    _name = "visa.detail.source.field"
    _description = "VISA Detail Source Column"
    _rec_name = "label"
    _order = "source, label, id"

    source = fields.Selection(
        [("visa", "VISA"), ("cms", "CMS"), ("cbs", "CBS")], required=True, index=True
    )
    label = fields.Char(required=True)
    technical_name = fields.Char(required=True, index=True)
    report_types = fields.Char(readonly=True, help="VISA report types containing this column.")
    sample_value = fields.Char(readonly=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )

    _source_field_unique = models.Constraint(
        "UNIQUE(company_id, source, technical_name)",
        "A source column can only be registered once per company.",
    )

    @api.model
    def ensure_visa_fields(self, company=None):
        company = company or self.env.company
        found = {}
        for report_type, model_name in VISA_MODELS.items():
            for technical_name, field in self.env[model_name]._fields.items():
                if technical_name in TECHNICAL_FIELDS or not field.store:
                    continue
                if field.type in {"one2many", "many2many", "binary", "html"}:
                    continue
                values = found.setdefault(technical_name, {"label": field.string, "types": []})
                values["types"].append(report_type)
        existing = {
            record.technical_name: record
            for record in self.search([("company_id", "=", company.id), ("source", "=", "visa")])
        }
        for technical_name, values in found.items():
            report_types = ", ".join("VX-%s" % code for code in values["types"])
            if technical_name in existing:
                existing[technical_name].write({
                    "label": values["label"], "report_types": report_types, "active": True,
                })
            else:
                self.create({
                    "source": "visa", "label": values["label"],
                    "technical_name": technical_name, "report_types": report_types,
                    "company_id": company.id,
                })
        return True

    @api.model
    def upsert_import_fields(self, source, headers, company):
        existing = {
            record.technical_name: record
            for record in self.search([("company_id", "=", company.id), ("source", "=", source)])
        }
        result = {}
        for header in headers:
            values = {
                "label": header["name"],
                "sample_value": header.get("sample_value", "")[:200],
                "active": True,
            }
            record = existing.get(header["key"])
            if record:
                record.write(values)
            else:
                record = self.create({
                    **values, "source": source, "technical_name": header["key"],
                    "company_id": company.id,
                })
            result[header["key"]] = record
        return result


class VisaDetailImport(models.Model):
    _name = "visa.detail.import"
    _description = "CMS/CBS Daily Import"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "imported_at desc, id desc"

    name = fields.Char(default=lambda self: _("New"), readonly=True, copy=False, index=True)
    source = fields.Selection([("cms", "CMS"), ("cbs", "CBS")], required=True, index=True)
    business_date = fields.Date(required=True, index=True, default=fields.Date.context_today)
    file = fields.Binary(required=True, attachment=True, copy=False)
    filename = fields.Char(required=True)
    file_hash = fields.Char(readonly=True, copy=False, index=True)
    file_format = fields.Char(readonly=True)
    file_size = fields.Integer(readonly=True)
    state = fields.Selection(
        [("draft", "Draft"), ("processed", "Processed"), ("error", "Error")],
        default="draft", required=True, tracking=True, index=True,
    )
    error_message = fields.Text(readonly=True)
    column_ids = fields.One2many("visa.detail.import.column", "import_id", readonly=True)
    row_ids = fields.One2many("visa.detail.import.row", "import_id", readonly=True)
    column_count = fields.Integer(compute="_compute_counts")
    row_count = fields.Integer(compute="_compute_counts")
    imported_at = fields.Datetime(default=fields.Datetime.now, readonly=True, index=True)
    imported_by = fields.Many2one("res.users", default=lambda self: self.env.user, readonly=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )

    _file_source_unique = models.Constraint(
        "UNIQUE(company_id, source, file_hash)",
        "This file has already been processed for the selected source.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            if values.get("name", _("New")) == _("New"):
                values["name"] = self.env["ir.sequence"].next_by_code("visa.detail.import") or _("New")
        return super().create(vals_list)

    @api.depends("column_ids", "row_ids")
    def _compute_counts(self):
        for record in self:
            record.column_count = len(record.column_ids)
            record.row_count = len(record.row_ids)

    @staticmethod
    def _row_preview(values):
        parts = []
        for key, value in list(values.items())[:6]:
            shown = _masked(value) if any(token in key for token in ("account", "pan", "card_no")) else value
            parts.append("%s: %s" % (key.replace("_", " ").title(), shown))
        return " | ".join(parts)[:1000]

    def action_process(self):
        self.ensure_one()
        if self.state == "processed":
            return True
        try:
            raw = base64.b64decode(self.file or b"")
        except Exception as error:
            raise UserError(_("Could not decode the uploaded file: %s", error))
        if len(raw) > 250 * 1024 * 1024:
            raise UserError(_("The maximum supported file size is 250 MB."))
        digest = hashlib.sha256(raw).hexdigest()
        duplicate = self.search([
            ("id", "!=", self.id), ("company_id", "=", self.company_id.id),
            ("source", "=", self.source), ("file_hash", "=", digest),
            ("state", "=", "processed"),
        ], limit=1)
        if duplicate:
            raise UserError(_("This %(source)s file was already processed as %(name)s.",
                              source=self.source.upper(), name=duplicate.name))
        try:
            headers, rows, format_name = parse_dynamic_file(raw, self.filename)
        except Exception as error:
            raise UserError(_("Unable to read %(source)s file: %(error)s",
                              source=self.source.upper(), error=error))
        if not rows:
            raise UserError(_("No data rows were found in the uploaded file."))
        for header in headers:
            header["sample_value"] = next(
                (row["values"].get(header["key"], "") for row in rows
                 if row["values"].get(header["key"], "")), ""
            )
        field_map = self.env["visa.detail.source.field"].upsert_import_fields(
            self.source, headers, self.company_id
        )
        self.column_ids.unlink()
        self.row_ids.unlink()
        self.env["visa.detail.import.column"].create([
            {
                "import_id": self.id, "sequence": sequence,
                "field_id": field_map[header["key"]].id,
                "source_name": header["name"], "technical_name": header["key"],
                "sample_value": header.get("sample_value", "")[:200],
            }
            for sequence, header in enumerate(headers, 1)
        ])
        row_model = self.env["visa.detail.import.row"]
        for offset in range(0, len(rows), 1000):
            row_model.create([
                {
                    "import_id": self.id, "source": self.source,
                    "business_date": self.business_date, "row_number": row["row_number"],
                    "data_json": row["values"], "preview": self._row_preview(row["values"]),
                    "company_id": self.company_id.id,
                }
                for row in rows[offset:offset + 1000]
            ])
        self.write({
            "file_hash": digest, "file_format": format_name, "file_size": len(raw),
            "state": "processed", "error_message": False,
        })
        return True


class VisaDetailImportColumn(models.Model):
    _name = "visa.detail.import.column"
    _description = "CMS/CBS Imported Column"
    _order = "sequence, id"

    import_id = fields.Many2one("visa.detail.import", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    field_id = fields.Many2one("visa.detail.source.field", required=True, ondelete="restrict")
    source_name = fields.Char(required=True)
    technical_name = fields.Char(required=True)
    sample_value = fields.Char()
    company_id = fields.Many2one(related="import_id.company_id", store=True, index=True)


class VisaDetailImportRow(models.Model):
    _name = "visa.detail.import.row"
    _description = "CMS/CBS Imported Row"
    _rec_name = "preview"
    _order = "import_id desc, row_number, id"

    import_id = fields.Many2one("visa.detail.import", required=True, ondelete="cascade", index=True)
    source = fields.Selection(related="import_id.source", store=True, index=True)
    business_date = fields.Date(required=True, index=True)
    row_number = fields.Integer(required=True, index=True)
    data_json = fields.Json(required=True)
    preview = fields.Text(readonly=True)
    company_id = fields.Many2one("res.company", required=True, index=True)

    _import_row_unique = models.Constraint(
        "UNIQUE(import_id, row_number)", "A source row number can only occur once per import."
    )


class VisaDetailMatchProfile(models.Model):
    _name = "visa.detail.match.profile"
    _description = "VISA One-to-One Matching Profile"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "active desc, name"

    name = fields.Char(required=True, tracking=True)
    active = fields.Boolean(default=True, tracking=True)
    retention_months = fields.Integer(default=6, required=True, tracking=True)
    line_ids = fields.One2many("visa.detail.match.rule", "profile_id", copy=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )

    @api.model
    def default_get(self, field_list):
        self.env["visa.detail.source.field"].ensure_visa_fields()
        return super().default_get(field_list)

    @api.constrains("retention_months")
    def _check_retention(self):
        if any(record.retention_months < 1 or record.retention_months > 120 for record in self):
            raise ValidationError(_("Retention must be between 1 and 120 months."))

    def action_refresh_columns(self):
        self.env["visa.detail.source.field"].ensure_visa_fields(self.company_id or self.env.company)
        return {
            "type": "ir.actions.client", "tag": "display_notification",
            "params": {"title": _("Columns refreshed"),
                       "message": _("VISA fields and uploaded CMS/CBS headers are ready for mapping."),
                       "type": "success", "sticky": False},
        }

    def mapping_signature(self):
        self.ensure_one()
        payload = [
            (
                line.sequence, line.name, line.visa_field_id.technical_name,
                line.cms_field_id.technical_name, line.cbs_field_id.technical_name,
                line.normalizer, line.required,
            )
            for line in self.line_ids.sorted(lambda row: (row.sequence, row.id))
        ]
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest()


class VisaDetailMatchRule(models.Model):
    _name = "visa.detail.match.rule"
    _description = "VISA One-to-One Column Mapping"
    _order = "sequence, id"

    profile_id = fields.Many2one("visa.detail.match.profile", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    name = fields.Char(string="Matching Field", required=True)
    visa_field_id = fields.Many2one(
        "visa.detail.source.field", string="VISA Column", required=True, ondelete="restrict",
        domain="[('source', '=', 'visa'), ('company_id', '=', company_id), ('active', '=', True)]",
    )
    cms_field_id = fields.Many2one(
        "visa.detail.source.field", string="CMS Column", required=True, ondelete="restrict",
        domain="[('source', '=', 'cms'), ('company_id', '=', company_id), ('active', '=', True)]",
    )
    cbs_field_id = fields.Many2one(
        "visa.detail.source.field", string="CBS Column", required=True, ondelete="restrict",
        domain="[('source', '=', 'cbs'), ('company_id', '=', company_id), ('active', '=', True)]",
    )
    normalizer = fields.Selection([
        ("exact", "Exact"), ("trim", "Trim Spaces"), ("upper", "Case Insensitive"),
        ("alnum", "Letters & Digits Only"), ("digits", "Digits Only"),
    ], default="alnum", required=True)
    required = fields.Boolean(default=True)
    company_id = fields.Many2one(related="profile_id.company_id", store=True, index=True)


class VisaDetailReconciliationRun(models.Model):
    _name = "visa.detail.reconciliation.run"
    _description = "VISA Daily One-to-One Reconciliation"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "business_date desc, id desc"

    name = fields.Char(default=lambda self: _("New"), readonly=True, copy=False, index=True)
    business_date = fields.Date(required=True, default=fields.Date.context_today, index=True)
    profile_id = fields.Many2one("visa.detail.match.profile", required=True, ondelete="restrict")
    cms_import_id = fields.Many2one(
        "visa.detail.import", required=True, ondelete="restrict",
        domain="[('source', '=', 'cms'), ('state', '=', 'processed'), ('business_date', '=', business_date)]",
    )
    cbs_import_id = fields.Many2one(
        "visa.detail.import", required=True, ondelete="restrict",
        domain="[('source', '=', 'cbs'), ('state', '=', 'processed'), ('business_date', '=', business_date)]",
    )
    state = fields.Selection([
        ("draft", "Draft"), ("processing", "Processing"),
        ("completed", "Completed"), ("exception", "Exception"),
    ], default="draft", required=True, tracking=True, index=True)
    visa_count = fields.Integer(readonly=True)
    cms_count = fields.Integer(readonly=True)
    cbs_count = fields.Integer(readonly=True)
    matched_count = fields.Integer(readonly=True)
    unmatched_count = fields.Integer(readonly=True)
    match_group_count = fields.Integer(readonly=True)
    item_ids = fields.One2many("visa.detail.reconciliation.item", "run_id", readonly=True)
    processed_at = fields.Datetime(readonly=True)
    processed_by = fields.Many2one("res.users", readonly=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            if values.get("name", _("New")) == _("New"):
                values["name"] = self.env["ir.sequence"].next_by_code("visa.detail.run") or _("New")
        return super().create(vals_list)

    @api.constrains("business_date", "cms_import_id", "cbs_import_id", "profile_id", "company_id")
    def _check_sources(self):
        for run in self:
            for source, import_record in (("CMS", run.cms_import_id), ("CBS", run.cbs_import_id)):
                if import_record and (
                    import_record.business_date != run.business_date
                    or import_record.company_id != run.company_id
                    or import_record.source != source.lower()
                ):
                    raise ValidationError(_("The selected %s import does not match this run.", source))
            if run.profile_id and run.profile_id.company_id != run.company_id:
                raise ValidationError(_("The matching profile belongs to another company."))

    def _latest_visa_records(self):
        result = []
        for report_type, model_name in VISA_MODELS.items():
            model = self.env[model_name]
            latest = model.search([
                ("company_id", "=", self.company_id.id),
                ("system_date", "=", self.business_date), ("active", "=", True),
            ], order="imported_at desc, id desc", limit=1)
            if not latest:
                continue
            domain = [
                ("company_id", "=", self.company_id.id),
                ("system_date", "=", self.business_date), ("active", "=", True),
            ]
            if latest.batch_id:
                domain.append(("batch_id", "=", latest.batch_id.id))
            records = model.search(domain, order="id")
            result.extend((report_type, model_name, record) for record in records)
        return result

    @staticmethod
    def _normalize(value, mode):
        if hasattr(value, "display_name"):
            value = value.display_name
        if value is False or value is None:
            return ""
        value = str(value)
        if mode == "exact":
            return value
        if mode == "trim":
            return value.strip()
        if mode == "upper":
            return value.strip().upper()
        if mode == "digits":
            return re.sub(r"\D", "", value)
        return re.sub(r"[^A-Z0-9]", "", value.upper())

    def _create_source_items(self, visa_records):
        Item = self.env["visa.detail.reconciliation.item"]
        external_rows = self.cms_import_id.row_ids | self.cbs_import_id.row_ids
        all_keys = ["%s:%s" % (model_name, record.id) for _type, model_name, record in visa_records]
        all_keys += ["visa.detail.import.row:%s" % row.id for row in external_rows]
        existing_keys = set()
        for offset in range(0, len(all_keys), 5000):
            existing_keys.update(Item.search([
                ("company_id", "=", self.company_id.id),
                ("source_key", "in", all_keys[offset:offset + 5000]),
            ]).mapped("source_key"))
        values = []
        for report_type, model_name, record in visa_records:
            source_key = "%s:%s" % (model_name, record.id)
            if source_key in existing_keys:
                continue
            account_type_id = record.account_type_id.id
            if not account_type_id:
                account_type_id = self.env["visa.detail.account.rule"].resolve(
                    record.account_number, self.company_id.id, self.business_date
                )
                if account_type_id:
                    record.account_type_id = account_type_id
            values.append({
                "name": "%s/VISA-%s/%s" % (self.name, report_type, record.source_line_number or record.id),
                "run_id": self.id, "profile_id": self.profile_id.id,
                "business_date": self.business_date, "source": "visa",
                "source_channel": "visa_%s" % report_type,
                "source_label": "VISA VX-%s" % report_type,
                "visa_report_type": report_type, "source_model": model_name,
                "source_res_id": record.id, "source_key": source_key,
                "source_row_number": record.source_line_number or record.id,
                "source_reference": _masked(record.account_number) or str(record.id),
                "account_type_id": account_type_id, "company_id": self.company_id.id,
            })
        for import_record in (self.cms_import_id, self.cbs_import_id):
            for row in import_record.row_ids:
                source_key = "visa.detail.import.row:%s" % row.id
                if source_key in existing_keys:
                    continue
                values.append({
                    "name": "%s/%s/%s" % (self.name, import_record.source.upper(), row.row_number),
                    "run_id": self.id, "profile_id": self.profile_id.id,
                    "business_date": row.business_date, "source": import_record.source,
                    "source_channel": import_record.source,
                    "source_label": import_record.source.upper(),
                    "source_model": "visa.detail.import.row", "source_res_id": row.id,
                    "source_key": source_key, "source_row_id": row.id,
                    "source_import_id": import_record.id,
                    "source_row_number": row.row_number,
                    "source_reference": "%s row %s" % (import_record.name, row.row_number),
                    "company_id": self.company_id.id,
                })
        created = Item.browse()
        for offset in range(0, len(values), 2000):
            created |= Item.create(values[offset:offset + 2000])
        return created

    def _visa_record_cache(self, items):
        cache = {}
        grouped = defaultdict(list)
        for item in items.filtered(lambda r: r.source == "visa"):
            grouped[item.source_model].append(item.source_res_id)
        for model_name, record_ids in grouped.items():
            cache.update({(model_name, record.id): record for record in self.env[model_name].browse(record_ids).exists()})
        return cache

    def _item_value(self, item, rule, visa_cache):
        field_record = {
            "visa": rule.visa_field_id, "cms": rule.cms_field_id, "cbs": rule.cbs_field_id,
        }[item.source]
        if item.source == "visa":
            record = visa_cache.get((item.source_model, item.source_res_id))
            if not record or field_record.technical_name not in record._fields:
                return ""
            return record[field_record.technical_name]
        return (item.source_row_id.data_json or {}).get(field_record.technical_name, "")

    def _build_key(self, item, rules, visa_cache):
        values = []
        missing = []
        for rule in rules:
            value = self._normalize(self._item_value(item, rule, visa_cache), rule.normalizer)
            if rule.required and not value:
                missing.append(rule.name)
            values.append(value)
        if missing:
            return False, _("Missing required value: %s", ", ".join(missing))
        serialized = json.dumps(values, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest(), False

    def action_reconcile(self):
        self.ensure_one()
        if self.state != "draft":
            raise UserError(_("Only a draft run can be processed."))
        if self.cms_import_id.state != "processed" or self.cbs_import_id.state != "processed":
            raise UserError(_("Process both CMS and CBS imports before reconciliation."))
        rules = self.profile_id.line_ids.sorted(lambda line: (line.sequence, line.id))
        if not rules:
            raise UserError(_("The selected profile has no column mappings."))
        for source, import_record, field_name in (
            ("CMS", self.cms_import_id, "cms_field_id"),
            ("CBS", self.cbs_import_id, "cbs_field_id"),
        ):
            available = set(import_record.column_ids.mapped("technical_name"))
            missing = rules.filtered(lambda rule: rule[field_name].technical_name not in available)
            if missing:
                details = ", ".join(
                    "%s (%s)" % (rule.name, rule[field_name].label) for rule in missing
                )
                raise UserError(_(
                    "The %(source)s file does not match the saved profile. Missing column(s): %(columns)s",
                    source=source, columns=details,
                ))
        self.state = "processing"
        visa_records = self._latest_visa_records()
        if not visa_records:
            self.state = "exception"
            raise UserError(_("No VISA VX-705/706/707/725/727 data was found for %s.", self.business_date))
        self._create_source_items(visa_records)
        cutoff = self.business_date - relativedelta(months=self.profile_id.retention_months)
        candidates = self.env["visa.detail.reconciliation.item"].search([
            ("company_id", "=", self.company_id.id), ("status", "=", "unmatched"),
            ("business_date", ">=", cutoff), ("business_date", "<=", self.business_date),
        ], order="business_date, id")
        profile_signature = self.profile_id.mapping_signature()
        needs_compute = candidates.filtered(
            lambda item: not item.match_key_hash or item.match_profile_signature != profile_signature
        )
        needs_compute_ids = set(needs_compute.ids)
        visa_cache = self._visa_record_cache(needs_compute)
        buckets = defaultdict(list)
        for item in candidates:
            if item.id in needs_compute_ids:
                key_hash, reason = self._build_key(item, rules, visa_cache)
                item.write({
                    "profile_id": self.profile_id.id, "match_key_hash": key_hash or False,
                    "match_profile_signature": profile_signature,
                    "unmatched_reason": reason or _("No counterpart found within the active window."),
                })
            else:
                key_hash = item.match_key_hash
            if key_hash:
                buckets[key_hash].append(item)
        matched_items = self.env["visa.detail.reconciliation.item"]
        created_groups = self.env["visa.detail.match.group"]
        for key_hash, bucket_items in buckets.items():
            by_channel = defaultdict(deque)
            for item in bucket_items:
                by_channel[item.source_channel].append(item)
            while sum(bool(queue) for queue in by_channel.values()) >= 2:
                group_items = self.env["visa.detail.reconciliation.item"]
                for channel in sorted(by_channel):
                    if by_channel[channel]:
                        group_items |= by_channel[channel].popleft()
                labels = sorted(set(group_items.mapped("source_label")))
                group = self.env["visa.detail.match.group"].create({
                    "run_id": self.id, "business_date": max(group_items.mapped("business_date")),
                    "match_key_hash": key_hash, "matched_sources": ", ".join(labels),
                    "company_id": self.company_id.id,
                })
                for item in group_items:
                    other_labels = sorted(set(group_items.filtered(lambda row: row != item).mapped("source_label")))
                    item.write({
                        "status": "matched", "match_group_id": group.id,
                        "matched_with": ", ".join(other_labels), "matched_at": fields.Datetime.now(),
                        "unmatched_reason": False,
                    })
                matched_items |= group_items
                created_groups |= group
        current_items = self.env["visa.detail.reconciliation.item"].search([("run_id", "=", self.id)])
        self.write({
            "state": "completed", "visa_count": len(visa_records),
            "cms_count": len(self.cms_import_id.row_ids), "cbs_count": len(self.cbs_import_id.row_ids),
            "matched_count": len(current_items.filtered(lambda row: row.status == "matched")),
            "unmatched_count": len(current_items.filtered(lambda row: row.status == "unmatched")),
            "match_group_count": len(created_groups), "processed_at": fields.Datetime.now(),
            "processed_by": self.env.user.id,
        })
        return {
            "type": "ir.actions.act_window", "name": _("Reconciliation Results"),
            "res_model": "visa.detail.reconciliation.item", "view_mode": "list,form",
            "domain": [("run_id", "=", self.id)], "target": "current",
        }


class VisaDetailMatchGroup(models.Model):
    _name = "visa.detail.match.group"
    _description = "VISA Reconciliation Match"
    _order = "id desc"

    name = fields.Char(default=lambda self: _("New"), readonly=True, copy=False, index=True)
    run_id = fields.Many2one("visa.detail.reconciliation.run", ondelete="set null", index=True)
    business_date = fields.Date(required=True, index=True)
    match_key_hash = fields.Char(required=True, index=True)
    matched_sources = fields.Char(readonly=True)
    item_ids = fields.One2many("visa.detail.reconciliation.item", "match_group_id", readonly=True)
    company_id = fields.Many2one("res.company", required=True, index=True)

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            if values.get("name", _("New")) == _("New"):
                values["name"] = self.env["ir.sequence"].next_by_code("visa.detail.match") or _("New")
        return super().create(vals_list)


class VisaDetailReconciliationItem(models.Model):
    _name = "visa.detail.reconciliation.item"
    _description = "VISA Reconciliation Result"
    _order = "business_date desc, id desc"

    name = fields.Char(default=lambda self: _("New"), readonly=True, copy=False, index=True)
    run_id = fields.Many2one("visa.detail.reconciliation.run", ondelete="set null", index=True)
    profile_id = fields.Many2one("visa.detail.match.profile", ondelete="restrict", index=True)
    business_date = fields.Date(required=True, index=True)
    source = fields.Selection(
        [("visa", "VISA"), ("cms", "CMS"), ("cbs", "CBS")], required=True, index=True
    )
    source_channel = fields.Char(required=True, index=True)
    source_label = fields.Char(required=True)
    visa_report_type = fields.Selection([
        ("705", "VX-705"), ("706", "VX-706"), ("707", "VX-707"),
        ("725", "VX-725"), ("727", "VX-727"),
    ], index=True)
    source_model = fields.Char(required=True)
    source_res_id = fields.Integer(required=True)
    source_key = fields.Char(required=True, index=True)
    source_import_id = fields.Many2one("visa.detail.import", ondelete="set null", index=True)
    source_row_id = fields.Many2one("visa.detail.import.row", ondelete="set null", index=True)
    source_row_number = fields.Integer(index=True)
    source_reference = fields.Char(readonly=True)
    account_type_id = fields.Many2one("visa.detail.account.type", ondelete="set null", index=True)
    status = fields.Selection(
        [("unmatched", "Unmatched"), ("matched", "Matched")],
        default="unmatched", required=True, index=True,
    )
    match_key_hash = fields.Char(readonly=True, index=True)
    match_profile_signature = fields.Char(readonly=True)
    match_group_id = fields.Many2one("visa.detail.match.group", ondelete="set null", index=True)
    matched_with = fields.Char(readonly=True)
    matched_at = fields.Datetime(readonly=True)
    unmatched_reason = fields.Char(readonly=True)
    company_id = fields.Many2one("res.company", required=True, index=True)

    _source_key_unique = models.Constraint(
        "UNIQUE(company_id, source_key)", "This source row is already in reconciliation."
    )

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            if values.get("name", _("New")) == _("New"):
                values["name"] = self.env["ir.sequence"].next_by_code("visa.detail.item") or _("New")
        return super().create(vals_list)

    @api.model
    def _cron_archive_expired_unmatched(self, limit=2000):
        today = fields.Date.context_today(self)
        candidates = self.search([("status", "=", "unmatched")], order="business_date, id", limit=limit)
        expired = candidates.filtered(
            lambda item: item.business_date
            and item.business_date < today - relativedelta(months=item.profile_id.retention_months or 6)
        )
        if not expired:
            return 0
        self.env["visa.detail.reconciliation.archive"].create([
            {
                "original_name": item.name, "run_name": item.run_id.name,
                "profile_name": item.profile_id.name, "business_date": item.business_date,
                "source": item.source, "source_label": item.source_label,
                "visa_report_type": item.visa_report_type,
                "source_row_number": item.source_row_number,
                "source_reference": item.source_reference,
                "account_type_name": item.account_type_id.name,
                "match_key_hash": item.match_key_hash,
                "unmatched_reason": item.unmatched_reason,
                "company_id": item.company_id.id,
            }
            for item in expired
        ])
        count = len(expired)
        expired.unlink()
        return count


class VisaDetailReconciliationArchive(models.Model):
    _name = "visa.detail.reconciliation.archive"
    _description = "Archived VISA Unmatched Result"
    _rec_name = "original_name"
    _order = "business_date desc, id desc"

    original_name = fields.Char(required=True, index=True)
    run_name = fields.Char(index=True)
    profile_name = fields.Char()
    business_date = fields.Date(required=True, index=True)
    source = fields.Selection([("visa", "VISA"), ("cms", "CMS"), ("cbs", "CBS")], index=True)
    source_label = fields.Char()
    visa_report_type = fields.Selection([
        ("705", "VX-705"), ("706", "VX-706"), ("707", "VX-707"),
        ("725", "VX-725"), ("727", "VX-727"),
    ])
    source_row_number = fields.Integer()
    source_reference = fields.Char()
    account_type_name = fields.Char()
    match_key_hash = fields.Char(index=True)
    unmatched_reason = fields.Char()
    archived_at = fields.Datetime(default=fields.Datetime.now, required=True, index=True)
    company_id = fields.Many2one("res.company", required=True, index=True)


def _assign_account_types(env, vals_list):
    rule_model = env["visa.detail.account.rule"]
    rule_cache = {}
    for values in vals_list:
        if values.get("account_type_id") or not values.get("account_number"):
            continue
        company_id = values.get("company_id") or env.company.id
        on_date = values.get("system_date")
        cache_key = (company_id, str(on_date or ""))
        if cache_key not in rule_cache:
            rule_cache[cache_key] = rule_model._rule_data(company_id, on_date)
        account = _normal_account(values["account_number"])
        values["account_type_id"] = next(
            (type_id for prefix, type_id in rule_cache[cache_key] if account.startswith(prefix)), False
        )


class VisaVX705AccountType(models.Model):
    _inherit = "visa.vx.705"

    account_type_id = fields.Many2one(
        "visa.detail.account.type", string="Account Type", readonly=True, index=True, ondelete="set null"
    )

    @api.model_create_multi
    def create(self, vals_list):
        _assign_account_types(self.env, vals_list)
        return super().create(vals_list)


class VisaVX706AccountType(models.Model):
    _inherit = "visa.vx.706"

    account_type_id = fields.Many2one(
        "visa.detail.account.type", string="Account Type", readonly=True, index=True, ondelete="set null"
    )

    @api.model_create_multi
    def create(self, vals_list):
        _assign_account_types(self.env, vals_list)
        return super().create(vals_list)


class VisaVX707AccountType(models.Model):
    _inherit = "visa.vx.707"

    account_type_id = fields.Many2one(
        "visa.detail.account.type", string="Account Type", readonly=True, index=True, ondelete="set null"
    )

    @api.model_create_multi
    def create(self, vals_list):
        _assign_account_types(self.env, vals_list)
        return super().create(vals_list)


class VisaVX725AccountType(models.Model):
    _inherit = "visa.vx.725"

    account_type_id = fields.Many2one(
        "visa.detail.account.type", string="Account Type", readonly=True, index=True, ondelete="set null"
    )

    @api.model_create_multi
    def create(self, vals_list):
        _assign_account_types(self.env, vals_list)
        return super().create(vals_list)


class VisaVX727AccountType(models.Model):
    _inherit = "visa.vx.727"

    account_type_id = fields.Many2one(
        "visa.detail.account.type", string="Account Type", readonly=True, index=True, ondelete="set null"
    )

    @api.model_create_multi
    def create(self, vals_list):
        _assign_account_types(self.env, vals_list)
        return super().create(vals_list)
