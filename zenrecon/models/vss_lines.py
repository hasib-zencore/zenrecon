# -*- coding: utf-8 -*-
from odoo import api, fields, models


REPORT_SELECTION = [
    ("VSS-110", "VSS-110"),
    ("VSS-120", "VSS-120"),
    ("VSS-130", "VSS-130"),
    ("VSS-140", "VSS-140"),
    ("VSS-210", "VSS-210"),
]
DIRECTION_SELECTION = [("CR", "CR"), ("DB", "DB")]
RECORD_TYPE_SELECTION = [("detail", "DETAIL"), ("total", "TOTAL"), ("net", "NET")]
BUSINESS_MODE_SELECTION = [("ACQUIRER", "Acquirer"), ("ISSUER", "Issuer"), ("OTHER", "Other")]


class BsrVssLineMixin(models.AbstractModel):
    """Common source/header columns repeated on every parsed report row.

    The business requirement is one consolidated table per VSS report type *per
    imported text file*.  Header values from each source VSS block are therefore
    stored on every extracted row, exactly like the user's reference spreadsheet.

    ``report_id`` is retained only for upgrade compatibility with the earlier
    prototype.  New processing does not create logical report records.
    """

    _name = "bsr.vss.line.mixin"
    _description = "VSS Consolidated Parsed Line Mixin"

    # Direct owner of the consolidated table row.
    import_id = fields.Many2one("bsr.vss.import", ondelete="cascade", index=True)
    attachment_id = fields.Many2one(related="import_id.attachment_id", store=True, index=True)
    company_id = fields.Many2one(related="import_id.company_id", store=True, index=True)

    # Legacy prototype link. Kept nullable so existing databases can be upgraded
    # without dropping historical prototype data.
    report_id = fields.Many2one("bsr.vss.report", ondelete="set null", index=True)

    # Consolidated-row ordering and audit traceability.
    sequence = fields.Integer(string="SL#", default=10, index=True)
    source_report_sequence = fields.Integer(string="Source Report #", index=True)
    source_page = fields.Integer(string="Page", index=True)
    source_line_no = fields.Integer(index=True)
    raw_source_line = fields.Text(readonly=True)

    # Repeated report header/context columns.
    report_code = fields.Selection(REPORT_SELECTION, string="Report ID", index=True)
    report_name = fields.Char(string="Report Name", index=True)
    service_name = fields.Char(string="Service Name", index=True)

    reporting_for_ref = fields.Char(string="Reporting For ID", index=True)
    reporting_for_name = fields.Char(string="Reporting For Name", index=True)
    reporting_for_display = fields.Char(string="Reporting For", index=True)

    rollup_to_ref = fields.Char(string="Rollup To ID", index=True)
    rollup_to_name = fields.Char(string="Rollup To Name")
    rollup_to_display = fields.Char(string="Rollup To", index=True)

    funds_xfer_entity_ref = fields.Char(string="Funds Xfer Entity ID", index=True)
    funds_xfer_entity_name = fields.Char(string="Funds Xfer Entity Name")
    funds_xfer_entity_display = fields.Char(string="Funds Xfer Entity", index=True)

    settlement_currency = fields.Char(string="Settlement Currency", index=True)
    processing_date = fields.Date(string="Production Date", index=True)
    report_date = fields.Date(string="Report Date", index=True)


class BsrVss110Line(models.Model):
    _name = "bsr.vss.110.line"
    _description = "VSS-110 Consolidated Settlement Summary"
    _inherit = "bsr.vss.line.mixin"
    _order = "import_id desc, sequence, id"

    particulars = fields.Char(required=True, index=True)
    entity = fields.Char(required=True, index=True)
    count = fields.Integer()
    count_display = fields.Char(string="Count", compute="_compute_count_display", store=True)
    credit_amount = fields.Float(digits=(20, 2))
    debit_amount = fields.Float(digits=(20, 2))
    total_amount = fields.Float(digits=(20, 2))
    direction = fields.Selection(DIRECTION_SELECTION, string="CR/DB", index=True)
    record_type = fields.Selection(RECORD_TYPE_SELECTION, required=True, default="detail", index=True)

    @api.depends("particulars", "count")
    def _compute_count_display(self):
        # VSS-110 prints COUNT only for INTERCHANGE VALUE. A blank is not the
        # same as a numeric zero, so the display field preserves that distinction.
        for rec in self:
            rec.count_display = str(rec.count or 0) if rec.particulars == "INTERCHANGE VALUE" else ""


