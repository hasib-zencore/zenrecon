# -*- coding: utf-8 -*-
import html

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError


REPORT_SELECTION = [(f"VSS-{code}", f"VSS-{code}") for code in ("110", "120", "130", "140", "210")]
REPORT_CODES = tuple(code for code, _label in REPORT_SELECTION)
LINE_MODEL_BY_REPORT = {
    "VSS-110": "bsr.vss.110.line",
    "VSS-120": "bsr.vss.120.line",
    "VSS-130": "bsr.vss.130.line",
    "VSS-140": "bsr.vss.140.line",
    "VSS-210": "bsr.vss.210.line",
}
FILTER_OPTION_FIELDS = {
    "clearing_currency": ("clearing_currency", "clearing_currency_option_ids"),
    "transaction_type": ("transaction_type", "transaction_type_option_ids"),
    "business_mode": ("business_mode", "business_mode_option_ids"),
    "disposition": ("source_description", "disposition_option_ids"),
    "description": ("description_filter", "description_option_ids"),
    "program_network": ("program_network", "program_network_option_ids"),
    "record_type": ("record_type", "record_type_option_ids"),
    "region_country": ("region_country", "region_country_option_ids"),
    "fee_category": ("fee_category", "fee_category_option_ids"),
    "transaction_category": ("transaction_category", "transaction_category_option_ids"),
    "particulars": ("particulars", "particulars_option_ids"),
    "entity": ("entity", "entity_option_ids"),
}
FILTER_OPERATOR_FIELDS = {
    key: ("disposition_operator" if key == "disposition" else f"{key}_operator")
    for key in FILTER_OPTION_FIELDS
}
FILTER_OPTION_SOURCE_FIELDS = {
    "VSS-110": ("particulars", "entity", "record_type"),
    "VSS-120": ("clearing_currency", "transaction_type", "business_mode", "disposition", "transaction_category"),
    "VSS-130": (
        "transaction_type",
        "business_mode",
        "description",
        "region_country",
        "fee_category",
        "transaction_category",
        "program_network",
        "record_type",
    ),
    "VSS-140": (
        "transaction_type", "business_mode", "transaction_category",
        "description", "program_network", "region_country", "record_type",
    ),
    "VSS-210": (
        "clearing_currency", "transaction_type", "business_mode", "transaction_category",
        "description", "program_network", "record_type",
    ),
}
SOURCE_DIRECTION_SELECTION = [("DB", "DB"), ("DR", "DR (Legacy)"), ("CR", "CR")]
POSTING_SELECTION = [("DR", "DR"), ("CR", "CR")]
CONVERSION_TYPE_SELECTION = [
    ("buy", "Buy Rate"),
    ("sale", "Sale Rate"),
    ("mid", "Mid Rate"),
]
RECORD_TYPE_SELECTION = [("detail", "Detail"), ("total", "Total"), ("net", "Net")]
FILTER_OPERATOR_SELECTION = [
    ("any", "Any"),
    ("blank", "Is blank"),
    ("equals_any", "Equals any of"),
    ("not_blank", "Is not blank"),
    ("not_equals_any", "Not equals any of"),
]
AMOUNT_SOURCE_SELECTION = [
    ("auto", "Automatic (Legacy)"),
    ("total_amount", "Net Settlement Amount"),
    ("debit_amount", "VSS-110 Debit Amount"),
    ("credit_amount", "VSS-110 Credit Amount"),
    ("clearing_amount", "Clearing Amount"),
    ("interchange_amount", "Interchange Amount"),
    ("interchange_credit", "VSS-120 Interchange Credit"),
    ("interchange_debit", "VSS-120 Interchange Debit"),
    ("fee_credit", "Reimbursement Fee Credit"),
    ("fee_debit", "Reimbursement Fee Debit"),
    ("visa_charge_credit", "Visa Charge Credit"),
    ("visa_charge_debit", "Visa Charge Debit"),
    ("settlement_interchange_amount", "Settlement Interchange Amount"),
    ("settlement_conversion_fee", "Settlement Conversion Fee"),
    ("clearing_interchange_amount", "Clearing Interchange Amount"),
    ("clearing_conversion_fee", "Clearing Conversion Fee"),
    ("optional_issuer_fee", "Optional Issuer Fee"),
]
AMOUNT_SOURCE_LABELS = dict(AMOUNT_SOURCE_SELECTION)
AMOUNT_SOURCE_ORDER = tuple(AMOUNT_SOURCE_LABELS)


def _filter_operator_field(label):
    return fields.Selection(
        FILTER_OPERATOR_SELECTION,
        string=f"{label} Match",
        default="equals_any",
        required=True,
        tracking=True,
        help="Choose how this source field is matched. Empty value lists are treated as Any.",
    )


def _filter_options_field(label, relation):
    return fields.Many2many(
        "bsr.accounting.filter.option",
        relation,
        "configuration_id",
        "option_id",
        string=label,
        copy=True,
        tracking=True,
    )


class BsrAccountingFilterOption(models.Model):
    _name = "bsr.accounting.filter.option"
    _description = "Available Accounting Source Filter Value"
    _order = "field_name, is_blank desc, name, id"

    source_import_id = fields.Many2one(
        "bsr.vss.import", required=True, ondelete="cascade", index=True
    )
    report_code_ids = fields.Many2many(
        "bsr.accounting.report.code",
        "bsr_filter_option_report_code_rel",
        "option_id",
        "report_code_id",
        required=True,
    )
    company_id = fields.Many2one(related="source_import_id.company_id", store=True, index=True)
    field_name = fields.Selection(
        [(key, key.replace("_", " ").title()) for key in FILTER_OPTION_FIELDS],
        required=True,
        index=True,
    )
    value = fields.Char()
    value_key = fields.Char(required=True, index=True)
    name = fields.Char(required=True, index=True)
    is_blank = fields.Boolean(default=False, index=True)

    _source_field_value_unique = models.Constraint(
        "UNIQUE(source_import_id, field_name, value_key)",
        "Each source filter value must be unique within its processed file.",
    )


def _posting_indicator_from_source(
    report_code, record_type, particulars, entity, amount_source, source_direction
):
    """Default posting side from VSS; only Net Settlement Total Amount is reversed."""
    normalized = str(source_direction or "").upper()
    if normalized not in {"DB", "DR", "CR"}:
        return False
    is_debit = normalized in {"DB", "DR"}
    normalized_particulars = str(particulars or "TOTAL").strip().lower()
    normalized_entity = str(entity or "").strip().lower()
    is_net_settlement = (
        report_code == "VSS-110"
        and record_type == "net"
        and normalized_particulars == "total"
        and normalized_entity == "net settlement amount"
        and amount_source == "total_amount"
    )
    if is_net_settlement:
        return "CR" if is_debit else "DR"
    return "DR" if is_debit else "CR"


class BsrAccountingReportCode(models.Model):
    _name = "bsr.accounting.report.code"
    _description = "Selectable VSS Report ID"
    _rec_name = "code"
    _order = "sequence, id"

    code = fields.Selection(REPORT_SELECTION, required=True, index=True)
    sequence = fields.Integer(required=True)


