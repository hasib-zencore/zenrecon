# -*- coding: utf-8 -*-
import re

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


IDENTITY_FIELDS = (
    ("reporting_for", "Reporting For"),
    ("rollup_to", "Rollup To"),
    ("funds_xfer_entity", "Funds Xfer Entity"),
)
DIMENSIONS = (
    ("business_owner", "Business Owner"),
    ("product_type", "Product Type"),
    ("card_type", "Card Type"),
)
VSS_LINE_MODELS = tuple(
    f"bsr.vss.{code}.line" for code in ("110", "120", "130", "140", "210")
)
VSS_IDENTITY_SOURCE_FIELDS = {
    "reporting_for": "reporting_for_display",
    "rollup_to": "rollup_to_display",
    "funds_xfer_entity": "funds_xfer_entity_display",
}


def _clean(value):
    return " ".join(str(value or "").strip().split())


def _key(value):
    return _clean(value).casefold()


def _split_values(value):
    return [_clean(item) for item in re.split(r"[,;|\n]+", value or "") if _clean(item)]


class BsrVisaSourceOption(models.Model):
    """Current VSS identities, reused so their permanent business mapping survives."""

    _name = "bsr.visa.source.option"
    _description = "VISA Configuration Identity Value"
    _order = "field_name, name, id"

    name = fields.Char(required=True, index=True)
    value_key = fields.Char(required=True, index=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )
    field_name = fields.Selection(IDENTITY_FIELDS, required=True, index=True)
    active = fields.Boolean(default=True)
    last_seen_import_id = fields.Many2one(
        "bsr.vss.import", string="Last Seen VSS File", readonly=True, ondelete="set null", index=True
    )

    _company_field_value_unique = models.Constraint(
        "UNIQUE(company_id, field_name, value_key)",
        "Each VISA configuration identity value must be unique per company.",
    )

    @api.model
    def sync_from_import(self, source_import):
        """Replace active identity choices with one processed VSS file's values.

        Existing option records are reused by normalized value. This keeps the
        administrator's VISA Setup relations while making the current file the
        authoritative source for the first three columns.
        """
        source_import.ensure_one()
        if source_import.state not in ("completed", "partial"):
            return self.browse()

        expected = {field_name: {} for field_name, _label in IDENTITY_FIELDS}
        for model_name in VSS_LINE_MODELS:
            lines = self.env[model_name].sudo().search(
                [("import_id", "=", source_import.id)]
            )
            for field_name, source_field in VSS_IDENTITY_SOURCE_FIELDS.items():
                for value in lines.mapped(source_field):
                    cleaned = _clean(value)
                    if cleaned:
                        expected[field_name].setdefault(_key(cleaned), cleaned)

        Option = self.sudo().with_context(active_test=False)
        current = Option.search([("company_id", "=", source_import.company_id.id)])
        existing = {(row.field_name, row.value_key): row for row in current}
        active_options = self.browse()
        expected_keys = {
            (field_name, value_key)
            for field_name, values in expected.items()
            for value_key in values
        }
        for field_name, values in expected.items():
            for value_key, name in values.items():
                option = existing.get((field_name, value_key))
                vals = {
                    "name": name,
                    "active": True,
                    "last_seen_import_id": source_import.id,
                }
                if option:
                    option.write(vals)
                else:
                    option = Option.create(
                        {
                            **vals,
                            "company_id": source_import.company_id.id,
                            "field_name": field_name,
                            "value_key": value_key,
                        }
                    )
                active_options |= option

        obsolete = current.filtered(
            lambda row: (row.field_name, row.value_key) not in expected_keys and row.active
        )
        if obsolete:
            obsolete.write({"active": False})
        return active_options

    @api.model
    def sync_latest_imports(self, companies=None):
        companies = companies or self.env.companies
        Import = self.env["bsr.vss.import"].sudo()
        result = self.browse()
        for company in companies:
            source_import = Import.search(
                [
                    ("company_id", "=", company.id),
                    ("state", "in", ("completed", "partial")),
                ],
                order="processing_completed_at desc, id desc",
                limit=1,
            )
            if source_import:
                result |= self.sync_from_import(source_import)
        return result

    @api.model
    def sync_from_configurations(self, companies=None):
        """Compatibility entrypoint; processed VSS data is authoritative.

        The configuration fallback supports a database that has not processed
        any VSS file yet. Once a file exists, configurations can no longer
        replace or deactivate identities discovered in that file.
        """
        companies = companies or self.env.companies
        Configuration = self.env["bsr.accounting.configuration"].sudo()
        Import = self.env["bsr.vss.import"].sudo()
        Option = self.sudo().with_context(active_test=False)
        result = self.browse()
        for company in companies:
            source_import = Import.search(
                [
                    ("company_id", "=", company.id),
                    ("state", "in", ("completed", "partial")),
                ],
                order="processing_completed_at desc, id desc",
                limit=1,
            )
            if source_import:
                result |= self.sync_from_import(source_import)
                continue
            configurations = Configuration.search(
                [("company_id", "=", company.id), ("batch_run_id", "=", False)]
            )
            current = Option.search([("company_id", "=", company.id)])
            expected = {}
            for field_name, _label in IDENTITY_FIELDS:
                for value in configurations.mapped(field_name):
                    for item in _split_values(value):
                        expected[(field_name, _key(item))] = item
            existing = {(row.field_name, row.value_key): row for row in current}
            for identity, name in expected.items():
                row = existing.get(identity)
                if row:
                    values = {}
                    if row.name != name:
                        values["name"] = name
                    if not row.active:
                        values["active"] = True
                    if values:
                        row.write(values)
                else:
                    Option.create(
                        {
                            "company_id": company.id,
                            "field_name": identity[0],
                            "value_key": identity[1],
                            "name": name,
                        }
                    )
            obsolete = current.filtered(
                lambda row: (row.field_name, row.value_key) not in expected
            )
            if obsolete:
                obsolete.write({"active": False})
            result |= self.search([("company_id", "=", company.id)])
        return result