class BsrVss120Line(models.Model):
    _name = "bsr.vss.120.line"
    _description = "VSS-120 Consolidated Interchange Value"
    _inherit = "bsr.vss.line.mixin"
    _order = "import_id desc, sequence, id"

    clearing_currency = fields.Char(index=True)
    business_mode = fields.Selection(BUSINESS_MODE_SELECTION, index=True)
    transaction_category = fields.Char(index=True)
    transaction_type = fields.Char(index=True)
    disposition = fields.Char(index=True)
    currency_table_date = fields.Date(index=True)
    count = fields.Integer()
    clearing_amount = fields.Float(digits=(20, 2))
    clearing_direction = fields.Selection(DIRECTION_SELECTION, string="Clearing CR/DB", index=True)
    interchange_credit = fields.Float(digits=(20, 2))
    interchange_debit = fields.Float(digits=(20, 2))
    record_type = fields.Selection(RECORD_TYPE_SELECTION, required=True, default="detail", index=True)


class BsrVss130Line(models.Model):
    _name = "bsr.vss.130.line"
    _description = "VSS-130 Consolidated Reimbursement Fees"
    _inherit = "bsr.vss.line.mixin"
    _order = "import_id desc, sequence, id"

    business_mode = fields.Selection(BUSINESS_MODE_SELECTION, index=True)
    transaction_category = fields.Char(index=True)
    transaction_type = fields.Char(index=True)
    program_network = fields.Char(index=True)
    region_country = fields.Char(index=True)
    fee_category = fields.Char(index=True)
    description = fields.Char(required=True, index=True)
    count = fields.Integer()
    interchange_amount = fields.Float(digits=(20, 2))
    interchange_direction = fields.Selection(DIRECTION_SELECTION, string="Interchange CR/DB", index=True)
    fee_credit = fields.Float(string="Reimbursement Fee Credit", digits=(20, 2))
    fee_debit = fields.Float(string="Reimbursement Fee Debit", digits=(20, 2))
    record_type = fields.Selection(RECORD_TYPE_SELECTION, required=True, default="detail", index=True)


class BsrVss140Line(models.Model):
    _name = "bsr.vss.140.line"
    _description = "VSS-140 Consolidated Visa Charges"
    _inherit = "bsr.vss.line.mixin"
    _order = "import_id desc, sequence, id"

    business_mode = fields.Selection(BUSINESS_MODE_SELECTION, index=True)
    charge_category = fields.Char(index=True)
    transaction_category = fields.Char(index=True)
    transaction_type = fields.Char(index=True)
    program_network = fields.Char(index=True)
    region_country = fields.Char(index=True)
    description = fields.Char(required=True, index=True)
    count = fields.Integer()
    interchange_amount = fields.Float(digits=(20, 2))
    interchange_direction = fields.Selection(DIRECTION_SELECTION, string="Interchange CR/DB", index=True)
    visa_charge_credit = fields.Float(digits=(20, 2))
    visa_charge_debit = fields.Float(digits=(20, 2))
    record_type = fields.Selection(RECORD_TYPE_SELECTION, required=True, default="detail", index=True)


class BsrVss210Line(models.Model):
    _name = "bsr.vss.210.line"
    _description = "VSS-210 Consolidated Currency Conversion Fees"
    _inherit = "bsr.vss.line.mixin"
    _order = "import_id desc, sequence, id"

    clearing_currency = fields.Char(index=True)
    business_mode = fields.Selection(BUSINESS_MODE_SELECTION, index=True)
    transaction_category = fields.Char(index=True)
    transaction_type = fields.Char(index=True)
    program_network = fields.Char(index=True)
    description = fields.Char(required=True, index=True)
    settlement_interchange_amount = fields.Float(digits=(20, 2))
    settlement_interchange_direction = fields.Selection(
        DIRECTION_SELECTION, string="Settlement Interchange CR/DB", index=True
    )
    settlement_conversion_fee = fields.Float(digits=(20, 2))
    clearing_interchange_amount = fields.Float(digits=(20, 2))
    clearing_interchange_direction = fields.Selection(
        DIRECTION_SELECTION, string="Clearing Interchange CR/DB", index=True
    )
    clearing_conversion_fee = fields.Float(digits=(20, 2))
    optional_issuer_fee = fields.Float(digits=(20, 2))
    optional_issuer_fee_direction = fields.Selection(
        DIRECTION_SELECTION, string="Optional Issuer Fee CR/DB", index=True
    )
    record_type = fields.Selection(RECORD_TYPE_SELECTION, required=True, default="detail", index=True)
