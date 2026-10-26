from odoo import _, api, fields, models
from odoo.exceptions import UserError


class NpsbOclImport(models.Model):
    _name = "npsb.ocl.import"
    _description = "NPSB OCL Imported File"
    _order = "imported_at desc, id desc"

    name = fields.Char(string="File Name", required=True, readonly=True)
    file = fields.Binary(string="Original File", attachment=True, readonly=True)
    file_size = fields.Integer(string="File Size (bytes)", readonly=True)
    imported_at = fields.Datetime(default=fields.Datetime.now, readonly=True, index=True)
    imported_by = fields.Many2one(
        "res.users", default=lambda self: self.env.user, readonly=True
    )
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company,
        readonly=True, index=True,
    )
    transaction_ids = fields.One2many(
        "npsb.ocl.transaction", "batch_id", string="Transactions", readonly=True
    )
    record_count = fields.Integer(compute="_compute_record_count", string="Total Records")
    remarks = fields.Text()
    status = fields.Selection(
        [("imported", "Imported")], default="imported", readonly=True
    )

    @api.depends("transaction_ids")
    def _compute_record_count(self):
        for batch in self:
            batch.record_count = len(batch.transaction_ids)

    def action_view_records(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("%s — Transactions") % self.name,
            "res_model": "npsb.ocl.transaction",
            "view_mode": "list,form",
            "domain": [("batch_id", "=", self.id)],
            "context": {"default_batch_id": self.id},
        }

    def action_download_file(self):
        self.ensure_one()
        if not self.file:
            raise UserError(_("No original file is available for this import."))
        return {
            "type": "ir.actions.act_url",
            "url": (
                "/web/content?model=npsb.ocl.import&id=%d&field=file"
                "&filename_field=name&download=true" % self.id
            ),
            "target": "self",
        }


class NpsbOclTransaction(models.Model):
    _name = "npsb.ocl.transaction"
    batch_id = fields.Many2one(
        "npsb.ocl.import", string="Imported File", required=True, index=True,
        ondelete="cascade", copy=False,
    )
    _description = "NPSB OCL Transaction"
    _rec_name = "drn"
    _order = "local_datetime desc, id desc"

    # File header / import metadata
    file_label = fields.Char(string="File Label", index=True)
    format_version = fields.Char(string="Format Version")
    sender = fields.Char(string="Sender", index=True)
    receiver = fields.Char(string="Receiver", index=True)
    creation_date = fields.Date(string="File Creation Date", index=True)
    creation_time = fields.Char(string="File Creation Time")
    file_sequence_number = fields.Char(string="File Sequence Number", index=True)
    source_file_name = fields.Char(string="Source File Name", index=True)
    source_record_number = fields.Integer(string="Source Record Number")
    imported_at = fields.Datetime(string="Imported At", readonly=True, index=True)

    # Transaction type
    msg_code = fields.Char(string="Message Code", index=True)
    fin_category = fields.Char(string="Financial Category")
    request_category = fields.Char(string="Request Category")
    service_class = fields.Char(string="Service Class")
    transaction_type_code = fields.Char(string="Transaction Type Code", index=True)
    transaction_condition = fields.Text(string="Transaction Condition")
    original_transaction_condition = fields.Text(string="Original Transaction Condition")
    dispute_reason_code = fields.Char(string="Dispute Reason Code", index=True)
    dispute_reason_details = fields.Text(string="Dispute Reason Details")

    # Document references
    drn = fields.Char(string="DRN", index=True)
    previous_drn = fields.Char(string="Previous DRN", index=True)
    original_drn = fields.Char(string="Original DRN", index=True)
    summary_drn = fields.Char(string="Summary DRN", index=True)
    srn = fields.Char(string="SRN", index=True)
    irn = fields.Char(string="IRN", index=True)
    rrn = fields.Char(string="RRN", index=True)
    arn = fields.Char(string="ARN", index=True)
    auth_code = fields.Char(string="Authorization Code", index=True)
    trn = fields.Char(string="TRN", index=True)
    reference_parameters = fields.Text(
        string="All Reference Parameters",
        help="JSON snapshot of every ParmCode/Value pair from DocRefSet.",
    )

    # Dates / source details
    local_datetime = fields.Datetime(string="Local Date/Time", index=True)
    network_datetime = fields.Datetime(string="Network Date/Time")
    sic = fields.Char(string="SIC", index=True)
    country = fields.Char(string="Country")
    city = fields.Char(string="City", index=True)
    merchant_name = fields.Char(string="Merchant Name", index=True)
    merchant_id = fields.Char(string="Merchant ID", index=True)

    # Originator
    originator_contract_number = fields.Char(string="Originator Contract Number", index=True)
    originator_member_id = fields.Char(string="Originator Member ID", index=True)
    originator_transit_id = fields.Char(string="Originator Transit ID")
    originator_card_expiry = fields.Char(string="Originator Card Expiry")
    originator_card_sequence = fields.Char(string="Originator Card Sequence")
    originator_channel = fields.Char(string="Originator Channel")

    # Destination
    destination_contract_number = fields.Char(string="Destination Contract Number", index=True)
    destination_relation = fields.Char(string="Destination Relation")
    destination_member_id = fields.Char(string="Destination Member ID", index=True)
    destination_transit_id = fields.Char(string="Destination Transit ID")
    destination_card_expiry = fields.Char(string="Destination Card Expiry")
    destination_card_sequence = fields.Char(string="Destination Card Sequence")
    destination_channel = fields.Char(string="Destination Channel")

    # Transaction / billing / reconciliation
    transaction_currency_code = fields.Char(string="Transaction Currency Code")
    transaction_amount = fields.Float(string="Transaction Amount", digits=(18, 6))
    transaction_amount_raw = fields.Char(string="Transaction Amount (Raw)")
    extra_type = fields.Char(string="Extra Type")
    transaction_code = fields.Char(string="Transaction Code / WHAT_TRX", index=True)
    additional_parameters = fields.Text(
        string="All Additional Parameters",
        help="JSON snapshot of every ParmCode/Value pair from Transaction/Extra/AddData.",
    )

    billing_date = fields.Date(string="Billing Date", index=True)
    billing_currency_code = fields.Char(string="Billing Currency Code")
    billing_amount = fields.Float(string="Billing Amount", digits=(18, 6))
    billing_amount_raw = fields.Char(string="Billing Amount (Raw)")

    reconciliation_date = fields.Date(string="Reconciliation Date", index=True)
    reconciliation_currency_code = fields.Char(string="Reconciliation Currency Code")
    reconciliation_amount = fields.Float(string="Reconciliation Amount", digits=(18, 6))
    reconciliation_amount_raw = fields.Char(string="Reconciliation Amount (Raw)")

    original_transaction_datetime = fields.Datetime(string="Original Transaction Date/Time")

    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    active = fields.Boolean(default=True)
