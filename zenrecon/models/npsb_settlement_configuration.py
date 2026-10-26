# -*- coding: utf-8 -*-
from collections import defaultdict

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


FILTER_FIELDS = {
    "transaction_date": "transaction_date",
    "settlement_date": "settlement_date",
    "business_mode": "issuer_acquirer",
    "delivery_channel": "delivery_channel",
    "transaction_type": "trans_type",
}
AMOUNT_FIELDS = {
    "trans_amount": "Transaction Amount",
    "fees_irf_amount": "Fees/IRF",
    "platform_fee": "Platform Fee",
    "net_amount": "Net Amount",
}
BLANK_KEY = "__blank__"


class NpsbSettlementFilterOption(models.Model):
    _name = "npsb.settlement.filter.option"
    _description = "NPSB Settlement Filter Option"
    _order = "field_name, is_blank desc, name, id"

    report_id = fields.Many2one(
        "npsb.settlement.report", required=True, ondelete="cascade", index=True
    )
    company_id = fields.Many2one(related="report_id.company_id", store=True, index=True)
    field_name = fields.Selection(
        [
            ("transaction_date", "Transaction Business Date"),
            ("settlement_date", "Settlement Business Date"),
            ("business_mode", "Business Mode"),
            ("delivery_channel", "Delivery Channel"),
            ("transaction_type", "Transaction Type"),
        ],
        required=True,
        index=True,
    )
    value = fields.Char()
    value_key = fields.Char(required=True, index=True)
    name = fields.Char(required=True, index=True)
    is_blank = fields.Boolean(default=False, index=True)

    _report_field_value_unique = models.Constraint(
        "UNIQUE(report_id, field_name, value_key)",
        "Each filter value must be unique within an NPSB settlement report.",
    )


