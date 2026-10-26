from odoo import fields, models


class VisaVX705(models.Model):
    _name = "visa.vx.705"
    batch_id = fields.Many2one('visa.import.batch', string='Imported File', index=True, ondelete='cascade', copy=False)
    _description = "Visa VX-705 - Incoming Interchange Sales Drafts"
    _order = "imported_at desc, id desc"

    report_code = fields.Char(
        string="Report Code",
        required=True,
        default="VX-705",
        index=True,
    )

    report_type = fields.Char(
        string="Report Type",
        default="Incoming Interchange",
    )

    report_name = fields.Char(
        string="Report Name",
        default="Sales Drafts",
    )

    system_date = fields.Date(
        string="System Date",
    )

    release = fields.Char(
        string="Release",
    )

    cpd = fields.Char(
        string="CPD",
        help="Central Processing Date as provided by the VX-705 file.",
    )

    bank_name = fields.Char(
        string="Bank Name",
    )

    center = fields.Char(
        string="Center",
    )

    run_number = fields.Char(
        string="Run Number",
    )

    page = fields.Integer(
        string="Page",
    )

    # ============================================================
    # SALES DRAFT INFORMATION
    # ============================================================

    draft_type = fields.Selection(
        selection=[
            ("original", "Sales Draft - Original"),
            ("account_funding", "Account Funding Sales Draft - Original"),
            ("representment_vcr", "Sales Draft - Representment - VCR"),
        ],
        string="Draft Type",
        default="original",
        required=True,
    )

    data_section = fields.Selection(
        selection=[
            ("required", "Required Data"),
            ("additional", "Additional Data"),
            ("payment_service", "Payment Service Data"),
        ],
        string="Data Section",
    )

    # ============================================================
    # REQUIRED DATA
    # ============================================================

    account_number = fields.Char(
        string="Account Number",
        index=True,
    )

    floor_limit_indicator = fields.Char(
        string="Floor Limit Indicator",
    )

    crb_exception_file_indicator = fields.Char(
        string="CRB/Exception File Indicator",
    )

    acquirer_reference_number = fields.Char(
        string="Acquirer Reference Number",
        index=True,
    )

    acquirer_business_id = fields.Char(
        string="Acquirer's Business ID",
    )

    purchase_date = fields.Char(
        string="Purchase Date",
        help="Purchase date as provided by the source file.",
    )

    destination_amount = fields.Monetary(
        string="Destination Amount",
        currency_field="destination_currency_id",
    )

    destination_currency_code = fields.Char(
        string="Destination Currency Code",
    )

    destination_currency_id = fields.Many2one(
        "res.currency",
        string="Destination Currency",
    )

    source_amount = fields.Monetary(
        string="Source Amount",
        currency_field="source_currency_id",
    )

    source_currency_code = fields.Char(
        string="Source Currency Code",
    )

    source_currency_id = fields.Many2one(
        "res.currency",
        string="Source Currency",
    )

    merchant_name = fields.Char(
        string="Merchant Name",
    )

    merchant_city = fields.Char(
        string="Merchant City",
    )

    merchant_country_code = fields.Char(
        string="Merchant Country Code",
    )

    merchant_category_code = fields.Char(
        string="Merchant Category Code",
    )

    merchant_zip_code = fields.Char(
        string="Merchant ZIP Code",
    )

    merchant_state_province_code = fields.Char(
        string="Merchant State/Province Code",
    )

    requested_payment_service = fields.Char(
        string="Requested Payment Service",
    )

    number_of_payment_forms = fields.Integer(
        string="Number of Payment Forms",
    )

    usage_code = fields.Char(
        string="Usage Code",
    )

    chargeback_reason_code = fields.Char(
        string="Chargeback Reason Code",
    )

    settlement_flag = fields.Char(
        string="Settlement Flag",
    )

    auth_characteristics_indicator = fields.Char(
        string="Auth Characteristics Indicator",
    )

    authorization_code = fields.Char(
        string="Authorization Code",
    )

    pos_terminal_capability = fields.Char(
        string="POS Terminal Capability",
    )

    cardholder_id_method = fields.Char(
        string="Cardholder ID Method",
    )

    collection_only_flag = fields.Char(
        string="Collection-Only Flag",
    )

    pos_entry_mode = fields.Char(
        string="POS Entry Mode",
    )

    central_processing_date = fields.Char(
        string="Central Processing Date",
    )

    reimbursement_attribute = fields.Char(
        string="Reimbursement Attribute",
    )

    # ============================================================
    # ADDITIONAL DATA
    # ============================================================

    business_format_code = fields.Char(
        string="Business Format Code",
    )

    token_assurance_method = fields.Char(
        string="Token Assurance Method",
    )

    rate_table_id = fields.Char(
        string="Rate Table ID",
    )

    scheme_identifier = fields.Char(
        string="Scheme Identifier",
    )

    reserved_data = fields.Char(
        string="Reserved Data",
    )

    documentation_indicator = fields.Char(
        string="Documentation Indicator",
    )

    member_message_text = fields.Char(
        string="Member Message Text",
    )

    special_condition_indicator = fields.Char(
        string="Special Condition Indicator",
    )

    fee_program_indicator = fields.Char(
        string="Fee Program Indicator",
    )

    issuer_charge = fields.Char(
        string="Issuer Charge",
    )

    pfx_applied_indicator = fields.Char(
        string="PFX Applied Indicator",
    )

    card_acceptor_id = fields.Char(
        string="Card Acceptor ID",
        index=True,
    )

    terminal_id = fields.Char(
        string="Terminal ID",
        index=True,
    )

    national_reimbursement_fee = fields.Monetary(
        string="National Reimbursement Fee",
        currency_field="destination_currency_id",
    )

    mail_phone_ecommerce_payment_indicator = fields.Char(
        string="Mail/Phn/Ecomm & Pymt Indicator",
    )

    special_chargeback_indicator = fields.Char(
        string="Special Chargeback Indicator",
    )

    conversion_date = fields.Char(
        string="Conversion Date",
    )

    additional_token_response = fields.Char(
        string="Additional Token Response",
    )

    acceptance_terminal_indicator = fields.Char(
        string="Acceptance Terminal Indicator",
    )

    prepaid_card_indicator = fields.Char(
        string="Prepaid Card Indicator",
    )

    service_development_field = fields.Char(
        string="Service Development Field",
    )

    avs_response_code = fields.Char(
        string="AVS Response Code",
    )

    authorization_source_code = fields.Char(
        string="Authorization Source Code",
    )

    purchase_id_format = fields.Char(
        string="Purchase ID Format",
    )

    account_selection = fields.Char(
        string="Account Selection",
    )

    installment_payment_count = fields.Integer(
        string="Installment Payment Count",
    )

    purchase_identifier = fields.Char(
        string="Purchase Identifier",
        index=True,
    )

    cashback = fields.Monetary(
        string="Cashback",
        currency_field="destination_currency_id",
    )

    chip_condition_code = fields.Char(
        string="Chip Condition Code",
    )

    pos_environment = fields.Char(
        string="POS Environment",
    )

    # ============================================================
    # PAYMENT SERVICE DATA
    # ============================================================

    transaction_identifier = fields.Char(
        string="Transaction Identifier",
        index=True,
    )

    authorized_amount = fields.Monetary(
        string="Authorized Amount",
        currency_field="auth_currency_id",
    )

    auth_currency_code = fields.Char(
        string="Auth Currency Code",
    )

    auth_currency_id = fields.Many2one(
        "res.currency",
        string="Auth Currency",
    )

    ecommerce_goods_indicator = fields.Char(
        string="ECommerce Goods Indicator",
    )

    merchant_verification_value = fields.Char(
        string="Merchant Verification Value",
    )

    interchange_fee_amount = fields.Monetary(
        string="Interchange Fee Amount",
        currency_field="auth_currency_id",
    )

    interchange_fee_sign = fields.Char(
        string="Interchange Fee Sign",
    )

    authorization_response_code = fields.Char(
        string="Authorization Response Code",
    )

    validation_code = fields.Char(
        string="Validation Code",
    )

    excluded_transaction_id_reason = fields.Char(
        string="Excluded Transaction ID Reason",
    )

    crs_processing_code = fields.Char(
        string="CRS Processing Code",
    )

    chargeback_rights_indicator = fields.Char(
        string="Chargeback Rights Indicator",
    )

    multiple_clearing_sequence_number = fields.Char(
        string="Multiple Clearing Sequence Number",
    )

    multiple_clearing_sequence_count = fields.Char(
        string="Multiple Clearing Sequence Count",
    )

    market_specific_authorization_data = fields.Char(
        string="Market-Specific Authorization Data",
    )

    total_authorized_amount = fields.Monetary(
        string="Total Authorized Amount",
        currency_field="auth_currency_id",
    )

    information_indicator = fields.Char(
        string="Information Indicator",
    )

    merchant_telephone_number = fields.Char(
        string="Merchant Telephone Number",
    )

    additional_data_indicator = fields.Char(
        string="Additional Data Indicator",
    )

    merchant_volume_indicator = fields.Char(
        string="Merchant Volume Indicator",
    )

    source_to_base_currency_exchange_rate = fields.Float(
        string="Source to Base Currency Exchange Rate",
        digits=(16, 8),
    )

    base_to_destination_currency_exchange_rate = fields.Float(
        string="Base to Destination Currency Exchange Rate",
        digits=(16, 8),
    )

    optional_issuer_isa_amount = fields.Monetary(
        string="Optional Issuer ISA Amount",
        currency_field="auth_currency_id",
    )

    product_id_code = fields.Char(
        string="Product ID",
    )

    program_id = fields.Char(
        string="Program ID",
    )

    dynamic_currency_conversion_indicator = fields.Char(
        string="Dynamic Currency Conversion Indicator",
    )

    account_type_identification = fields.Char(
        string="Account Type Identification",
    )

    spend_qualified_indicator = fields.Char(
        string="Spend Qualified Indicator",
    )

    pan_token = fields.Char(
        string="PAN Token",
    )

    account_funding_source = fields.Char(
        string="Account Funding Source",
    )

    cvv2_result_code = fields.Char(
        string="CVV2 Result Code",
    )

    # ============================================================
    # SYSTEM / IMPORT INFORMATION
    # ============================================================

    source_file_name = fields.Char(
        string="Source File Name",
    )

    source_line_number = fields.Integer(
        string="Source Line Number",
    )

    imported_at = fields.Datetime(
        string="Imported At",
        readonly=True,
    )

    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
    )

    active = fields.Boolean(
        string="Active",
        default=True,
    )

    def get_data(self):
        
        for record in self:
            print("=" * 60)
            print(f"visa.vx.705  ID: {record.id}")
            print("=" * 60)
            for field_name in record._fields:
                print(f"  {field_name}: {record[field_name]}")
            print()
        return True