class BsrVssImport(models.Model):
    _inherit = "bsr.vss.import"

    def _process_one(self):
        result = super()._process_one()
        for source_import in self.filtered(lambda item: item.state in ("completed", "partial")):
            self.env["bsr.visa.source.option"].sync_from_import(source_import)
        return result


class BsrVisaDimensionOption(models.Model):
    """Friendly Voucher Run choices maintained from the VISA Setup table."""

    _name = "bsr.visa.dimension.option"
    _description = "VISA Voucher Selection Value"
    _order = "is_all desc, name, id"

    name = fields.Char(required=True, index=True)
    value_key = fields.Char(required=True, index=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )
    dimension = fields.Selection(DIMENSIONS, required=True, index=True)
    is_all = fields.Boolean(default=False, index=True)
    active = fields.Boolean(default=True)

    _company_dimension_value_unique = models.Constraint(
        "UNIQUE(company_id, dimension, value_key)",
        "Each VISA selection value must be unique per company.",
    )

    @api.model
    def all_option(self, company, dimension):
        option = self.sudo().with_context(active_test=False).search(
            [
                ("company_id", "=", company.id),
                ("dimension", "=", dimension),
                ("is_all", "=", True),
            ],
            limit=1,
        )
        if not option:
            option = self.sudo().create(
                {
                    "company_id": company.id,
                    "dimension": dimension,
                    "name": _("All"),
                    "value_key": "__all__",
                    "is_all": True,
                }
            )
        elif not option.active:
            option.active = True
        return option

    @api.model
    def sync_from_setups(self, companies=None):
        companies = companies or self.env.companies
        Setup = self.env["bsr.visa.setup"].sudo()
        Option = self.sudo().with_context(active_test=False)
        for company in companies:
            setups = Setup.search([("company_id", "=", company.id)])
            for dimension, _label in DIMENSIONS:
                self.all_option(company, dimension)
                expected = {
                    _key(value): _clean(value)
                    for value in setups.mapped(dimension)
                    if _clean(value)
                }
                current = Option.search(
                    [
                        ("company_id", "=", company.id),
                        ("dimension", "=", dimension),
                        ("is_all", "=", False),
                    ]
                )
                existing = {row.value_key: row for row in current}
                for value_key, name in expected.items():
                    row = existing.get(value_key)
                    if row:
                        values = {}
                        if row.name != name:
                            values["name"] = name
                        if not row.active:
                            values["active"] = True
                        if values:
                            row.write(values)
                    else:
                        Option.create(
                            {
                                "company_id": company.id,
                                "dimension": dimension,
                                "name": name,
                                "value_key": value_key,
                            }
                        )
                obsolete = current.filtered(lambda row: row.value_key not in expected)
                if obsolete:
                    obsolete.write({"active": False})