class NpsbSettlementConfiguration(models.Model):
    _name = "npsb.settlement.configuration"
    _description = "NPSB Settlement Configuration"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc, id desc"
    _check_company_auto = True

    name = fields.Char(default=lambda self: _("New"), required=True, copy=False, tracking=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company,
        index=True, tracking=True,
    )
    source_report_id = fields.Many2one(
        "npsb.settlement.report",
        string="Processed Settlement Report",
        required=True,
        ondelete="restrict",
        check_company=True,
        domain="[('company_id', '=', company_id), ('state', '=', 'processed')]",
        tracking=True,
    )

    transaction_date_option_ids = fields.Many2many(
        "npsb.settlement.filter.option", "npsb_config_tx_date_option_rel",
        "configuration_id", "option_id", string="Transaction Business Date", copy=True,
    )
    settlement_date_option_ids = fields.Many2many(
        "npsb.settlement.filter.option", "npsb_config_st_date_option_rel",
        "configuration_id", "option_id", string="Settlement Business Date", copy=True,
    )
    business_mode_option_ids = fields.Many2many(
        "npsb.settlement.filter.option", "npsb_config_business_mode_option_rel",
        "configuration_id", "option_id", string="Business Mode", copy=True,
    )
    delivery_channel_option_ids = fields.Many2many(
        "npsb.settlement.filter.option", "npsb_config_delivery_channel_option_rel",
        "configuration_id", "option_id", string="Delivery Channel", copy=True,
    )
    transaction_type_option_ids = fields.Many2many(
        "npsb.settlement.filter.option", "npsb_config_transaction_type_option_rel",
        "configuration_id", "option_id", string="Transaction Type", copy=True,
    )

    amount_trans_amount = fields.Boolean(string="Transaction Amount", default=True, tracking=True)
    amount_fees_irf = fields.Boolean(string="Fees/IRF", default=True, tracking=True)
    amount_platform_fee = fields.Boolean(string="Platform Fee", default=True, tracking=True)
    amount_net_amount = fields.Boolean(string="Net Amount", default=True, tracking=True)

    line_ids = fields.One2many(
        "npsb.settlement.configuration.line", "configuration_id",
        string="Accounting Rules", copy=True,
    )
    state = fields.Selection(
        [("draft", "Draft"), ("matched", "Source Matched"), ("ready", "Ready")],
        default="draft", required=True, tracking=True, index=True,
    )
    source_row_count = fields.Integer(compute="_compute_counts")
    rule_count = fields.Integer(compute="_compute_counts")
    incomplete_count = fields.Integer(compute="_compute_counts")
    preview_debit_total = fields.Float(compute="_compute_totals", digits=(20, 2))
    preview_credit_total = fields.Float(compute="_compute_totals", digits=(20, 2))
    preview_difference = fields.Float(compute="_compute_totals", digits=(20, 2))
    is_preview_balanced = fields.Boolean(compute="_compute_totals")
    validation_message = fields.Text(readonly=True)
    matched_at = fields.Datetime(readonly=True)
    matched_by_id = fields.Many2one("res.users", readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("npsb.settlement.configuration")
                    or _("New")
                )
        records = super().create(vals_list)
        records._ensure_filter_options()
        return records

    @api.depends("line_ids", "line_ids.source_row_count", "line_ids.configuration_status")
    def _compute_counts(self):
        for record in self:
            record.source_row_count = sum(record.line_ids.mapped("source_row_count"))
            record.rule_count = len(record.line_ids)
            record.incomplete_count = len(
                record.line_ids.filtered(lambda line: line.configuration_status == "incomplete")
            )

    @api.depends(
        "line_ids.debit_amount", "line_ids.credit_amount", "line_ids.include_in_voucher"
    )
    def _compute_totals(self):
        for record in self:
            included = record.line_ids.filtered("include_in_voucher")
            debit = sum(included.mapped("debit_amount"))
            credit = sum(included.mapped("credit_amount"))
            record.preview_debit_total = debit
            record.preview_credit_total = credit
            record.preview_difference = debit - credit
            record.is_preview_balanced = abs(debit - credit) < 0.01

    @staticmethod
    def _value_key(value):
        if value in (False, None, ""):
            return BLANK_KEY
        if hasattr(value, "isoformat"):
            value = value.isoformat()
        return str(value).strip().casefold()

    @staticmethod
    def _display_value(value):
        if value in (False, None, ""):
            return "(Blank)"
        return fields.Date.to_string(value) if hasattr(value, "isoformat") else str(value).strip()

    def _ensure_filter_options(self):
        Option = self.env["npsb.settlement.filter.option"]
        for record in self.filtered("source_report_id"):
            source_lines = self.env["npsb.settlement.summary.line"].search([
                ("report_id", "=", record.source_report_id.id),
            ])
            existing_options = Option.search([("report_id", "=", record.source_report_id.id)])
            existing = {(option.field_name, option.value_key): option for option in existing_options}
            desired = {}
            for filter_name, source_field in FILTER_FIELDS.items():
                for value in source_lines.mapped(source_field):
                    key = record._value_key(value)
                    desired[(filter_name, key)] = value

            stale = existing_options.filtered(
                lambda option: (option.field_name, option.value_key) not in desired
            )
            if stale:
                stale.unlink()

            values_list = []
            for (filter_name, key), value in desired.items():
                if (filter_name, key) in existing:
                    continue
                values_list.append({
                    "report_id": record.source_report_id.id,
                    "field_name": filter_name,
                    "value": False if key == BLANK_KEY else record._display_value(value),
                    "value_key": key,
                    "name": record._display_value(value),
                    "is_blank": key == BLANK_KEY,
                })
            if values_list:
                Option.create(values_list)

    def _reset_for_source_change(self):
        if not self:
            return
        self.mapped("line_ids").unlink()
        self.write({
            "transaction_date_option_ids": [(5, 0, 0)],
            "settlement_date_option_ids": [(5, 0, 0)],
            "business_mode_option_ids": [(5, 0, 0)],
            "delivery_channel_option_ids": [(5, 0, 0)],
            "transaction_type_option_ids": [(5, 0, 0)],
            "state": "draft",
            "validation_message": _("Source report changed. Review filters and match the Summary data again."),
            "matched_at": False,
            "matched_by_id": False,
        })
        self._ensure_filter_options()

    @api.onchange("source_report_id")
    def _onchange_source_report_id(self):
        for record in self:
            record.transaction_date_option_ids = False
            record.settlement_date_option_ids = False
            record.business_mode_option_ids = False
            record.delivery_channel_option_ids = False
            record.transaction_type_option_ids = False
            record.line_ids = [(5, 0, 0)]
            record.state = "draft"
            if record.source_report_id:
                record._ensure_filter_options()

    @api.constrains(
        "transaction_date_option_ids", "settlement_date_option_ids",
        "business_mode_option_ids", "delivery_channel_option_ids",
        "transaction_type_option_ids",
    )
    def _check_filter_report(self):
        for record in self:
            options = (
                record.transaction_date_option_ids
                | record.settlement_date_option_ids
                | record.business_mode_option_ids
                | record.delivery_channel_option_ids
                | record.transaction_type_option_ids
            )
            if options.filtered(lambda option: option.report_id != record.source_report_id):
                raise ValidationError(_("Filter values must belong to the selected settlement report."))

    def _selected_amount_fields(self):
        self.ensure_one()
        selected = []
        if self.amount_trans_amount:
            selected.append("trans_amount")
        if self.amount_fees_irf:
            selected.append("fees_irf_amount")
        if self.amount_platform_fee:
            selected.append("platform_fee")
        if self.amount_net_amount:
            selected.append("net_amount")
        return selected

    def _matches_filters(self, line, include_source_dates=True):
        """Match Summary dimensions.

        Source dates are useful while designing a configuration from a sample
        report. Voucher runs deliberately ignore them because their own dates
        already select the authoritative daily report.
        """
        self.ensure_one()
        if (
            not self.transaction_type_option_ids
            and str(line.trans_type or "").replace(" ", "").casefold()
            in {"subtotal", "grandtotal"}
        ):
            return False
        selections = {
            "transaction_date": self.transaction_date_option_ids,
            "settlement_date": self.settlement_date_option_ids,
            "business_mode": self.business_mode_option_ids,
            "delivery_channel": self.delivery_channel_option_ids,
            "transaction_type": self.transaction_type_option_ids,
        }
        for filter_name, options in selections.items():
            if not include_source_dates and filter_name in {
                "transaction_date", "settlement_date",
            }:
                continue
            if not options:
                continue
            actual = line[FILTER_FIELDS[filter_name]]
            if self._value_key(actual) not in set(options.mapped("value_key")):
                return False
        return True

    def action_match_source(self):
        self.ensure_one()
        self._ensure_filter_options()
        amount_fields = self._selected_amount_fields()
        if not amount_fields:
            raise UserError(_("Select at least one amount column."))

        source_lines = self.env["npsb.settlement.summary.line"].search([
            ("report_id", "=", self.source_report_id.id),
        ]).filtered(self._matches_filters)
        if not source_lines:
            raise UserError(_("No Summary rows match the selected NPSB filters."))

        previous = {line.match_key: line for line in self.line_ids}
        grouped = defaultdict(lambda: {"amount": 0.0, "count": 0, "source_ids": []})
        for source in source_lines:
            dimensions = (
                source.issuer_acquirer or "",
                source.delivery_channel or "",
                source.trans_type or "",
            )
            for amount_field in amount_fields:
                amount = abs(source[amount_field] or 0.0)
                if not amount:
                    continue
                key = (*dimensions, amount_field)
                grouped[key]["amount"] += amount
                grouped[key]["count"] += 1
                grouped[key]["source_ids"].append(str(source.id))

        if not grouped:
            raise UserError(_("Matched Summary rows contain no non-zero values in the selected amount columns."))

        values_list = []
        for sequence, (key, totals) in enumerate(sorted(grouped.items()), 1):
            business_mode, channel, transaction_type, amount_source = key
            match_key = "|".join(str(value).strip().casefold() for value in key)
            old = previous.get(match_key)
            values_list.append({
                "configuration_id": self.id,
                "sequence": sequence * 10,
                "business_mode": business_mode or False,
                "delivery_channel": channel or False,
                "transaction_type": transaction_type or False,
                "amount_source": amount_source,
                "matched_amount": totals["amount"],
                "source_row_count": totals["count"],
                "source_record_ids": ",".join(totals["source_ids"]),
                "include_in_voucher": old.include_in_voucher if old else True,
                "posting_indicator": old.posting_indicator if old else False,
                "gl_number": old.gl_number if old else False,
                "gl_name": old.gl_name if old else False,
                "debit_remarks": old.debit_remarks if old else False,
                "credit_remarks": old.credit_remarks if old else False,
            })

        self.line_ids.unlink()
        self.env["npsb.settlement.configuration.line"].create(values_list)
        self.write({
            "state": "matched",
            "matched_at": fields.Datetime.now(),
            "matched_by_id": self.env.user.id,
            "validation_message": _(
                "%s accounting rule(s) created from %s matching Summary row(s). Complete DR/CR and GL mapping."
            ) % (len(values_list), len(source_lines)),
        })
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("NPSB source matched"),
                "message": self.validation_message,
                "type": "success",
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }

    def action_validate(self):
        self.ensure_one()
        included = self.line_ids.filtered("include_in_voucher")
        if not included:
            raise UserError(_("Keep at least one accounting rule enabled."))
        incomplete = included.filtered(lambda line: line.configuration_status == "incomplete")
        if incomplete:
            raise UserError(_("%s included rule(s) still require DR/CR, GL Number, and GL Name.") % len(incomplete))
        self.write({
            "state": "ready",
            "validation_message": _("Configuration is complete and ready for settlement output."),
        })
        return {"type": "ir.actions.client", "tag": "reload"}

    def action_reset_draft(self):
        self.write({"state": "draft", "validation_message": False})
        return {"type": "ir.actions.client", "tag": "reload"}