class BsrAccountingConfiguration(models.Model):
    _name = "bsr.accounting.configuration"
    _description = "Bank Reconciliation Voucher Configuration"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc, id desc"
    _check_company_auto = True

    name = fields.Char(default=lambda self: _("New"), required=True, copy=False, tracking=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True, tracking=True
    )
    configuration_group_id = fields.Many2one(
        "bsr.accounting.configuration.group",
        string="Voucher Group",
        ondelete="set null",
        index=True,
        check_company=True,
        tracking=True,
        help="Execution group used by Voucher Runs. ALL makes the group available to USD and BDT runs but never overrides this configuration's own settlement currency.",
    )
    source_import_id = fields.Many2one(
        "bsr.vss.import",
        string="Processed VSS File",
        required=True,
        index=True,
        ondelete="restrict",
        check_company=True,
        domain="[('company_id', '=', company_id), ('state', 'in', ('completed', 'partial'))]",
        tracking=True,
    )
    # Kept only for database compatibility with configurations created by the
    # earlier single-report prototype. It is not part of the user workflow.
    report_code = fields.Selection(
        REPORT_SELECTION, string="Reference Report ID", required=True, default="VSS-120", index=True, tracking=True
    )
    report_code_ids = fields.Many2many(
        "bsr.accounting.report.code",
        "bsr_accounting_config_report_code_rel",
        "configuration_id",
        "report_code_id",
        string="Report ID",
        help="Select one or more report types present in the processed VSS file.",
    )
    available_report_code_ids = fields.Many2many(
        "bsr.accounting.report.code",
        compute="_compute_available_report_code_ids",
        string="Available Report IDs",
    )
    # Retained as an audit/search value and for older configurations. The
    # multi-select field above is the only editable report selection.
    report_id_filter = fields.Char(string="Selected Report IDs", readonly=True, copy=False, index=True)
    # Deprecated compatibility fields. The complete parsed file is scanned
    # automatically; users no longer select individual VSS reports.
    use_vss_110 = fields.Boolean(default=True)
    use_vss_120 = fields.Boolean(default=True)
    use_vss_130 = fields.Boolean(default=True)
    use_vss_140 = fields.Boolean(default=False)
    use_vss_210 = fields.Boolean(default=False)
    source_report_codes = fields.Char(string="Source Report IDs", compute="_compute_source_report_codes", store=True)
    production_date = fields.Date(string="PROC Date", index=True, tracking=True)
    report_date = fields.Date(index=True, tracking=True)

    business_owner = fields.Char(required=True, tracking=True)
    product_type = fields.Char(required=True, index=True, tracking=True)
    reporting_for = fields.Char(required=True, index=True, tracking=True)
    rollup_to = fields.Char(index=True, tracking=True)
    funds_xfer_entity = fields.Char(string="Funds Xfer Entity", index=True, tracking=True)
    settlement_currency = fields.Char(required=True, index=True, tracking=True)
    conversion_type = fields.Selection(
       CONVERSION_TYPE_SELECTION, string="Legacy Conversion Type", default="mid", required=True, tracking=True,
       help="Rate used to convert USD amounts to BDT in voucher runs.")
    clearing_currency = fields.Char(
        index=True,
        tracking=True,
        help="Exact Clearing Currency filter. Separate multiple values with commas.",
    )
    clearing_currency_operator = _filter_operator_field("Clearing Currency")
    business_mode = fields.Char(
        index=True,
        tracking=True,
        help="Exact Business Mode filter. Separate multiple values with commas.",
    )
    business_mode_operator = _filter_operator_field("Business Mode")
    transaction_category = fields.Char(
        index=True,
        tracking=True,
        help="Exact Transaction Category filter. Separate multiple values with commas.",
    )
    transaction_category_operator = _filter_operator_field("Transaction Category")
    transaction_type = fields.Char(
        index=True,
        tracking=True,
        help="Exact Transaction Type filter. Separate multiple values with commas.",
    )
    transaction_type_operator = _filter_operator_field("Transaction Type")
    vss_120_source_level = fields.Selection(
        RECORD_TYPE_SELECTION,
        string="VSS-120 Source Level",
        tracking=True,
        help="Select exactly one VSS-120 hierarchy level to prevent Detail, Total and Net amounts from overlapping.",
    )
    source_description = fields.Char(
        string="Disposition",
        index=True,
        tracking=True,
        help="Exact VSS disposition filter. Separate multiple values with commas. Reports without a disposition column ignore it.",
    )
    disposition_operator = _filter_operator_field("Disposition")
    description_filter = fields.Char(
        string="Description",
        index=True,
        tracking=True,
        help="Exact VSS description filter. Separate multiple values with commas. Reports without a description column ignore it.",
    )
    description_operator = _filter_operator_field("Description")
    program_network = fields.Char(
        string="Program Network", index=True, tracking=True,
        help="Exact source program/network filter. Select one or more source values.",
    )
    program_network_operator = _filter_operator_field("Program Network")
    record_type = fields.Char(
        string="Record Type", index=True, tracking=True,
        help="Exact source record type filter. Select one or more source values.",
    )
    record_type_operator = _filter_operator_field("Record Type")

    region_country = fields.Char(
        string="Region Country",
        index=True,
        tracking=True,
        help="Exact VSS-130 region/country filter. Select one or more source values.",
    )
    region_country_operator = _filter_operator_field("Region Country")
    fee_category = fields.Char(
        string="Fee Category",
        index=True,
        tracking=True,
        help="Exact VSS-130 fee category filter. Select one or more source values.",
    )
    fee_category_operator = _filter_operator_field("Fee Category")
    show_vss_110_amounts = fields.Boolean(compute="_compute_amount_sections")
    show_vss_120_amounts = fields.Boolean(compute="_compute_amount_sections")
    show_vss_130_amounts = fields.Boolean(compute="_compute_amount_sections")
    show_vss_140_amounts = fields.Boolean(compute="_compute_amount_sections")
    show_vss_210_amounts = fields.Boolean(compute="_compute_amount_sections")
    amount_vss_110_credit = fields.Boolean(string="Credit Amount", default=True, tracking=True)
    amount_vss_110_debit = fields.Boolean(string="Debit Amount", default=True, tracking=True)
    amount_vss_110_total = fields.Boolean(string="Total Amount", default=True, tracking=True)
    amount_vss_120_clearing = fields.Boolean(string="Clearing Amount", default=True, tracking=True)
    amount_vss_120_interchange_credit = fields.Boolean(string="Interchange Credit", default=True, tracking=True)
    amount_vss_120_interchange_debit = fields.Boolean(string="Interchange Debit", default=True, tracking=True)
    amount_vss_130_interchange = fields.Boolean(string="Interchange Amount", default=True, tracking=True)
    amount_vss_130_fee_credit = fields.Boolean(string="Reimbursement Fee Credit", default=True, tracking=True)
    amount_vss_130_fee_debit = fields.Boolean(string="Reimbursement Fee Debit", default=True, tracking=True)
    amount_vss_140_charge_credit = fields.Boolean(string="Visa Charge Credit", default=True, tracking=True)
    amount_vss_140_charge_debit = fields.Boolean(string="Visa Charge Debit", default=True, tracking=True)
    amount_vss_210_settlement_interchange = fields.Boolean(
        string="Settlement Interchange Amount", default=True, tracking=True
    )
    amount_vss_210_settlement_conversion = fields.Boolean(
        string="Settlement Conversion Fee", default=True, tracking=True
    )
    amount_vss_210_clearing_interchange = fields.Boolean(
        string="Clearing Interchange Amount", default=True, tracking=True
    )
    amount_vss_210_clearing_conversion = fields.Boolean(
        string="Clearing Conversion Fee", default=True, tracking=True
    )
    amount_vss_210_optional_issuer = fields.Boolean(string="Optional Issuer Fee", default=True, tracking=True)
    particulars = fields.Char(
        index=True,
        tracking=True,
        help="Exact VSS-110 Particulars filter. Separate multiple values with commas.",
    )
    particulars_operator = _filter_operator_field("Particulars")
    entity = fields.Char(
        index=True,
        tracking=True,
        help="Exact VSS-110 Entity filter. Separate multiple values with commas.",
    )
    entity_operator = _filter_operator_field("Entity")
    clearing_currency_option_ids = _filter_options_field(
        "Clearing Currency", "bsr_config_clearing_currency_option_rel"
    )
    transaction_type_option_ids = _filter_options_field(
        "Transaction Type", "bsr_config_transaction_type_option_rel"
    )
    business_mode_option_ids = _filter_options_field(
        "Business Mode", "bsr_config_business_mode_option_rel"
    )
    disposition_option_ids = _filter_options_field(
        "Disposition", "bsr_config_disposition_option_rel"
    )
    description_option_ids = _filter_options_field(
        "Description", "bsr_config_description_option_rel"
    )
    program_network_option_ids = _filter_options_field(
        "Program Network", "bsr_config_program_network_option_rel"
    )
    record_type_option_ids = _filter_options_field(
        "Record Type", "bsr_config_record_type_option_rel"
    )
    region_country_option_ids = _filter_options_field(

        "Region Country", "bsr_config_region_country_option_rel"
    )
    fee_category_option_ids = _filter_options_field(
        "Fee Category", "bsr_config_fee_category_option_rel"
    )
    transaction_category_option_ids = _filter_options_field(
        "Transaction Category", "bsr_config_transaction_category_option_rel"
    )
    particulars_option_ids = _filter_options_field(
        "Particulars", "bsr_config_particulars_option_rel"
    )
    entity_option_ids = _filter_options_field(
        "Entity", "bsr_config_entity_option_rel"
    )
    posting_date = fields.Date(required=True, default=fields.Date.context_today, tracking=True)
    remarks = fields.Text(help="General remarks printed on the voucher report.")

    line_ids = fields.One2many(
        "bsr.accounting.mapping", "configuration_id", string="Matched Configuration Lines", copy=True
    )
    previous_same_report_line_ids = fields.Many2many(
        "bsr.accounting.mapping",
        "bsr_config_previous_mapping_rel",
        "configuration_id",
        "mapping_id",
        string="Legacy Displayed Rules",
        copy=False,
        check_company=True,
        help="Compatibility field for older installations. The form displays only this configuration's own rules.",
    )
    report_ids = fields.One2many("bsr.accounting.report", "configuration_id", string="Generated Reports")
    template_id = fields.Many2one(
        "bsr.accounting.configuration", string="Source Configuration", readonly=True, copy=False, index=True
    )
    batch_run_id = fields.Many2one(
        "bsr.accounting.run", string="Configuration Run", readonly=True, copy=False, index=True, ondelete="cascade"
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("matched", "Source Matched"),
            ("ready", "Ready"),
            ("no_activity", "No Activity"),
            ("blocked", "Skipped — Blocking Issue"),
            ("validated", "Legacy Validated"),
            ("active", "Legacy Active"),
            ("archived", "Legacy Archived"),
        ],
        default="draft",
        required=True,
        tracking=True,
        index=True,
    )
    source_row_count = fields.Integer(compute="_compute_counts")
    rule_count = fields.Integer(compute="_compute_counts")
    configured_count = fields.Integer(compute="_compute_counts")
    incomplete_count = fields.Integer(compute="_compute_counts")
    preview_debit_total = fields.Float(compute="_compute_preview_totals", digits=(20, 2))
    preview_credit_total = fields.Float(compute="_compute_preview_totals", digits=(20, 2))
    preview_difference = fields.Float(compute="_compute_preview_totals", digits=(20, 2))
    is_preview_balanced = fields.Boolean(compute="_compute_preview_totals")
    show_usd_amount = fields.Boolean(compute="_compute_show_usd_amount")
    show_currency_columns = fields.Boolean(compute="_compute_show_currency_columns")
    amount_summary_html = fields.Html(compute="_compute_amount_summary_html", sanitize=False)
    for _amount_code, _amount_label in AMOUNT_SOURCE_SELECTION:
        locals()[f"show_amount_column_{_amount_code}"] = fields.Boolean(
            compute="_compute_amount_column_visibility"
        )
    validation_message = fields.Text(readonly=True)
    matched_at = fields.Datetime(readonly=True)
    matched_by_id = fields.Many2one("res.users", readonly=True)

    @api.depends(
        "settlement_currency",
        "clearing_currency",
        "line_ids.source_currency",
        "line_ids.clearing_currency",
    )
    def _compute_show_usd_amount(self):
        for record in self:
            currencies = {
                self._norm(value).upper()
                for value in (
                    record.settlement_currency,
                    record.clearing_currency,
                    *record.line_ids.mapped("source_currency"),
                    *record.line_ids.mapped("clearing_currency"),
                )
                if self._norm(value)
            }
            record.show_usd_amount = {"BDT", "USD"}.issubset(currencies)

    @api.depends(
        "settlement_currency",
        "clearing_currency",
        "line_ids.source_currency",
        "line_ids.clearing_currency",
    )
    def _compute_show_currency_columns(self):
        for record in self:
            currencies = {
                self._norm(value).upper()
                for value in (
                    record.settlement_currency,
                    record.clearing_currency,
                    *record.line_ids.mapped("source_currency"),
                    *record.line_ids.mapped("clearing_currency"),
                )
                if self._norm(value)
            }
            record.show_currency_columns = {"BDT", "USD"}.issubset(currencies)

    @api.depends(
        "line_ids.amount_source",
        "line_ids.matched_amount",
        "line_ids.amount_columns_json",
        "line_ids.debit_amount",
        "line_ids.credit_amount",
        "line_ids.posting_indicator",
        "line_ids.gl_number",
        "line_ids.gl_name",
        "line_ids.report_code",
        "line_ids.record_type",
        "line_ids.business_mode",
        "line_ids.transaction_category",
        "line_ids.transaction_type",
        "line_ids.description_match",
        "line_ids.source_currency",
    )
    def _compute_amount_summary_html(self):
        for record in self:
            lines = record.line_ids.sorted("sequence")
            additional_sources = []
            for line in lines:
                for source in (line.amount_columns_json or {}):
                    if source not in additional_sources:
                        additional_sources.append(source)
            additional_sources.sort(
                key=lambda source: (
                    AMOUNT_SOURCE_ORDER.index(source)
                    if source in AMOUNT_SOURCE_ORDER
                    else len(AMOUNT_SOURCE_ORDER),
                    source,
                )
            )
            if not additional_sources:
                record.amount_summary_html = False
                continue
            groups = {}
            for line in lines:
                key = (
                    line.report_code,
                    line.record_type,
                    line.business_mode,
                    line.transaction_category,
                    line.transaction_type,
                    line.description_match,
                    line.source_currency,
                )
                group = groups.setdefault(
                    key,
                    {
                        "line": line,
                        "primary": 0.0,
                        "debit": 0.0,
                        "credit": 0.0,
                        "additional": {},
                    },
                )
                group["primary"] += line.matched_amount
                group["debit"] += line.debit_amount
                group["credit"] += line.credit_amount
                for source, value in (line.amount_columns_json or {}).items():
                    group["additional"][source] = group["additional"].get(source, 0.0) + (value or 0.0)
            primary_sources = list(dict.fromkeys(line.amount_source for line in lines if line.amount_source))
            primary_source = primary_sources[0] if len(primary_sources) == 1 else "matched_amount"
            primary_label = (
                AMOUNT_SOURCE_LABELS.get(primary_source, primary_source)
                if primary_source != "matched_amount"
                else "Accounting Amount"
            )
            header_cells = "".join(
                f"<th>{html.escape(AMOUNT_SOURCE_LABELS.get(source, source))}</th>"
                for source in additional_sources
            )
            body_rows = []
            for group in groups.values():
                line = group["line"]
                cells = [
                    line.report_code,
                    line.record_type.title(),
                    line.business_mode,
                    line.transaction_type,
                    line.description_match,
                ]
                cells_html = "".join(f"<td>{html.escape(str(value or ''))}</td>" for value in cells)
                accounting_cells = "".join(
                    (
                        f'<td class="text-end">{group["primary"]:,.2f}</td>'
                        f'<td class="text-end">{group["debit"]:,.2f}</td>'
                        f'<td class="text-end">{group["credit"]:,.2f}</td>'
                        f"<td>{html.escape(line.posting_indicator or '')}</td>"
                        f"<td>{html.escape(line.gl_number or '')}</td>"
                        f"<td>{html.escape(line.gl_name or '')}</td>"
                    )
                )
                amount_cells = "".join(
                    f"<td class=\"text-end\">{group['additional'].get(source, 0.0):,.2f}</td>"
                    for source in additional_sources
                )
                body_rows.append(f"<tr>{cells_html}{accounting_cells}{amount_cells}</tr>")
            record.amount_summary_html = (
                '<div class="o_bsr_amount_summary">'
                '<div class="o_bsr_amount_summary_title">Selected amount summary — '
                f"Primary: {html.escape(primary_label)}</div>"
                '<table class="table table-sm table-hover o_bsr_amount_summary_table">'
                '<thead><tr><th>VSS Source</th><th>Level</th><th>Mode</th>'
                '<th>Transaction Type</th><th>Source Description</th>'
                f"<th>{html.escape(primary_label)}</th>"
                '<th>Debit</th><th>Credit</th><th>DR/CR</th><th>GL Number</th><th>GL Name</th>'
                f"{header_cells}</tr></thead><tbody>{''.join(body_rows)}</tbody></table></div>"
            )

    @api.depends("line_ids.amount_columns_json")
    def _compute_amount_column_visibility(self):
        for record in self:
            selected = {
                source
                for line in record.line_ids
                for source in (line.amount_columns_json or {})
            }
            for source, _label in AMOUNT_SOURCE_SELECTION:
                record[f"show_amount_column_{source}"] = source in selected

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            if not values.get("name") or values.get("name") == _("New"):
                values["name"] = self.env["ir.sequence"].next_by_code("bsr.accounting.configuration") or _("New")
        records = super().create(vals_list)
        records._sync_report_id_filter()
        records._ensure_filter_option_catalog()
        records._adopt_legacy_filter_options()
        standalone = records.filtered(lambda record: not record.batch_run_id)
        if standalone:
            self.env["bsr.visa.source.option"].sync_from_configurations(
                standalone.mapped("company_id")
            )
        return records

    def action_open_configuration_group_wizard(self):
        configurations = self.filtered(lambda item: not item.batch_run_id)
        if not configurations:
            raise UserError(_("Select at least one standalone VISA configuration."))
        companies = configurations.mapped("company_id")
        if len(companies) != 1:
            raise UserError(_("Select configurations from one company only."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Manage VISA Group"),
            "res_model": "bsr.configuration.group.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_configuration_ids": [(6, 0, configurations.ids)],
                "default_company_id": companies.id,
            },
        }

    def write(self, values):
        identity_changed = bool(
            set(values)
            & {"reporting_for", "rollup_to", "funds_xfer_entity", "company_id", "batch_run_id"}
        )
        previous_companies = self.mapped("company_id") if identity_changed else self.env["res.company"]
        option_keys = {
            key for key, (_legacy, option_field) in FILTER_OPTION_FIELDS.items() if option_field in values
        }
        legacy_keys = {
            key
            for key, (legacy_field, _option) in FILTER_OPTION_FIELDS.items()
            if legacy_field in values or FILTER_OPERATOR_FIELDS[key] in values
        }
        result = super().write(values)
        if "report_code_ids" in values:
            self._sync_report_id_filter()
        if "source_import_id" in values:
            self._ensure_filter_option_catalog()
            super(BsrAccountingConfiguration, self).write(
                {option_field: [(5, 0, 0)] for _legacy, option_field in FILTER_OPTION_FIELDS.values()}
            )
            self._adopt_legacy_filter_options()
        elif option_keys:
            self._sync_legacy_filter_values(option_keys)
        elif legacy_keys:
            super(BsrAccountingConfiguration, self).write(
                {FILTER_OPTION_FIELDS[key][1]: [(5, 0, 0)] for key in legacy_keys}
            )
            self._adopt_legacy_filter_options(legacy_keys)
        if identity_changed:
            self.env["bsr.visa.source.option"].sync_from_configurations(
                previous_companies | self.mapped("company_id")
            )
        return result

    def unlink(self):
        companies = self.filtered(lambda record: not record.batch_run_id).mapped("company_id")
        result = super().unlink()
        if companies:
            self.env["bsr.visa.source.option"].sync_from_configurations(companies)
        return result

    def _ensure_filter_option_catalog(self):
        """Build reusable source-value choices once per processed file."""
        Option = self.env["bsr.accounting.filter.option"].sudo()
        report_options = {
            option.code: option for option in self.env["bsr.accounting.report.code"].sudo().search([])
        }
        for source_import in self.mapped("source_import_id"):
            existing = Option.search([("source_import_id", "=", source_import.id)])
            known = {(option.field_name, option.value_key): option for option in existing}
            values_by_field = {key: {} for key in FILTER_OPTION_FIELDS}
            reports_by_field = {key: set() for key in FILTER_OPTION_FIELDS}
            for report_code, source_fields in FILTER_OPTION_SOURCE_FIELDS.items():
                model = self.env[LINE_MODEL_BY_REPORT[report_code]].sudo()
                lines = model.search([("import_id", "=", source_import.id)])
                report_option = report_options.get(report_code)
                if not lines or not report_option:
                    continue
                for field_name in source_fields:
                    reports_by_field[field_name].add(report_option.id)
                    for value in lines.mapped(field_name):
                        cleaned = " ".join(str(value or "").strip().split())
                        if cleaned:
                            value_key = self._norm(cleaned)
                            entry = values_by_field[field_name].setdefault(
                                value_key, {"value": cleaned, "report_ids": set()}
                            )
                            entry["report_ids"].add(report_option.id)

            create_values = []
            for field_name, source_values in values_by_field.items():
                blank_key = (field_name, "__blank__")
                if reports_by_field[field_name] and blank_key not in known:
                    create_values.append(
                        {
                            "source_import_id": source_import.id,
                            "report_code_ids": [(6, 0, sorted(reports_by_field[field_name]))],
                            "field_name": field_name,
                            "value_key": "__blank__",
                            "name": _("(Blank)"),
                            "is_blank": True,
                        }
                    )
                elif blank_key in known:
                    known[blank_key].report_code_ids = [(4, report_id) for report_id in reports_by_field[field_name]]
                for value_key, entry in sorted(source_values.items()):
                    option_key = (field_name, value_key)
                    if option_key not in known:
                        create_values.append(
                            {
                                "source_import_id": source_import.id,
                                "report_code_ids": [(6, 0, sorted(entry["report_ids"]))],
                                "field_name": field_name,
                                "value": entry["value"],
                                "value_key": value_key,
                                "name": entry["value"],
                            }
                        )
                    else:
                        known[option_key].report_code_ids = [
                            (4, report_id) for report_id in entry["report_ids"]
                        ]
            if create_values:
                Option.create(create_values)

    def _adopt_legacy_filter_options(self, filter_keys=None):
        """Represent existing text/operator filters as tags when possible."""
        selected_keys = set(filter_keys or FILTER_OPTION_FIELDS)
        Option = self.env["bsr.accounting.filter.option"].sudo()
        for record in self.filtered("source_import_id"):
            updates = {}
            for key in selected_keys:
                legacy_field, option_field = FILTER_OPTION_FIELDS[key]
                if record[option_field]:
                    continue
                operator = record[FILTER_OPERATOR_FIELDS[key]] or "equals_any"
                if operator == "blank":
                    wanted = {"__blank__"}
                elif operator == "equals_any":
                    wanted = {record._norm(value) for value in record._split_manual_values(record[legacy_field])}
                    if "(blank)" in wanted:
                        wanted.remove("(blank)")
                        wanted.add("__blank__")
                else:
                    continue
                if not wanted:
                    continue
                options = Option.search(
                    [
                        ("source_import_id", "=", record.source_import_id.id),
                        ("field_name", "=", key),
                        ("value_key", "in", list(wanted)),
                    ]
                )
                if options:
                    updates[option_field] = [(6, 0, options.ids)]
            if updates:
                super(BsrAccountingConfiguration, record).write(updates)

    def _sync_legacy_filter_values(self, filter_keys):
        """Keep audit exports and older integrations readable after tag edits."""
        for record in self:
            updates = {}
            for key in filter_keys:
                legacy_field, option_field = FILTER_OPTION_FIELDS[key]
                options = record[option_field]
                values = options.filtered(lambda option: not option.is_blank).mapped("value")
                has_blank = bool(options.filtered("is_blank"))
                display_values = ([_("(Blank)")] if has_blank else []) + sorted(values, key=str.casefold)
                updates[legacy_field] = ", ".join(display_values) or False
                updates[FILTER_OPERATOR_FIELDS[key]] = (
                    "any" if not options else "blank" if has_blank and not values else "equals_any"
                )
            super(BsrAccountingConfiguration, record).write(updates)

    def _sync_report_id_filter(self):
        for record in self:
            selected = set(record.report_code_ids.mapped("code"))
            value = ", ".join(code for code in REPORT_CODES if code in selected)
            if record.report_id_filter != value:
                super(BsrAccountingConfiguration, record).write({"report_id_filter": value or False})

    @api.depends("source_import_id")
    def _compute_available_report_code_ids(self):
        options = self.env["bsr.accounting.report.code"].search([])
        for record in self:
            if not record.source_import_id:
                record.available_report_code_ids = False
                continue
            available = options.filtered(
                lambda option: bool(
                    self.env[LINE_MODEL_BY_REPORT[option.code]].search_count(
                        [("import_id", "=", record.source_import_id.id)], limit=1
                    )
                )
            )
            record.available_report_code_ids = available

    @api.depends("line_ids.report_code")
    def _compute_source_report_codes(self):
        for record in self:
            used = set(record.line_ids.mapped("report_code"))
            record.source_report_codes = ", ".join(code for code, _label in REPORT_SELECTION if code in used)

    @api.depends("report_code_ids")
    def _compute_amount_sections(self):
        for record in self:
            selected = set(record.report_code_ids.mapped("code"))
            record.show_vss_110_amounts = "VSS-110" in selected
            record.show_vss_120_amounts = "VSS-120" in selected
            record.show_vss_130_amounts = "VSS-130" in selected
            record.show_vss_140_amounts = "VSS-140" in selected
            record.show_vss_210_amounts = "VSS-210" in selected

    @staticmethod
    def _split_manual_values(value):
        if not value:
            return []
        normalized = str(value).replace("\n", ",").replace(";", ",").replace("|", ",")
        return [item.strip() for item in normalized.split(",") if item.strip()]

    def _report_codes_to_scan(self):
        """Return selected reports in the standard source order."""
        self.ensure_one()
        selected = set(self.report_code_ids.mapped("code"))
        return [code for code in REPORT_CODES if code in selected]

    @api.constrains("report_code_ids", "source_import_id")
    def _check_selected_report_codes(self):
        for record in self:
            if not record.source_import_id or not record.report_code_ids:
                continue
            available = set(record.available_report_code_ids.mapped("code"))
            invalid = sorted(set(record.report_code_ids.mapped("code")) - available)
            if invalid:
                raise ValidationError(
                    _("Report ID(s) %(codes)s are not present in the selected processed VSS file.")
                    % {"codes": ", ".join(invalid)}
                )

    @api.depends(
        "line_ids",
        "line_ids.configuration_status",
        "line_ids.source_row_count",
        "line_ids.include_in_voucher",
    )
    def _compute_counts(self):
        for record in self:
            included = record.line_ids.filtered("include_in_voucher")
            record.rule_count = len(included)
            record.source_row_count = sum(included.mapped("source_row_count"))
            record.configured_count = len(included.filtered(lambda line: line.configuration_status == "configured"))
            record.incomplete_count = len(included.filtered(lambda line: line.configuration_status == "incomplete"))

    @api.depends("line_ids.matched_amount", "line_ids.posting_indicator", "line_ids.include_in_voucher")
    def _compute_preview_totals(self):
        for record in self:
            lines = record.line_ids.filtered("include_in_voucher")
            debit = sum(lines.filtered(lambda line: line.posting_indicator == "DR").mapped("matched_amount"))
            credit = sum(lines.filtered(lambda line: line.posting_indicator == "CR").mapped("matched_amount"))
            record.preview_debit_total = debit
            record.preview_credit_total = credit
            record.preview_difference = abs(debit - credit)
            record.is_preview_balanced = bool(lines) and abs(debit - credit) < 0.005

    @staticmethod
    def _norm(value):
        return " ".join(str(value or "").strip().casefold().split())

    @staticmethod
    def _source_description(report_code, line):
        candidates = {
            "VSS-110": ("entity", "particulars"),
            "VSS-120": ("disposition", "transaction_type"),
            "VSS-130": ("description",),
            "VSS-140": ("description",),
            "VSS-210": ("description",),
        }
        return next(
            (line[field] for field in candidates.get(report_code, ()) if field in line._fields and line[field]),
            "",
        )

    def _source_amount_fields(self, report_code, line):
        """Return enabled source amount fields in their configured display order.

        Compatible currency-pair fields from the same source row remain on one
        accounting rule. Other selected amounts retain independent GL rules.
        """
        fixed = {
            "VSS-120": (
                ("clearing_amount", "clearing_direction"),
                ("interchange_credit", "CR"),
                ("interchange_debit", "DB"),
            ),
            "VSS-130": (
                ("interchange_amount", "interchange_direction"),
                ("fee_credit", "CR"),
                ("fee_debit", "DB"),
            ),
            "VSS-140": (("visa_charge_credit", "CR"), ("visa_charge_debit", "DB")),
            "VSS-210": (
                ("settlement_interchange_amount", "settlement_interchange_direction"),
                ("settlement_conversion_fee", "settlement_interchange_direction"),
                ("clearing_interchange_amount", "clearing_interchange_direction"),
                ("clearing_conversion_fee", "clearing_interchange_direction"),
                ("optional_issuer_fee", "optional_issuer_fee_direction"),
            ),
        }
        amount_fields = fixed.get(report_code, ())
        if report_code == "VSS-130" and "VSS-120" in self._report_codes_to_scan():
            # VSS-130 repeats the interchange value reported by VSS-120.
            # When both reports are selected, VSS-120 owns interchange and
            # VSS-130 contributes reimbursement fees only.
            amount_fields = (("fee_credit", "CR"), ("fee_debit", "DB"))
        if report_code == "VSS-110":
            is_net_settlement = (
                self._norm(line.record_type) == "net"
                and self._norm(line.particulars or "TOTAL") == "total"
                and self._norm(line.entity) == "net settlement amount"
            )
            is_section_total = self._norm(line.record_type) == "total"
            is_interchange = self._norm(line.particulars) == "interchange value"
            if is_net_settlement or (is_section_total and not is_interchange):
                amount_fields = (("total_amount", "direction"),)
            else:
                amount_fields = (("debit_amount", "DB"), ("credit_amount", "CR"))
        enabled_fields = {
            "VSS-110": {
                "credit_amount": self.amount_vss_110_credit,
                "debit_amount": self.amount_vss_110_debit,
                "total_amount": self.amount_vss_110_total,
            },
            "VSS-120": {
                "clearing_amount": self.amount_vss_120_clearing,
                "interchange_credit": self.amount_vss_120_interchange_credit,
                "interchange_debit": self.amount_vss_120_interchange_debit,
            },
            "VSS-130": {
                "interchange_amount": self.amount_vss_130_interchange,
                "fee_credit": self.amount_vss_130_fee_credit,
                "fee_debit": self.amount_vss_130_fee_debit,
            },
            "VSS-140": {
                "visa_charge_credit": self.amount_vss_140_charge_credit,
                "visa_charge_debit": self.amount_vss_140_charge_debit,
            },
            "VSS-210": {
                "settlement_interchange_amount": self.amount_vss_210_settlement_interchange,
                "settlement_conversion_fee": self.amount_vss_210_settlement_conversion,
                "clearing_interchange_amount": self.amount_vss_210_clearing_interchange,
                "clearing_conversion_fee": self.amount_vss_210_clearing_conversion,
                "optional_issuer_fee": self.amount_vss_210_optional_issuer,
            },
        }.get(report_code, {})
        return tuple(
            (amount_field, direction_source)
            for amount_field, direction_source in amount_fields
            if enabled_fields.get(amount_field, True)
        )

    def _source_variants(self, report_code, line):
        """Return every enabled accounting amount from an eligible source row."""
        amount_fields = self._source_amount_fields(report_code, line)
        variants = []
        for amount_field, direction_source in amount_fields:
            if amount_field not in line._fields or not line[amount_field]:
                continue
            raw_direction = direction_source if direction_source in {"CR", "DB"} else line[direction_source]
            normalized = str(raw_direction or "").upper()
            direction = "DB" if normalized in {"DB", "DR", "DEBIT"} else "CR" if normalized in {"CR", "CREDIT"} else False
            if direction:
                variants.append((direction, amount_field, abs(line[amount_field])))
        return variants

    @staticmethod
    def _source_variant_groups(report_code, variants, posting_by_field):
        """Keep contractual currency pairs on one GL rule.

        Pairing is deliberately narrow: fields must come from the same parsed
        row and resolve to the same posting side. Opposite-side or unrelated
        amounts remain independent accounting rules.
        """
        pair_fields = {
            "VSS-120": {
                "clearing_amount": {
                    "DR": "interchange_debit",
                    "CR": "interchange_credit",
                },
            },
            "VSS-210": {
                "settlement_interchange_amount": {
                    "DR": "clearing_interchange_amount",
                    "CR": "clearing_interchange_amount",
                },
                "settlement_conversion_fee": {
                    "DR": "clearing_conversion_fee",
                    "CR": "clearing_conversion_fee",
                },
            },
        }.get(report_code, {})
        by_field = {
            amount_source: (source_direction, amount_source, amount)
            for source_direction, amount_source, amount in variants
        }
        consumed = set()
        groups = []
        for source_direction, amount_source, amount in variants:
            if amount_source in consumed:
                continue
            posting_indicator = posting_by_field[amount_source]
            additional_amounts = {}
            pair_field = pair_fields.get(amount_source, {}).get(posting_indicator)
            pair = by_field.get(pair_field)
            if pair and posting_by_field.get(pair_field) == posting_indicator:
                additional_amounts[pair_field] = pair[2]
                consumed.add(pair_field)
            consumed.add(amount_source)
            groups.append((source_direction, amount_source, amount, additional_amounts))
        return groups

    def _source_currency(self, report_code, line, amount_source):
        """Identify the currency of every source amount without converting it."""
        self.ensure_one()
        clearing_currency = line["clearing_currency"] if "clearing_currency" in line._fields else ""
        if report_code == "VSS-120" and amount_source == "clearing_amount":
            return clearing_currency or line.settlement_currency
        if report_code == "VSS-210" and amount_source in {
            "clearing_interchange_amount",
            "clearing_conversion_fee",
            "optional_issuer_fee",
        }:
            return clearing_currency or line.settlement_currency
        return line.settlement_currency

    def _usd_amount(self, report_code, line, amount_source, amount, source_currency):
        """Return the informational USD value without changing posting amount."""
        if not self.show_usd_amount or not amount:
            return 0.0
        settlement = self._norm(self.settlement_currency).upper()
        if report_code == "VSS-130":
            return abs(line.interchange_amount or 0.0) if amount_source == "interchange_amount" and settlement == "USD" else 0.0
        if report_code == "VSS-140":
            return abs(line.interchange_amount or 0.0) if settlement == "USD" else 0.0
        if report_code == "VSS-110" and settlement == "USD":
            return amount
        return amount if self._norm(source_currency).upper() == "USD" else 0.0

    def _is_accounting_source_row(self, report_code, line):
        """Choose one hierarchy level so detail, total and net never overlap."""
        record_type = line.record_type
        description = self._norm(self._source_description(report_code, line))
        mode = self._norm(line["business_mode"] if "business_mode" in line._fields else "")
        if report_code == "VSS-110":
            # Explicit VSS-110 filters select their requested row/summary.
            has_particulars = self._source_filter_is_active("particulars")
            has_entity = self._source_filter_is_active("entity")
            if has_particulars and has_entity:
                return True
            if has_entity:
                return True
            if has_particulars:
                return record_type in {"total", "net"}

            # Without VSS-110 row filters, use section totals as fallbacks.
            # A more detailed selected VSS report owns the same amount when
            # available, preventing duplicate posting across report IDs.
            selected_reports = set(self._report_codes_to_scan())
            particulars = self._norm(line.particulars)
            if record_type == "net" and description == "net settlement amount":
                return True
            if record_type != "total":
                return False
            detailed_source = {
                "interchange value": "VSS-120",
                "reimbursement fees": "VSS-130",
                "visa charges": "VSS-140",
            }.get(particulars)
            return bool(detailed_source and detailed_source not in selected_reports)
        if report_code == "VSS-120":
            return record_type == (self.vss_120_source_level or "detail")
        if report_code == "VSS-130":
            # Multiple categories are a summary request: use one NET row per
            # category and never mix it with its DETAIL/TOTAL hierarchy.
            if self._source_filter_value_count("transaction_category") > 1:
                return record_type == "net"
            if self._source_filter_is_active("transaction_category") or self._source_filter_is_active(
                "transaction_type"
            ):
                return record_type == "detail"
            if mode == "acquirer":
                # TOTAL ACQUIRER REIMB FEES already contains both fee sides.
                # NET PURCHASE repeats the debit side and must not be posted
                # together with that total.
                return (record_type, description) == ("total", "total acquirer reimb fees")
            expected = f"net {mode} reimb fees"
            return bool(mode) and record_type == "net" and description == expected
        if report_code == "VSS-140":
            expected = f"total {mode} charges" if mode == "acquirer" else f"net {mode} charges"
            return bool(mode) and description == expected and record_type == ("total" if mode == "acquirer" else "net")
        if report_code == "VSS-210":
            # Manual scope has already applied the exact Record Type filter.
            # Respect an explicit value (for example DETAIL, TOTAL or NET)
            # instead of silently discarding every non-detail match.  With no
            # configured value, retain DETAIL as the safe non-duplicating
            # default hierarchy level.
            if self._source_filter_is_active("record_type"):
                return True
            return record_type == "detail"
        return False

    def _base_source_domain(self, report_code=None):
        self.ensure_one()
        code = report_code or self.report_code
        domain = [("import_id", "=", self.source_import_id.id), ("report_code", "=", code)]
        if self.production_date:
            domain.append(("processing_date", "=", self.production_date))
        if self.report_date:
            domain.append(("report_date", "=", self.report_date))
        return domain

    def _matches_manual_scope(self, line):
        pairs = (
            (self.reporting_for, line.reporting_for_display),
            (self.rollup_to, line.rollup_to_display),
            (self.funds_xfer_entity, line.funds_xfer_entity_display),
            (self.settlement_currency, line.settlement_currency),
        )
        if not all(self._matches_filter_values(expected, actual) for expected, actual in pairs):
            return False

        report_specific = []
        if "clearing_currency" in line._fields:
            report_specific.append(("clearing_currency", line.clearing_currency))
        if "business_mode" in line._fields:
            report_specific.append(("business_mode", line.business_mode))
        if "transaction_category" in line._fields:
            report_specific.append(("transaction_category", line.transaction_category))
        # VSS-130 NET/TOTAL rows summarize transaction types. Applying a
        # detail transaction-type filter to them drops valid category totals
        # (for example NET ORIGINAL CREDIT when CHARGEBACK is also selected).
        is_vss_130_summary = line.report_code == "VSS-130" and line.record_type in {"total", "net"}
        if "transaction_type" in line._fields and not is_vss_130_summary:
            report_specific.append(("transaction_type", line.transaction_type))
        if "disposition" in line._fields:
            report_specific.append(("disposition", line.disposition))
        if "description" in line._fields:
            report_specific.append(("description", line.description))
        if "program_network" in line._fields:
            report_specific.append(("program_network", line.program_network))
        if "record_type" in line._fields:
            report_specific.append(("record_type", line.record_type))
        if "region_country" in line._fields:
            report_specific.append(("region_country", line.region_country))
        if "fee_category" in line._fields:
            report_specific.append(("fee_category", line.fee_category))
        if "particulars" in line._fields:
            report_specific.append(("particulars", line.particulars))
        if "entity" in line._fields:
            report_specific.append(("entity", line.entity))

        for filter_key, actual in report_specific:
            if not self._matches_source_filter(filter_key, actual):
                return False
        return True

    def _matches_source_filter(self, filter_key, actual):
        legacy_field, option_field = FILTER_OPTION_FIELDS[filter_key]
        options = self[option_field]
        if options:
            actual_key = self._norm(actual) or "__blank__"
            return actual_key in set(options.mapped("value_key"))
        return self._matches_filter_values(
            self[legacy_field], actual, self[FILTER_OPERATOR_FIELDS[filter_key]] or "equals_any"
        )

    def _sync_previous_same_report_lines(self):
        """Keep the legacy display relation isolated to its owning configuration."""
        for record in self:
            super(BsrAccountingConfiguration, record).write(
                {"previous_same_report_line_ids": [(6, 0, record.line_ids.ids)]}
            )

    def _refresh_previous_same_report_lines(self):
        report_options = self.mapped("report_code_ids")
        company_ids = self.mapped("company_id").ids
        affected = self
        if report_options and company_ids:
            affected |= self.search(
                [
                    ("company_id", "in", company_ids),
                    ("batch_run_id", "=", False),
                    ("state", "in", ("matched", "ready")),
                    ("report_code_ids", "in", report_options.ids),
                ]
            )
        affected._sync_previous_same_report_lines()

    def _source_filter_is_active(self, filter_key):
        legacy_field, option_field = FILTER_OPTION_FIELDS[filter_key]
        return bool(self[option_field]) or self._filter_is_active(
            self[legacy_field], self[FILTER_OPERATOR_FIELDS[filter_key]] or "equals_any"
        )

    def _source_filter_value_count(self, filter_key):
        legacy_field, option_field = FILTER_OPTION_FIELDS[filter_key]
        if self[option_field]:
            return len(self[option_field])
        operator = self[FILTER_OPERATOR_FIELDS[filter_key]] or "equals_any"
        return len(self._split_manual_values(self[legacy_field])) if operator == "equals_any" else 0

    def _selected_amount_labels(self, report_codes=None):
        """Return user-facing names for amount columns enabled by this configuration."""
        self.ensure_one()
        report_codes = report_codes or self._report_codes_to_scan()
        field_names = {
            "VSS-110": (
                ("amount_vss_110_credit", "credit_amount"),
                ("amount_vss_110_debit", "debit_amount"),
                ("amount_vss_110_total", "total_amount"),
            ),
            "VSS-120": (
                ("amount_vss_120_clearing", "clearing_amount"),
                ("amount_vss_120_interchange_credit", "interchange_credit"),
                ("amount_vss_120_interchange_debit", "interchange_debit"),
            ),
            "VSS-130": (
                ("amount_vss_130_interchange", "interchange_amount"),
                ("amount_vss_130_fee_credit", "fee_credit"),
                ("amount_vss_130_fee_debit", "fee_debit"),
            ),
            "VSS-140": (
                ("amount_vss_140_charge_credit", "visa_charge_credit"),
                ("amount_vss_140_charge_debit", "visa_charge_debit"),
            ),
            "VSS-210": (
                ("amount_vss_210_settlement_interchange", "settlement_interchange_amount"),
                ("amount_vss_210_settlement_conversion", "settlement_conversion_fee"),
                ("amount_vss_210_clearing_interchange", "clearing_interchange_amount"),
                ("amount_vss_210_clearing_conversion", "clearing_conversion_fee"),
                ("amount_vss_210_optional_issuer", "optional_issuer_fee"),
            ),
        }
        selected = []
        for report_code in report_codes:
            for toggle, amount_field in field_names.get(report_code, ()):
                if self[toggle] and amount_field not in selected:
                    selected.append(amount_field)
        return [AMOUNT_SOURCE_LABELS.get(field, field) for field in selected]

    def _match_criteria_description(self, report_codes=None):
        """Build a compact audit description for source matching errors."""
        self.ensure_one()
        report_codes = report_codes or self._report_codes_to_scan()
        criteria = [
            _("Report IDs: %s") % ", ".join(report_codes),
            _("PROC Date: %s") % (fields.Date.to_string(self.production_date) or _("Any")),
            _("Report Date: %s") % (fields.Date.to_string(self.report_date) or _("Any")),
        ]
        for field_name in ("reporting_for", "rollup_to", "funds_xfer_entity", "settlement_currency"):
            if self[field_name]:
                criteria.append(_("%s: %s") % (self._fields[field_name].string, self[field_name]))
        for filter_key, (legacy_field, option_field) in FILTER_OPTION_FIELDS.items():
            operator = self[FILTER_OPERATOR_FIELDS[filter_key]] or "equals_any"
            options = self[option_field]
            if options:
                value = ", ".join(options.mapped("name"))
            elif self._filter_is_active(self[legacy_field], operator):
                value = self[legacy_field] or dict(FILTER_OPERATOR_SELECTION).get(operator, operator)
            else:
                continue
            criteria.append(_("%s: %s") % (self._fields[legacy_field].string, value))
        amount_labels = self._selected_amount_labels(report_codes)
        criteria.append(_("Amount columns: %s") % (", ".join(amount_labels) or _("None")))
        return "; ".join(criteria)

    def _matches_filter_values(self, expected, actual, operator="equals_any"):
        """Apply a normalized operator; an empty value list always means no filter."""
        normalized_actual = self._norm(actual)
        if operator == "any":
            return True
        if operator == "blank":
            return not normalized_actual
        if operator == "not_blank":
            return bool(normalized_actual)
        accepted = {self._norm(value) for value in self._split_manual_values(expected)}
        if not accepted:
            return True
        if operator == "not_equals_any":
            return normalized_actual not in accepted
        return normalized_actual in accepted

    def _filter_is_active(self, expected, operator):
        if operator == "any":
            return False
        if operator in {"blank", "not_blank"}:
            return True
        return bool(self._split_manual_values(expected))

    @api.onchange("source_import_id")
    def _onchange_source_scope(self):
        for record in self:
            record.report_code_ids = False
            record.report_id_filter = False
            if not record.source_import_id:
                continue
            record._ensure_filter_option_catalog()
            lines = []
            for code in REPORT_CODES:
                lines += self.env[LINE_MODEL_BY_REPORT[code]].search(
                    [("import_id", "=", record.source_import_id.id), ("report_code", "=", code)]
                )
            production_dates = set(filter(None, [line.processing_date for line in lines]))
            report_dates = set(filter(None, [line.report_date for line in lines]))
            if len(production_dates) == 1:
                record.production_date = production_dates.pop()
            if len(report_dates) == 1:
                record.report_date = report_dates.pop()
            if not record.posting_date and record.report_date:
                record.posting_date = record.report_date

    @api.onchange("report_code_ids")
    def _onchange_report_code_ids(self):
        for record in self:
            selected = set(record.report_code_ids.mapped("code"))
            record.report_id_filter = ", ".join(code for code in REPORT_CODES if code in selected) or False
            if "VSS-120" in selected and not record.vss_120_source_level:
                record.vss_120_source_level = "detail"
            elif "VSS-120" not in selected:
                record.vss_120_source_level = False

    def action_match_source(self):
        self.ensure_one()
        self._ensure_filter_option_catalog()
        self._adopt_legacy_filter_options()
        report_codes = self._report_codes_to_scan()
        if not report_codes:
            raise UserError(_("Select at least one Report ID from the processed VSS file."))
        available = set(self.available_report_code_ids.mapped("code"))
        if not set(report_codes).issubset(available):
            raise UserError(_("Selected Report IDs must be present in the processed VSS file."))

        previous = {line.match_key: line for line in self.line_ids}
        grouped = {}
        total_source_rows = 0
        total_scoped_rows = 0
        total_eligible_rows = 0
        enabled_amount_fields = set()
        nonzero_amount_count = 0
        for report_code in report_codes:
            source_lines = self.env[LINE_MODEL_BY_REPORT[report_code]].search(self._base_source_domain(report_code))
            total_source_rows += len(source_lines)
            source_lines = source_lines.filtered(self._matches_manual_scope)
            total_scoped_rows += len(source_lines)
            if not source_lines:
                continue
            eligible = source_lines.filtered(lambda line: self._is_accounting_source_row(report_code, line))
            total_eligible_rows += len(eligible)
            report_contributions = 0
            for source in eligible:
                clearing_currency = source["clearing_currency"] if "clearing_currency" in source._fields else ""
                business_mode = source["business_mode"] if "business_mode" in source._fields else ""
                transaction_category = source["transaction_category"] if "transaction_category" in source._fields else ""
                transaction_type = source["transaction_type"] if "transaction_type" in source._fields else ""
                description = self._source_description(report_code, source)
                particulars = source.particulars if report_code == "VSS-110" else ""
                entity = source.entity if report_code == "VSS-110" else ""
                amount_fields = self._source_amount_fields(report_code, source)
                enabled_amount_fields.update(field for field, _direction in amount_fields)
                nonzero_amount_count += sum(
                    1 for field, _direction in amount_fields
                    if field in source._fields and source[field]
                )
                variants = self._source_variants(report_code, source)
                if not variants:
                    continue
                posting_by_field = {
                    amount_source: _posting_indicator_from_source(
                        report_code,
                        source.record_type,
                        particulars,
                        entity,
                        amount_source,
                        source_direction,
                    )
                    for source_direction, amount_source, _amount in variants
                }
                variant_groups = self._source_variant_groups(
                    report_code, variants, posting_by_field
                )
                for source_direction, amount_source, amount, additional_amounts in variant_groups:
                    source_currency = self._source_currency(report_code, source, amount_source)
                    values = (
                        report_code,
                        source.record_type,
                        particulars or "",
                        entity or "",
                        clearing_currency or "",
                        business_mode or "",
                        transaction_category or "",
                        transaction_type or "",
                        description or "",
                        source_direction or "",
                        amount_source or "",
                        source_currency or "",
                    )
                    key = "|".join(self._norm(value) for value in values)
                    item = grouped.setdefault(
                        key,
                        {
                            "values": values,
                            "count": 0,
                            "amount": 0.0,
                            "usd_amount": 0.0,
                            "additional_amounts": {},
                            "source_ids": [],
                        },
                    )
                    item["count"] += 1
                    item["amount"] += amount
                    item["usd_amount"] += self._usd_amount(
                        report_code, source, amount_source, amount, source_currency
                    )
                    for field, value in additional_amounts.items():
                        item["additional_amounts"][field] = (
                            item["additional_amounts"].get(field, 0.0) + value
                        )
                    item["source_ids"].append(str(source.id))
                    report_contributions += 1
            if not report_contributions:
                continue

        if not grouped:
            criteria = self._match_criteria_description(report_codes)
            if not total_source_rows:
                reason = _("No source rows exist for the selected Report IDs and dates.")
            elif not total_scoped_rows:
                reason = _("Source rows exist, but none match the saved configuration criteria.")
            elif not total_eligible_rows:
                reason = _("Source rows match the saved criteria, but none match the configured accounting level.")
            elif not enabled_amount_fields:
                reason = _("No accounting amount column is enabled for the matched source rows.")
            elif nonzero_amount_count:
                reason = _(
                    "Matched rows contain non-zero selected amounts, but their source direction is missing or invalid."
                )
            else:
                message = _(
                    "No Activity: %(rows)s eligible source row(s) matched, but all selected amount columns are zero. "
                    "%(criteria)s"
                ) % {"rows": total_eligible_rows, "criteria": criteria}
                if self.env.context.get("allow_no_activity"):
                    self.line_ids.unlink()
                    self.write(
                        {
                            "state": "no_activity",
                            "validation_message": message,
                            "matched_at": fields.Datetime.now(),
                            "matched_by_id": self.env.user.id,
                        }
                    )
                    self._sync_previous_same_report_lines()
                    return {"match_status": "no_activity", "message": message}
                raise UserError(message)
            raise UserError(_("%(reason)s Matching criteria: %(criteria)s") % {
                "reason": reason,
                "criteria": criteria,
            })

        applicable_reports = [
            code for code in report_codes if any(item["values"][0] == code for item in grouped.values())
        ]
        new_values = []
        for sequence, (key, item) in enumerate(grouped.items(), 1):
            # Preserve GL entries from configurations matched before source
            # Particulars/Entity became part of the rule identity.
            legacy_key = "|".join(
                self._norm(value)
                for index, value in enumerate(item["values"])
                if index not in (2, 3)
            )
            legacy_empty_key = "|".join(
                self._norm(value if index not in (2, 3) else "")
                for index, value in enumerate(item["values"])
            )
            legacy_currency_key = "|".join(self._norm(value) for value in item["values"][:-1])
            legacy_currency_empty_key = "|".join(
                self._norm(value) for value in (*item["values"][:-1], "")
            )
            old = (
                previous.get(key)
                or previous.get(legacy_key)
                or previous.get(legacy_empty_key)
                or previous.get(legacy_currency_key)
                or previous.get(legacy_currency_empty_key)
            )
            (
                report_code,
                record_type,
                particulars,
                entity,
                clearing_currency,
                business_mode,
                category,
                transaction_type,
                description,
                direction,
                amount_source,
                source_currency,
            ) = item["values"]
            new_values.append(
                {
                    "configuration_id": self.id,
                    "sequence": sequence * 10,
                    "report_code": report_code,
                    "record_type": record_type,
                    "source_particulars": particulars,
                    "source_entity": entity,
                    "clearing_currency": clearing_currency,
                    "business_mode": business_mode,
                    "transaction_category": category,
                    "transaction_type": transaction_type,
                    "description_match": description,
                    "source_direction": direction or False,
                    "amount_source": amount_source,
                    "source_currency": source_currency,
                    "conversion_type": (
                        old.conversion_type
                        if old and old.conversion_type
                        else (self.conversion_type if self._norm(source_currency).upper() == "USD" else False)
                    ),
                    "posting_indicator": (
                        old.posting_indicator
                        if old and old.posting_indicator
                        else _posting_indicator_from_source(
                            report_code,
                            record_type,
                            particulars,
                            entity,
                            amount_source,
                            direction,
                        )
                    ),
                    "matched_amount": item["amount"],
                    "usd_amount": item["usd_amount"],
                    "amount_columns_json": item["additional_amounts"],
                    "source_row_count": item["count"],
                    "source_record_ids": ",".join(item["source_ids"]),
                    "include_in_voucher": old.include_in_voucher if old else True,
                    "gl_number": old.gl_number if old else False,
                    "gl_name": old.gl_name if old else False,
                    "debit_remarks": old.debit_remarks if old else False,
                    "credit_remarks": old.credit_remarks if old else False,
                    "remarks": old.remarks if old else False,
                }
            )
        self.line_ids.unlink()
        self.env["bsr.accounting.mapping"].create(new_values)
        incomplete = len([value for value in new_values if not value.get("gl_number") or not value.get("gl_name")])
        self.write(
            {
                "state": "matched",
                "validation_message": _(
                    "%(rules)s accounting rule(s) were built from %(rows)s controlled source row(s) in the complete "
                    "processed file. Applicable sources: %(reports)s. "
                    "Complete GL Number and GL Name for %(missing)s rule(s)."
                )
                % {
                    "rules": len(new_values),
                    "rows": total_eligible_rows,
                    "reports": ", ".join(applicable_reports),
                    "missing": incomplete,
                },
                "matched_at": fields.Datetime.now(),
                "matched_by_id": self.env.user.id,
            }
        )
        self._refresh_previous_same_report_lines()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Controlled Source Match Completed"),
                "message": self.validation_message,
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }

    def action_validate(self):
        self.ensure_one()
        included = self.line_ids.filtered("include_in_voucher")
        if not included:
            raise UserError(_("Match source reports and keep at least one accounting rule enabled."))
        incomplete = included.filtered(lambda line: line.configuration_status != "configured")
        if incomplete:
            self.state = "matched"
            raise UserError(_("%s included rule(s) still require both GL Number and GL Name.") % len(incomplete))
        if self.is_preview_balanced:
            message = _("GL configuration is complete. Debit and Credit are both %.2f.") % self.preview_debit_total
        else:
            message = _(
                "GL configuration is complete, but this voucher has a mismatch. Debit: %(debit).2f, "
                "Credit: %(credit).2f, Difference: %(difference).2f. The report will be generated as an exception."
            ) % {
                "debit": self.preview_debit_total,
                "credit": self.preview_credit_total,
                "difference": self.preview_difference,
            }
        self.write(
            {
                "state": "ready",
                "validation_message": message,
            }
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Configuration Ready"),
                "message": self.validation_message,
                "type": "success" if self.is_preview_balanced else "warning",
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }

    def action_reset_draft(self):
        self.write({"state": "draft", "validation_message": False})
        self._refresh_previous_same_report_lines()

    def action_generate_report(self):
        self.ensure_one()
        # Recheck every time so a legacy or externally modified setup can never
        # bypass the GL-completeness and balance controls.
        self.action_validate()
        report = self.env["bsr.accounting.report"].create({"configuration_id": self.id})
        report.action_generate()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "zenrecon.action_bsr_accounting_report"
        )
        action.update({"view_mode": "form", "views": [(False, "form")], "res_id": report.id})
        return action

    @api.model
    def get_dashboard_data(self, business_date=None):
        """Return dashboard data for a specific business date (report_date).

        business_date: string 'YYYY-MM-DD' or False → today
        """
        Report = self.env["bsr.accounting.report"]
        Config = self.env["bsr.accounting.configuration"]
        Mapping = self.env["bsr.accounting.mapping"]
        Import = self.env["bsr.vss.import"]
        Run = self.env["bsr.accounting.run"]

        # Resolve business date
        if business_date:
            try:
                biz_date = fields.Date.to_date(business_date)
            except Exception:
                biz_date = fields.Date.context_today(self)
        else:
            biz_date = fields.Date.context_today(self)

        biz_date_str = fields.Date.to_string(biz_date)

        # ---------- Real global metrics (not date-filtered for now) ----------
        configs = Config.search([("batch_run_id", "=", False)])
        ready = configs.filtered(lambda c: c.state == "ready")
        incomplete_rules = Mapping.search_count([
            ("configuration_status", "=", "incomplete"),
            ("include_in_voucher", "=", True),
            ("configuration_id.batch_run_id", "=", False),
        ])
        reports = Report.search([])
        exceptions = reports.filtered(lambda r: r.state == "exception")
        pending_vouchers = reports.filtered(lambda r: r.state in ("balanced", "checked", "draft"))

        # ---------- VISA status for the selected business date ----------
        # Dates live on the line models, not on the import header.
        line_models = [
            "bsr.vss.110.line",
            "bsr.vss.120.line",
            "bsr.vss.130.line",
            "bsr.vss.140.line",
            "bsr.vss.210.line",
        ]
        import_ids = set()
        for model_name in line_models:
            lines = self.env[model_name].sudo().search([("report_date", "=", biz_date)])
            import_ids.update(lines.mapped("import_id").ids)

        visa_source = "Missing"
        visa_gross = "—"
        visa_detailed = "—"
        visa_exception = "—"
        visa_voucher = "—"

        if import_ids:
            imports = Import.browse(list(import_ids))
            # Prefer the most recent completed/partial import
            good = imports.filtered(lambda i: i.state in ("completed", "partial"))
            if good:
                visa_source = "Received"
                visa_gross = "Reconciled"
                visa_detailed = "100%"
                visa_exception = 0
            else:
                # Only draft / processing / failed
                if any(i.state in ("draft", "processing") for i in imports):
                    visa_source = "Pending"
                    visa_gross = "Pending"
                else:
                    visa_source = "Missing"
                    visa_gross = "—"

        # Voucher status from accounting runs of the same report_date
        runs = Run.search([
            ("report_date", "=", biz_date),
            ("company_id", "=", self.env.company.id),
        ], order="id desc", limit=5)

        if runs:
            # Take the latest run
            latest = runs[0]
            if latest.state == "done":
                visa_voucher = "Posted"
            elif latest.state == "exception":
                visa_voucher = "Exception"
            else:  # draft
                visa_voucher = "Pending"
        else:
            if visa_source == "Received":
                visa_voucher = "Not Generated"
            else:
                visa_voucher = "—"

        # Build schemes list – VISA is real, others remain demo
        schemes = [
            {
                "name": "VISA",
                "source": visa_source,
                "gross": visa_gross,
                "detailed": visa_detailed,
                "exception": visa_exception,
                "voucher": visa_voucher,
            },
            # Demo rows (keep for now)
            {"name": "Mastercard", "source": "Received", "gross": "Reconciled", "detailed": "100%", "exception": 0, "voucher": "Posted"},
            {"name": "Amex", "source": "Received", "gross": "Reconciled", "detailed": "99.6%", "exception": 4, "voucher": "Pending"},
            {"name": "JCB", "source": "Received", "gross": "Variance", "detailed": "92.1%", "exception": 47, "voucher": "Not Generated"},
            {"name": "CUP", "source": "Received", "gross": "Reconciled", "detailed": "100%", "exception": 0, "voucher": "Posted"},
            {"name": "NPSB", "source": "Missing", "gross": "—", "detailed": "—", "exception": "—", "voucher": "—"},
            {"name": "Own ATM/POS", "source": "Received", "gross": "Reconciled", "detailed": "98.9%", "exception": 11, "voucher": "Pending"},
        ]

        recent = [
            {"type": "warning", "title": "NPSB file not received", "detail": "Cutoff 09:00 · 8 min ago"},
            {"type": "warning", "title": "JCB Exception threshold exceeded", "detail": "47 items · 22 min ago"},
            {"type": "success", "title": "VISA fully reconciled & posted", "detail": "Voucher V-20260912-01 · 1 hr ago"},
            {"type": "info", "title": "CBS batch posting in progress", "detail": "Batch B-20260912-04 · 1 hr ago"},
        ]

        return {
            # Real metrics
            "configurations": len(configs),
            "ready_configurations": len(ready),
            "incomplete_rules": incomplete_rules,
            "reports": len(reports),
            "exceptions": len(exceptions),
            "pending_vouchers": len(pending_vouchers),

            # Demo KPIs (later we can make them date-aware too)
            "transactions_processed": 184662,
            "transactions_trend": 4.2,
            "schemes_reconciled": 6 if visa_source == "Received" else 5,
            "schemes_total": 7,
            "unreconciled_amount": 486250,
            "files_missing": 1 if visa_source == "Missing" else 0,
            "files_missing_detail": "NPSB · cutoff 09:00" if visa_source != "Missing" else "VISA + NPSB",

            # Chart
            "recon_rate": 88 if visa_source == "Received" else 75,
            "recon_pending": 8,
            "recon_exceptions": 4,

            # Tables
            "schemes": schemes,
            "recent_activity": recent,

            # Meta
            "business_date": biz_date.strftime("%d %b %Y"),
            "business_date_raw": biz_date_str,          # for the date input
            "last_updated": "just now",
        }


    @api.model
    def get_voucher_entries_data(self, business_date=None):
        """Data for the Voucher & Entries OWL page."""
        if business_date:
            try:
                biz_date = fields.Date.to_date(business_date)
            except Exception:
                biz_date = fields.Date.context_today(self)
        else:
            biz_date = fields.Date.context_today(self)

        biz_date_str = fields.Date.to_string(biz_date)
        Report = self.env["bsr.accounting.report"]

        # Real VISA reports for the selected date
        visa_reports = Report.search([
            ("report_date", "=", biz_date),
            ("company_id", "=", self.env.company.id),
        ], order="id desc")

        def _status_label(state):
            return {
                "approved": "Posted",
                "checked": "Pending Approval",
                "balanced": "Pending Approval",
                "exception": "Exception",
                "cancelled": "Cancelled",
                "draft": "Draft",
            }.get(state, state or "Not Generated")

        visa_row = {
            "scheme": "VISA",
            "reconciled_amount": 0.0,
            "gl_mapping": "GL Mapping Missing",
            "voucher_status": "Not Generated",
            "voucher_no": "-",
            "can_view": False,
            "can_approve": False,
            "can_generate": True,
            "report_id": False,
        }

        if visa_reports:
            report = visa_reports[0]
            has_gl = bool(report.voucher_id and report.voucher_id.line_ids)
            visa_row.update({
                "reconciled_amount": report.debit_total or report.credit_total or 0.0,
                "gl_mapping": "Configured" if has_gl else "GL Mapping Missing",
                "voucher_status": _status_label(report.state),
                "voucher_no": report.name or "-",
                "can_view": True,
                "can_approve": report.state in ("balanced", "checked"),
                "can_generate": False,
                "report_id": report.id,
            })

        # Demo rows for other schemes (replace later)
        schemes = [
            visa_row,
            {
                "scheme": "Mastercard",
                "reconciled_amount": 71088200.0,
                "gl_mapping": "Configured",
                "voucher_status": "Posted",
                "voucher_no": "V-20260912-02",
                "can_view": True,
                "can_approve": False,
                "can_generate": False,
                "report_id": False,
            },
            {
                "scheme": "Amex",
                "reconciled_amount": 9608970.0,
                "gl_mapping": "Configured",
                "voucher_status": "Pending Approval",
                "voucher_no": "V-20260912-03",
                "can_view": True,
                "can_approve": True,
                "can_generate": False,
                "report_id": False,
            },
            {
                "scheme": "CUP",
                "reconciled_amount": 2217300.0,
                "gl_mapping": "Configured",
                "voucher_status": "Posted",
                "voucher_no": "V-20260912-04",
                "can_view": True,
                "can_approve": False,
                "can_generate": False,
                "report_id": False,
            },
            {
                "scheme": "Own ATM/POS",
                "reconciled_amount": 56390410.0,
                "gl_mapping": "Configured",
                "voucher_status": "Pending Approval",
                "voucher_no": "V-20260912-05",
                "can_view": True,
                "can_approve": True,
                "can_generate": False,
                "report_id": False,
            },
            {
                "scheme": "JCB",
                "reconciled_amount": 4066800.0,
                "gl_mapping": "GL Mapping Missing",
                "voucher_status": "Not Generated",
                "voucher_no": "-",
                "can_view": False,
                "can_approve": False,
                "can_generate": True,
                "report_id": False,
            },
        ]

        # Detail panel – prefer real VISA report, otherwise demo Amex
        detail = None
        selected = next((s for s in schemes if s.get("report_id")), None)
        if not selected:
            selected = next((s for s in schemes if s["voucher_status"] == "Pending Approval"), schemes[0])

        if selected.get("report_id"):
            report = Report.browse(selected["report_id"])
            lines = []
            for v in report.voucher_ids:
                for line in v.line_ids.sorted("sequence"):
                    lines.append({
                        "gl_account": line.gl_number or "",
                        "account_name": line.gl_name or "",
                        "debit": line.amount if line.posting_indicator == "DR" else 0.0,
                        "credit": line.amount if line.posting_indicator == "CR" else 0.0,
                    })
            detail = {
                "title": f"{report.name} · VISA Settlement",
                "subtitle": f"Auto-generated from reconciled batch · {biz_date.strftime('%d %b %Y')}",
                "status": selected["voucher_status"],
                "narration": (report.configuration_id.remarks or "VISA settlement voucher"),
                "lines": lines,
                "debit_total": report.debit_total or 0.0,
                "credit_total": report.credit_total or 0.0,
                "report_id": report.id,
            }
        else:
            detail = {
                "title": "Voucher V-20260912-03 · Amex Settlement",
                "subtitle": f"Auto-generated from reconciled batch · {biz_date.strftime('%d %b %Y')}",
                "status": "Pending Approval",
                "narration": "Amex card settlement receivable – batch #AMEX-20260912 – 3,240 transactions, net of commission & VAT per approved GL schedule.",
                "lines": [
                    {"gl_account": "1102-4410", "account_name": "Amex Settlement Receivable", "debit": 9644120.0, "credit": 0.0},
                    {"gl_account": "4401-1100", "account_name": "Card Commission Income", "debit": 0.0, "credit": 33750.0},
                    {"gl_account": "2201-0090", "account_name": "VAT Payable – Card Services", "debit": 0.0, "credit": 1400.0},
                    {"gl_account": "1001-0001", "account_name": "Nostro / Clearing Account", "debit": 0.0, "credit": 9608970.0},
                ],
                "debit_total": 9644120.0,
                "credit_total": 9644120.0,
                "report_id": False,
            }

        return {
        "business_date": biz_date.strftime("%d %b %Y"),
        "business_date_raw": biz_date_str,
        "schemes": schemes,
        "detail": detail,
    }

    @api.model
    def get_notifications_data(self):
        """Demo data for Notifications page (replace with real model later)."""
        notifications = [
            {
                "id": 1,
                "type": "critical",
                "title": "File missing – NPSB",
                "message": "NPSB raw switch file for business date 12 Sep 2026 was not received by the 09:00 cutoff.",
                "source": "File Processing",
                "time": "8 minutes ago",
                "unread": True,
                "actions": ["Request Resend", "Dismiss"],
            },
            {
                "id": 2,
                "type": "critical",
                "title": "CBS posting failed",
                "message": "Batch CBS_BATCH_20260912_00.txt failed to post – API returned 504 Timeout after 3 retries.",
                "source": "Batch / API Posting",
                "time": "42 minutes ago",
                "unread": True,
                "actions": ["Retry Now", "Dismiss"],
            },
            {
                "id": 3,
                "type": "warning",
                "title": "Unmatched threshold exceeded – JCB",
                "message": "47 unmatched transactions (৳41,850) exceed the configured 2% threshold.",
                "source": "Detailed Reconciliation",
                "time": "1 hour ago",
                "unread": True,
                "actions": ["Investigate"],
            },
            {
                "id": 4,
                "type": "warning",
                "title": "GL mapping missing – JCB",
                "message": "No active GL mapping found for JCB settlement receivable.",
                "source": "Accounting Setup",
                "time": "2 hours ago",
                "unread": False,
                "actions": ["Configure"],
            },
            {
                "id": 5,
                "type": "info",
                "title": "VISA fully reconciled & posted",
                "message": "100% gross & detailed match. Voucher V-20260912-01 approved and confirmed posted to CBS.",
                "source": "Voucher & Entries",
                "time": "3 hours ago",
                "unread": False,
                "actions": [],
            },
        ]

        alert_rules = [
            {"name": "Missing file after cutoff", "enabled": True},
            {"name": "Unmatched % threshold", "enabled": True},
            {"name": "CBS posting failure", "enabled": True},
            {"name": "GL mapping gap", "enabled": True},
            {"name": "Voucher pending > 4 hrs", "enabled": False},
        ]

        return {
            "notifications": notifications,
            "alert_rules": alert_rules,
            "counts": {
                "all": len(notifications),
                "critical": len([n for n in notifications if n["type"] == "critical"]),
                "warning": len([n for n in notifications if n["type"] == "warning"]),
                "info": len([n for n in notifications if n["type"] == "info"]),
                "unread": len([n for n in notifications if n["unread"]]),
            },
        }

    @api.model
    def get_users_access_data(self):
        """Real users for the Users & Access page."""
        self._check_access_administration()
        Users = self.env["res.users"].sudo()
        users = Users.search([
            ("share", "=", False),
        ], order="name")

        # Groups we care about as "roles" in this app
        role_groups = self.env["res.groups"].sudo().search([
            ("id", "in", [
                self.env.ref("zenrecon.group_bsr_report_operator").id,
                self.env.ref("zenrecon.group_bsr_configuration_manager").id,
                self.env.ref("zenrecon.group_bsr_report_checker").id,
                self.env.ref("base.group_system").id,
            ])
        ])

        rows = []
        for u in users:
            user_roles = []
            for g in role_groups:
                if g in u.group_ids:
                    user_roles.append(g.name)
            if not user_roles and u.has_group("base.group_user"):
                user_roles = ["Internal User"]

            last_login = "—"
            if u.login_date:
                last_login = fields.Datetime.context_timestamp(
                    self, u.login_date
                ).strftime("%d %b %Y, %H:%M")

            rows.append({
                "id": u.id,
                "name": u.name,
                "email": u.email or u.login or "",
                "login": u.login,
                "roles": user_roles,
                "role_ids": [g.id for g in role_groups if g in u.group_ids],
                "department": u.partner_id.function or "",
                "status": "Active" if u.active else "Inactive",
                "active": u.active,
                "last_login": last_login,
                "employee_id": "",  # fill later if you add a field
                "scheme_access": [],  # future: custom field
            })

        available_roles = [
            {"id": g.id, "name": g.name}
            for g in role_groups
        ]

        return {
            "users": rows,
            "summary": {
                "total": len(rows),
                "roles": len(available_roles),
                "inactive": len([r for r in rows if not r["active"]]),
            },
            "available_roles": available_roles,
            "available_schemes": ["VISA", "Mastercard", "Amex", "JCB", "CUP", "NPSB", "ATM/POS"],
        }

    @api.model
    def action_open_user_form(self, user_id):
        """Open standard user form (for full edit)."""
        self._check_access_administration()
        user = self.env["res.users"].browse(int(user_id)).exists()
        if not user:
            raise UserError(_("User not found."))
        return {
            "type": "ir.actions.act_window",
            "name": _("User"),
            "res_model": "res.users",
            "res_id": user.id,
            "view_mode": "form",
            "target": "current",
            "context": {"form_view_initial_mode": "edit"},
        }

    @api.model
    def save_user_access(self, user_id, values):
        """Update basic user fields + role groups from the custom panel."""
        self._check_access_administration()
        user = self.env["res.users"].sudo().browse(int(user_id))
        if not user.exists():
            raise UserError(_("User not found."))

        write_vals = {}
        if "name" in values:
            write_vals["name"] = values["name"]
        if "email" in values:
            write_vals["email"] = values["email"]
        if "active" in values:
            write_vals["active"] = bool(values["active"])

        # Role groups (replace only our BSR-related groups)
        if "role_ids" in values:
            our_group_xmlids = [
                "zenrecon.group_bsr_report_operator",
                "zenrecon.group_bsr_configuration_manager",
                "zenrecon.group_bsr_report_checker",
                "base.group_system",
            ]
            our_groups = self.env["res.groups"].sudo()
            for xid in our_group_xmlids:
                our_groups |= self.env.ref(xid, raise_if_not_found=False)

            selected_groups = self.env["res.groups"].sudo().browse(values["role_ids"]).exists()
            invalid_groups = selected_groups - our_groups
            if invalid_groups:
                raise ValidationError(_("Only Bank Reconciliation roles can be assigned here."))
            system_group = self.env.ref("base.group_system")
            if user == self.env.user and system_group not in selected_groups:
                raise ValidationError(_("You cannot remove your own administrator access."))

            # Keep groups that are not in our managed set; set managed ones from role_ids
            other_groups = user.group_ids - our_groups
            write_vals["group_ids"] = [(6, 0, (other_groups | selected_groups).ids)]

        if write_vals:
            user.write(write_vals)
        return True

    @api.model
    def get_roles_permissions_data(self):
        """Real groups (roles) + simplified permission matrix for key models."""
        self._check_access_administration()
        Group = self.env["res.groups"].sudo()
        Access = self.env["ir.model.access"].sudo()

        # Roles = our BSR groups + system
        xmlids = [
            "zenrecon.group_bsr_report_operator",
            "zenrecon.group_bsr_configuration_manager",
            "zenrecon.group_bsr_report_checker",
            "base.group_system",
        ]
        groups = Group.browse()
        for xid in xmlids:
            groups |= self.env.ref(xid, raise_if_not_found=False)

        # Key models shown in the matrix (map UI module name → model)
        module_models = [
            ("Dashboard", None),  # client action only
            ("File Processing", "bsr.vss.import"),
            ("Gross Reconciliation", "bsr.vss.import"),
            ("Detailed Reconciliation", None),
            ("Voucher & Entries", "bsr.accounting.report"),
            ("Batch / API Posting", "bsr.accounting.run"),
            ("History", None),
            ("Notifications", None),
            ("Users & Access", "res.users"),
            ("Roles & Permissions", "res.groups"),
            ("Accounting Setup", "bsr.accounting.configuration"),
        ]

        roles = []
        for g in groups:
            user_count = self.env["res.users"].sudo().search_count([
                ("group_ids", "in", g.id),
                ("share", "=", False),
            ])
            perms = {}
            for label, model_name in module_models:
                if not model_name:
                    # UI-only rows: view allowed if internal user
                    perms[label] = {
                        "view": True,
                        "create": False,
                        "edit": False,
                        "approve": False,
                        "delete": False,
                    }
                    continue
                model = self.env["ir.model"].sudo().search([("model", "=", model_name)], limit=1)
                if not model:
                    perms[label] = {k: False for k in ("view", "create", "edit", "approve", "delete")}
                    continue
                access = Access.search([
                    ("model_id", "=", model.id),
                    ("group_id", "=", g.id),
                ], limit=1)
                if access:
                    perms[label] = {
                        "view": bool(access.perm_read),
                        "create": bool(access.perm_create),
                        "edit": bool(access.perm_write),
                        "approve": bool(access.perm_write),  # approximate
                        "delete": bool(access.perm_unlink),
                    }
                else:
                    # Inherit from implied groups roughly: if system admin → full
                    is_admin = g == self.env.ref("base.group_system")
                    perms[label] = {
                        "view": is_admin,
                        "create": is_admin,
                        "edit": is_admin,
                        "approve": is_admin,
                        "delete": is_admin,
                    }

            roles.append({
                "id": g.id,
                "name": g.name,
                "users": user_count,
                "description": g.comment or g.name,
                "permissions": perms,
            })

        return {
            "roles": roles,
            "modules": [m[0] for m in module_models],
            "actions": ["view", "create", "edit", "approve", "delete"],
        }

    @api.model
    def action_open_group_form(self, group_id):
        self._check_access_administration()
        group = self.env["res.groups"].browse(int(group_id)).exists()
        if not group:
            raise UserError(_("Role not found."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Group"),
            "res_model": "res.groups",
            "res_id": group.id,
            "view_mode": "form",
            "target": "current",
        }

    def _check_access_administration(self):
        if not self.env.user.has_group("base.group_system"):
            raise AccessError(_("Only Settings administrators can manage users and roles."))


class BsrAccountingMapping(models.Model):
    _name = "bsr.accounting.mapping"
    _description = "Matched VSS Voucher Configuration Line"
    _order = "configuration_id desc, sequence, id"
    _check_company_auto = True

    sequence = fields.Integer(default=10, index=True)
    configuration_id = fields.Many2one(
        "bsr.accounting.configuration", required=True, index=True, ondelete="cascade", check_company=True
    )
    company_id = fields.Many2one(related="configuration_id.company_id", store=True, index=True)
    source_import_id = fields.Many2one(
        related="configuration_id.source_import_id", string="Processed VSS File", store=True, index=True
    )
    configuration_state = fields.Selection(
        related="configuration_id.state", string="Configuration State", store=True, index=True
    )
    report_code = fields.Selection(REPORT_SELECTION, string="Report ID", required=True, index=True)
    record_type = fields.Selection(
        RECORD_TYPE_SELECTION, string="Source Level", required=True, default="detail", readonly=True
    )
    production_date = fields.Date(related="configuration_id.production_date", string="PROC Date", store=True)
    report_date = fields.Date(related="configuration_id.report_date", store=True)
    business_owner = fields.Char(related="configuration_id.business_owner", store=True)
    product_type = fields.Char(related="configuration_id.product_type", store=True)
    reporting_for = fields.Char(related="configuration_id.reporting_for", store=True)
    rollup_to = fields.Char(related="configuration_id.rollup_to", store=True)
    funds_xfer_entity = fields.Char(related="configuration_id.funds_xfer_entity", string="Funds Xfer Entity", store=True)
    settlement_currency = fields.Char(related="configuration_id.settlement_currency", store=True)
    source_particulars = fields.Char(string="Source Particulars", readonly=True, index=True)
    source_entity = fields.Char(string="Source Entity", readonly=True, index=True)
    clearing_currency = fields.Char(readonly=True, index=True)
    business_mode = fields.Char(readonly=True, index=True)
    transaction_category = fields.Char(readonly=True, index=True)
    transaction_type = fields.Char(readonly=True, index=True)
    description_match = fields.Char(string="Source Description", readonly=True, index=True)
    source_direction = fields.Selection(SOURCE_DIRECTION_SELECTION, string="Source CR/DB", readonly=True, index=True)
    amount_source = fields.Selection(AMOUNT_SOURCE_SELECTION, string="Source Amount", readonly=True, index=True)
    source_currency = fields.Char(string="Source Currency", readonly=True, index=True)
    conversion_type = fields.Selection(
        CONVERSION_TYPE_SELECTION,
        string="Conversion Type",
        help="Daily USD/BDT rate type used for this accounting rule.",
    )
    matched_amount = fields.Float(string="Matched Amount", readonly=True, digits=(20, 2))
    amount_columns_json = fields.Json(
        string="Additional Amount Columns",
        readonly=True,
        copy=True,
        help="Selected source amounts after the primary accounting amount, stored as informational columns.",
    )
    for _amount_code, _amount_label in AMOUNT_SOURCE_SELECTION:
        locals()[f"additional_amount_{_amount_code}"] = fields.Float(
            string=_amount_label,
            compute="_compute_additional_amount_values",
            readonly=True,
            digits=(20, 2),
        )
    usd_amount = fields.Float(string="USD Amount", readonly=True, digits=(20, 2))
    show_usd_amount = fields.Boolean(related="configuration_id.show_usd_amount", readonly=True)
    debit_amount = fields.Float(string="Debit", compute="_compute_posting_amounts", store=True, digits=(20, 2))
    credit_amount = fields.Float(string="Credit", compute="_compute_posting_amounts", store=True, digits=(20, 2))
    include_in_voucher = fields.Boolean(string="Use", default=True, index=True)
    gl_number = fields.Char(string="GL Number", index=True)
    gl_name = fields.Char(string="GL Name")
    debit_remarks = fields.Text(string="Debit Remarks")
    credit_remarks = fields.Text(string="Credit Remarks")
    posting_indicator = fields.Selection(
        POSTING_SELECTION,
        string="GL Posting Indicator",
        index=True,
        help="Defaults from the VSS CR/DB value. VSS-110 Total Amount is reversed. May be adjusted after matching.",
    )
    remarks = fields.Text()
    source_row_count = fields.Integer(readonly=True)
    source_record_ids = fields.Text(readonly=True)
    match_key = fields.Char(compute="_compute_match_key", store=True, index=True)
    configuration_status = fields.Selection(
        [("configured", "Configured"), ("incomplete", "Needs GL"), ("excluded", "Excluded"), ("inactive", "Inactive (Legacy)")],
        compute="_compute_configuration_status",
        store=True,
        index=True,
    )

    _configuration_match_key_unique = models.Constraint(
        "UNIQUE(configuration_id, match_key)",
        "The same source rule cannot be added more than once to one configuration.",
    )

    def action_delete_rule(self):
        """Remove one editable rule without affecting any other configuration."""
        self.ensure_one()
        configuration = self.configuration_id
        if configuration.state == "ready":
            raise UserError(_("Click Edit / Re-match before deleting an accounting rule."))
        self.unlink()
        configuration._sync_previous_same_report_lines()
        return {"type": "ir.actions.client", "tag": "reload"}

    @api.depends("amount_columns_json")
    def _compute_additional_amount_values(self):
        for record in self:
            values = record.amount_columns_json or {}
            for source, _label in AMOUNT_SOURCE_SELECTION:
                record[f"additional_amount_{source}"] = values.get(source, 0.0) or 0.0

    @api.depends("matched_amount", "posting_indicator", "include_in_voucher")
    def _compute_posting_amounts(self):
        for record in self:
            record.debit_amount = record.matched_amount if record.include_in_voucher and record.posting_indicator == "DR" else 0.0
            record.credit_amount = record.matched_amount if record.include_in_voucher and record.posting_indicator == "CR" else 0.0

    @api.depends(
        "include_in_voucher", "gl_number", "gl_name", "posting_indicator",
        "source_currency", "conversion_type",
    )
    def _compute_configuration_status(self):
        for record in self:
            if not record.include_in_voucher:
                record.configuration_status = "excluded"
            else:
                conversion_ready = (
                    BsrAccountingConfiguration._norm(record.source_currency).upper() != "USD"
                    or bool(record.conversion_type)
                )
                record.configuration_status = (
                    "configured"
                    if record.gl_number and record.gl_name and record.posting_indicator and conversion_ready
                    else "incomplete"
                )

    @api.depends(
        "report_code",
        "record_type",
        "source_particulars",
        "source_entity",
        "clearing_currency",
        "business_mode",
        "transaction_category",
        "transaction_type",
        "description_match",
        "source_direction",
        "amount_source",
        "source_currency",
    )
    def _compute_match_key(self):
        for record in self:
            record.match_key = "|".join(
                BsrAccountingConfiguration._norm(value)
                for value in (
                    record.report_code,
                    record.record_type,
                    record.source_particulars,
                    record.source_entity,
                    record.clearing_currency,
                    record.business_mode,
                    record.transaction_category,
                    record.transaction_type,
                    record.description_match,
                    record.source_direction,
                    record.amount_source,
                    record.source_currency,
                )
            )