class BsrVisaSetup(models.Model):
    _name = "bsr.visa.setup"
    _description = "VISA Setup Mapping"
    _order = "sequence, id"
    _check_company_auto = True

    sequence = fields.Integer(default=10)
    name = fields.Char(required=True, default=lambda self: _("VISA Setup"))
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )
    reporting_for_option_ids = fields.Many2many(
        "bsr.visa.source.option",
        "bsr_visa_setup_reporting_rel",
        "setup_id",
        "option_id",
        string="Reporting For",
    )
    rollup_to_option_ids = fields.Many2many(
        "bsr.visa.source.option",
        "bsr_visa_setup_rollup_rel",
        "setup_id",
        "option_id",
        string="Rollup To",
    )
    funds_xfer_entity_option_ids = fields.Many2many(
        "bsr.visa.source.option",
        "bsr_visa_setup_funds_rel",
        "setup_id",
        "option_id",
        string="Funds Xfer Entity",
    )
    business_owner = fields.Char(required=True, index=True)
    product_type = fields.Char(required=True, index=True)
    card_type = fields.Char(required=True, index=True)
    active = fields.Boolean(default=True)

    @staticmethod
    def _display_name_from_values(values):
        return " / ".join(
            filter(
                None,
                (
                    _clean(values.get("business_owner")),
                    _clean(values.get("product_type")),
                    _clean(values.get("card_type")),
                ),
            )
        ) or _("VISA Setup")

    @api.constrains(
        "reporting_for_option_ids",
        "rollup_to_option_ids",
        "funds_xfer_entity_option_ids",
        "company_id",
    )
    def _check_source_options(self):
        relations = (
            ("reporting_for_option_ids", "reporting_for", _("Reporting For")),
            ("rollup_to_option_ids", "rollup_to", _("Rollup To")),
            ("funds_xfer_entity_option_ids", "funds_xfer_entity", _("Funds Xfer Entity")),
        )
        for setup in self:
            for relation, field_name, label in relations:
                options = setup[relation]
                if not options:
                    raise ValidationError(_("Select at least one %s value.") % label)
                if options.filtered(
                    lambda option: option.company_id != setup.company_id
                    or option.field_name != field_name
                ):
                    raise ValidationError(
                        _("%s values must belong to the setup company and correct column.")
                        % label
                    )

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            values["name"] = self._display_name_from_values(values)
        records = super().create(vals_list)
        self.env["bsr.visa.dimension.option"].sync_from_setups(records.mapped("company_id"))
        return records

    def write(self, values):
        companies = self.mapped("company_id")
        label_fields = {"business_owner", "product_type", "card_type"}
        if set(values) & label_fields:
            for setup in self:
                item_values = {
                    field_name: values.get(field_name, setup[field_name])
                    for field_name in label_fields
                }
                super(BsrVisaSetup, setup).write(
                    dict(values, name=self._display_name_from_values(item_values))
                )
            result = True
        else:
            result = super().write(values)
        if set(values) & {"business_owner", "product_type", "card_type", "company_id", "active"}:
            self.env["bsr.visa.dimension.option"].sync_from_setups(
                companies | self.mapped("company_id")
            )
        return result

    def unlink(self):
        companies = self.mapped("company_id")
        result = super().unlink()
        self.env["bsr.visa.dimension.option"].sync_from_setups(companies)
        return result