class NpsbSettlementConfigurationLine(models.Model):
    _name = "npsb.settlement.configuration.line"
    _description = "NPSB Settlement Accounting Rule"
    _order = "configuration_id desc, sequence, id"
    _check_company_auto = True

    sequence = fields.Integer(default=10, index=True)
    configuration_id = fields.Many2one(
        "npsb.settlement.configuration", required=True, ondelete="cascade",
        index=True, check_company=True,
    )
    company_id = fields.Many2one(related="configuration_id.company_id", store=True, index=True)
    source_report_id = fields.Many2one(
        related="configuration_id.source_report_id", store=True, index=True,
        string="Settlement Report",
    )
    configuration_state = fields.Selection(related="configuration_id.state", store=True)
    business_mode = fields.Char(readonly=True, index=True)
    delivery_channel = fields.Char(readonly=True, index=True)
    transaction_type = fields.Char(readonly=True, index=True)
    amount_source = fields.Selection(
        [(key, label) for key, label in AMOUNT_FIELDS.items()],
        string="Source Amount", required=True, readonly=True, index=True,
    )
    matched_amount = fields.Float(readonly=True, digits=(20, 2))
    include_in_voucher = fields.Boolean(string="Use", default=True, index=True)
    posting_indicator = fields.Selection(
        [("DR", "DR"), ("CR", "CR")], string="DR/CR", index=True,
    )
    debit_amount = fields.Float(compute="_compute_posting_amounts", store=True, digits=(20, 2))
    credit_amount = fields.Float(compute="_compute_posting_amounts", store=True, digits=(20, 2))
    gl_number = fields.Char(string="GL Number", index=True)
    gl_name = fields.Char(string="GL Name")
    debit_remarks = fields.Text(string="Debit Remarks")
    credit_remarks = fields.Text(string="Credit Remarks")
    source_row_count = fields.Integer(readonly=True)
    source_record_ids = fields.Text(readonly=True)
    match_key = fields.Char(compute="_compute_match_key", store=True, index=True)
    configuration_status = fields.Selection(
        [("configured", "Configured"), ("incomplete", "Needs GL"), ("excluded", "Excluded")],
        compute="_compute_configuration_status", store=True, index=True,
    )

    _configuration_match_key_unique = models.Constraint(
        "UNIQUE(configuration_id, match_key)",
        "The same NPSB accounting rule cannot be added twice.",
    )

    @api.depends("matched_amount", "posting_indicator", "include_in_voucher")
    def _compute_posting_amounts(self):
        for line in self:
            line.debit_amount = (
                line.matched_amount
                if line.include_in_voucher and line.posting_indicator == "DR" else 0.0
            )
            line.credit_amount = (
                line.matched_amount
                if line.include_in_voucher and line.posting_indicator == "CR" else 0.0
            )

    @api.depends("include_in_voucher", "posting_indicator", "gl_number", "gl_name")
    def _compute_configuration_status(self):
        for line in self:
            if not line.include_in_voucher:
                line.configuration_status = "excluded"
            elif line.posting_indicator and line.gl_number and line.gl_name:
                line.configuration_status = "configured"
            else:
                line.configuration_status = "incomplete"

    @api.depends("business_mode", "delivery_channel", "transaction_type", "amount_source")
    def _compute_match_key(self):
        for line in self:
            line.match_key = "|".join(
                str(value or "").strip().casefold()
                for value in (
                    line.business_mode, line.delivery_channel,
                    line.transaction_type, line.amount_source,
                )
            )