class BsrAccountingConfigurationGroup(models.Model):
    _name = "bsr.accounting.configuration.group"
    _description = "VISA Configuration Group"
    _order = "sequence, name, id"
    _check_company_auto = True

    name = fields.Char(required=True, index=True)
    sequence = fields.Integer(default=10)
    settlement_currency = fields.Selection(
        [("usd", "USD"), ("bdt", "BDT"), ("all", "ALL")],
        required=True,
        default="all",
        index=True,
    )
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )
    configuration_ids = fields.One2many(
        "bsr.accounting.configuration", "configuration_group_id", string="VISA Configurations"
    )
    configuration_count = fields.Integer(
        compute="_compute_configuration_count", string="Configurations"
    )

    _company_name_unique = models.Constraint(
        "UNIQUE(company_id, name)",
        "A VISA configuration group with this label already exists.",
    )

    @api.depends("configuration_ids")
    def _compute_configuration_count(self):
        for group in self:
            group.configuration_count = len(group.configuration_ids)


class BsrConfigurationGroupWizard(models.TransientModel):
    _name = "bsr.configuration.group.wizard"
    _description = "Manage VISA Configuration Group"

    operation = fields.Selection(
        [("assign", "Assign to Group"), ("remove", "Remove from Group")],
        required=True,
        default="assign",
    )
    configuration_ids = fields.Many2many(
        "bsr.accounting.configuration", string="Selected Configurations", required=True
    )
    company_id = fields.Many2one("res.company", required=True)
    group_id = fields.Many2one(
        "bsr.accounting.configuration.group",
        string="Existing Group",
        domain="[('company_id', '=', company_id)]",
    )
    new_group_name = fields.Char(string="New Group Label")
    settlement_currency = fields.Selection(
        [("usd", "USD"), ("bdt", "BDT"), ("all", "ALL")],
        string="Settlement Currency",
        required=True,
        default="all",
    )

    @api.model
    def default_get(self, field_list):
        values = super().default_get(field_list)
        configurations = self.env["bsr.accounting.configuration"].browse(
            self.env.context.get("active_ids", [])
        ).exists().filtered(lambda item: not item.batch_run_id)
        if configurations:
            companies = configurations.mapped("company_id")
            if len(companies) != 1:
                raise UserError(_("Select configurations from one company only."))
            values.update(
                {
                    "configuration_ids": [(6, 0, configurations.ids)],
                    "company_id": companies.id,
                }
            )
        return values

    @api.onchange("group_id")
    def _onchange_group_id(self):
        if self.group_id:
            self.settlement_currency = self.group_id.settlement_currency

    def action_apply(self):
        self.ensure_one()
        if not self.configuration_ids:
            raise UserError(_("Select at least one VISA configuration."))
        self.configuration_ids.check_access("write")
        if self.operation == "remove":
            self.configuration_ids.write({"configuration_group_id": False})
        else:
            group = self.group_id
            label = _clean(self.new_group_name)
            if label:
                group = self.env["bsr.accounting.configuration.group"].search(
                    [("company_id", "=", self.company_id.id), ("name", "=ilike", label)],
                    limit=1,
                ) or self.env["bsr.accounting.configuration.group"].create(
                    {
                        "name": label,
                        "company_id": self.company_id.id,
                        "settlement_currency": self.settlement_currency,
                    }
                )
            if not group:
                raise UserError(_("Select an existing group or enter a new group label."))
            if group.settlement_currency != self.settlement_currency:
                group.write({"settlement_currency": self.settlement_currency})
            self.configuration_ids.write({"configuration_group_id": group.id})
        return {"type": "ir.actions.client", "tag": "reload"}
