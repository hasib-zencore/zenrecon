import re
from datetime import datetime


REPORT_CODE = "VX-727"
REPORT_TYPE = "Incoming Interchange"
REPORT_NAME = "Cash Disbursement Reversals"


REQUIRED_DATA_LABELS = {
    "Account Number": "account_number",
    "Floor Limit Indicator": "floor_limit_indicator",
    "CRB/Exception File Ind": "crb_exception_file_indicator",
    "Acquirer Reference Nbr": "acquirer_reference_number",
    "Acquirer's Business ID": "acquirer_business_id",
    "Purchase Date": "purchase_date",
    "Destination Amount": "destination_amount",
    "Destination Currency Code": "destination_currency_code",
    "Source Amount": "source_amount",
    "Source Currency Code": "source_currency_code",
    "Merchant Name": "merchant_name",
    "Merchant City": "merchant_city",
    "Merchant Country Code": "merchant_country_code",
    "Merchant Category Code": "merchant_category_code",
    "Merchant ZIP Code": "merchant_zip_code",
    "Merchant State/Prov. Code": "merchant_state_province_code",
    "Requested Payment Service": "requested_payment_service",
    "Number of Payment Forms": "number_of_payment_forms",
    "Usage Code": "usage_code",
    "Chargeback Reason Code": "chargeback_reason_code",
    "Settlement Flag": "settlement_flag",
    "Auth Characteristics Ind": "auth_characteristics_indicator",
    "Authorization Code": "authorization_code",
    "POS Terminal Capability": "pos_terminal_capability",
    "Cardholder ID Method": "cardholder_id_method",
    "Collection-Only Flag": "collection_only_flag",
    "POS Entry Mode": "pos_entry_mode",
    "Central Processing Date": "central_processing_date",
    "Reimbursement Attribute": "reimbursement_attribute",
}


ADDITIONAL_DATA_LABELS = {
    "Business Format Code": "business_format_code",
    "Token Assurance Method": "token_assurance_method",
    "Rate Table ID": "rate_table_id",
    "Scheme Identifier": "scheme_identifier",
    "Reserved Data": "reserved_data",
    "Documentation Indicator": "documentation_indicator",
    "Member Message Text": "member_message_text",
    "Special Condition Ind": "special_condition_indicator",
    "Fee Program Indicator": "fee_program_indicator",
    "Issuer Charge": "issuer_charge",
    "PFX Applied Indicator": "pfx_applied_indicator",
    "Card Acceptor ID": "card_acceptor_id",
    "Terminal ID": "terminal_id",
    "Nat'l Reimbursement Fee": "national_reimbursement_fee",
    "Mail/Phn/Ecomm & Pymt Ind": "mail_phone_ecommerce_payment_indicator",
    "Special Chargeback Ind": "special_chargeback_indicator",
    "Conversion Date": "conversion_date",
    "Additional Token Response": "additional_token_response",
    "Acceptance Terminal Ind": "acceptance_terminal_indicator",
    "Prepaid Card Indicator": "prepaid_card_indicator",
    "Service Development Field": "service_development_field",
    "AVS Response Code": "avs_response_code",
    "Authorization Source Code": "authorization_source_code",
    "Purchase Id Format": "purchase_id_format",
    "Account Selection": "account_selection",
    "Installment Payment Count": "installment_payment_count",
    "Purchase Identifier": "purchase_identifier",
    "Cashback": "cashback",
    "Chip Condition Code": "chip_condition_code",
    "POS Environment": "pos_environment",
}


PAYMENT_SERVICE_LABELS = {
    "Transaction Identifier": "transaction_identifier",
    "Authorized Amount": "authorized_amount",
    "Auth Currency Cd": "auth_currency_code",
    "ECommerce Goods Indicator": "ecommerce_goods_indicator",
    "Merchant Verification Val": "merchant_verification_value",
    "Merchant Verification Value": "merchant_verification_value",
    "Interchange Fee Amount": "interchange_fee_amount",
    "Interchange Fee Sign": "interchange_fee_sign",
    "Authorization Response Code": "authorization_response_code",
    "Validation Code": "validation_code",
    "Excluded Trans ID Rsn": "excluded_transaction_id_reason",
    "Excluded Transaction ID Reason": "excluded_transaction_id_reason",
    "CRS Processing Code": "crs_processing_code",
    "Chargeback Rights Ind": "chargeback_rights_indicator",
    "Chargeback Rights Indicator": "chargeback_rights_indicator",
    "Multiple Clearing Seq Nbr": "multiple_clearing_sequence_number",
    "Multiple Clearing Sequence Number": "multiple_clearing_sequence_number",
    "Multiple Clearing Seq Cnt": "multiple_clearing_sequence_count",
    "Multiple Clearing Sequence Count": "multiple_clearing_sequence_count",
    "Market-Specific Auth Data": "market_specific_authorization_data",
    "Market-Specific Authorization Data": "market_specific_authorization_data",
    "Total Authorized Amount": "total_authorized_amount",
    "Information Indicator": "information_indicator",
    "Merchant Telephone Number": "merchant_telephone_number",
    "Additional Data Indicator": "additional_data_indicator",
    "Merchant Volume Indicator": "merchant_volume_indicator",
    "Src to Base Curr Ex Rate": "source_to_base_currency_exchange_rate",
    "Source to Base Currency Exchange Rate": "source_to_base_currency_exchange_rate",
    "Base to Dest Curr Ex Rate": "base_to_destination_currency_exchange_rate",
    "Base to Destination Currency Exchange Rate": "base_to_destination_currency_exchange_rate",
    "Optional Issuer ISA Amt": "optional_issuer_isa_amount",
    "Optional Issuer ISA Amount": "optional_issuer_isa_amount",
    "Product Id": "product_id_code",
    "Product ID": "product_id_code",
    "Program ID": "program_id",
    "Dynamic Currency Conv Ind": "dynamic_currency_conversion_indicator",
    "Dynamic Currency Conversion Indicator": "dynamic_currency_conversion_indicator",
    "Acct Type Identification": "account_type_identification",
    "Account Type Identification": "account_type_identification",
    "Spend Qualified Indicator": "spend_qualified_indicator",
    "PAN Token": "pan_token",
    "Account Funding Source": "account_funding_source",
    "CVV2 Result Code": "cvv2_result_code",
}


CHIP_CARD_LABELS = {
    "Transaction Type": "transaction_type",
    "Card Sequence Number": "card_sequence_number",
    "Terminal Transaction Date": "terminal_transaction_date",
    "Terminal Capability Prof.": "terminal_capability_profile",
    "Terminal Country Code": "terminal_country_code",
    "Terminal Serial Number": "terminal_serial_number",
    "Unpredictable Number": "unpredictable_number",
    "Appl Transaction Counter": "application_transaction_counter",
    "Appl Interchange Profile": "application_interchange_profile",
    "Cryptogram": "cryptogram",
    "Iss Appl Data, Byte 2": "issuer_application_data_byte_2",
    "Iss Appl Data, Byte 3": "issuer_application_data_byte_3",
    "Term Verification Results": "terminal_verification_results",
    "Iss Appl Data, Byte 4-7": "issuer_application_data_byte_4_7",
    "Cryptogram Amount": "cryptogram_amount",
    "Iss Appl Data, Byte 8": "issuer_application_data_byte_8",
    "Iss Appl Data, Byte 9-16": "issuer_application_data_byte_9_16",
    "Iss Appl Data, Byte 1": "issuer_application_data_byte_1",
    "Iss Appl Data, Byte 17": "issuer_application_data_byte_17",
    "Iss Appl Data, Byte 18-32": "issuer_application_data_byte_18_32",
    "Form Factor Indicator": "form_factor_indicator",
    "Issuer Script 1 Results": "issuer_script_1_results",
}

ALL_SECTION_LABELS = {
    "required": REQUIRED_DATA_LABELS,
    "additional": ADDITIONAL_DATA_LABELS,
    "payment_service": PAYMENT_SERVICE_LABELS,
    "chip_card": CHIP_CARD_LABELS,
}

INTEGER_FIELDS = {
    "page",
    "number_of_payment_forms",
    "installment_payment_count",
    "source_line_number",
}

MONETARY_FIELDS = {
    "destination_amount",
    "source_amount",
    "national_reimbursement_fee",
    "cashback",
    "authorized_amount",
    "interchange_fee_amount",
    "total_authorized_amount",
    "optional_issuer_isa_amount",
}

FLOAT_FIELDS = {
    "source_to_base_currency_exchange_rate",
    "base_to_destination_currency_exchange_rate",
}

REPORT_CODE_RE = re.compile(r"\bREPORT\s+(VX-\d+)\b", re.IGNORECASE)

HEADER_PATTERNS = {
    "system_date": re.compile(r"SYSTEM DATE\s+(\S+)", re.IGNORECASE),
    "release": re.compile(r"RELEASE\s+(\S+)", re.IGNORECASE),
    "cpd": re.compile(r"CPD\s+(\S+)", re.IGNORECASE),
    "bank_name": re.compile(
        r"^\s*([A-Z][A-Z0-9 .,&'/-]*?)\s{2,}CENTER",
        re.MULTILINE,
    ),
    "center": re.compile(r"CENTER\s+(\S+)", re.IGNORECASE),
    "run_number": re.compile(r"RUN\s*NO\.?\s+(\S+)", re.IGNORECASE),
    "page": re.compile(r"PAGE\s+(\d+)", re.IGNORECASE),
}

# VX-727 uses Reversal, Cash Disbursement - First Presentment across four data sections.
SECTION_HEADER_RE = re.compile(
    r"(Reversal, Cash Disbursement - First Presentment)"
    r".*?----\s*"
    r"(Required Data|Additional Data|Payment Service Data|Chip Card Transaction Data)",
    re.IGNORECASE,
)

SECTION_KEY = {
    "required data": "required",
    "additional data": "additional",
    "payment service data": "payment_service",
    "chip card transaction data": "chip_card",
}

DRAFT_TYPE_KEY = {
    "reversal, cash disbursement - first presentment": "first_presentment",
}


def _default_header():
    return {
        "report_code": REPORT_CODE,
        "report_type": REPORT_TYPE,
        "report_name": REPORT_NAME,
    }


def _update_header_from_line(header, line):
    """Update page/header values while the parser moves through a multi-page file."""
    report_match = REPORT_CODE_RE.search(line)
    if report_match:
        header["report_code"] = report_match.group(1).upper()

    for field_name, pattern in HEADER_PATTERNS.items():
        match = pattern.search(line)
        if not match:
            continue
        value = match.group(1).strip()
        if field_name == "page":
            value = int(value)
        header[field_name] = value


def _parse_header(text):
    header = _default_header()
    for line in text.splitlines():
        _update_header_from_line(header, line)
        # First report header block is enough for initial metadata.
        if {"system_date", "release", "cpd", "bank_name", "center", "run_number", "page"}.issubset(header):
            break
    return header


def _extract_labeled_values(line, labels):
    found = []

    # Longer labels first avoids short aliases matching inside longer labels.
    for label in sorted(labels, key=len, reverse=True):
        idx = line.find(label)
        if idx == -1:
            continue

        label_end = idx + len(label)
        if any(idx < existing_end and label_end > existing_start
               for _, existing_start, existing_end in found):
            continue

        found.append((label, idx, label_end))

    found.sort(key=lambda item: item[1])

    values = {}
    for i, (label, _start, label_end) in enumerate(found):
        value_end = found[i + 1][1] if i + 1 < len(found) else len(line)
        raw_value = line[label_end:value_end].strip()
        values[labels[label]] = raw_value

    return values


def _coerce_value(field_name, raw):
    if raw == "":
        return False

    if field_name in INTEGER_FIELDS:
        try:
            return int(raw)
        except (TypeError, ValueError):
            return False

    if field_name in MONETARY_FIELDS:
        try:
            return int(raw) / 100.0
        except (TypeError, ValueError):
            return False

    if field_name in FLOAT_FIELDS:
        try:
            return float(raw)
        except (TypeError, ValueError):
            return False

    return raw


def parse_vx727(text, source_file_name=""):
    """Parse a VX-727 Cash Disbursement Reversals report.

    Returns:
        tuple: (list_of_record_dicts, list_of_unmatched_line_strings)
    """
    header = _parse_header(text)
    lines = text.splitlines()

    records = []
    current = None
    current_section = None
    unmatched_lines = []

    for line_no, raw_line in enumerate(lines, start=1):
        line = raw_line.rstrip("\r\n")
        if not line.strip():
            continue

        # Keep header/page values current. This is important because a VX-727
        # file can contain many PAGE blocks in one uploaded text file.
        _update_header_from_line(header, line)

        section_match = SECTION_HEADER_RE.search(line)
        if section_match:
            voucher_label, section_label = section_match.groups()
            section_key = SECTION_KEY[section_label.lower()]

            if section_key == "required":
                if current is not None:
                    records.append(current)

                current = dict(header)
                current["draft_type"] = DRAFT_TYPE_KEY[voucher_label.lower()]
                current["source_file_name"] = source_file_name
                current["source_line_number"] = line_no

            current_section = section_key
            if current is not None:
                current["data_section"] = current_section
            continue

        # Skip repeating report headers/titles between pages.
        upper_line = line.upper()
        if (
            "REPORT VX-727" in upper_line
            or "SYSTEM DATE" in upper_line
            or ("CENTER" in upper_line and "RUN" in upper_line)
            or "TRANSACTION TOTAL RECORD COUNT" in upper_line
        ):
            continue

        if current is None or current_section is None:
            continue

        labels = ALL_SECTION_LABELS[current_section]
        values = _extract_labeled_values(line, labels)

        if not values:
            unmatched_lines.append(
                "line %s [%s]: %r" % (line_no, current_section, line)
            )
            continue

        for field_name, raw_value in values.items():
            current[field_name] = _coerce_value(field_name, raw_value)

    if current is not None:
        records.append(current)

    return records, unmatched_lines


def parse_system_date(value):
    """VX-727 system date example: 26/08/31 (YY/MM/DD)."""
    if not value:
        return False

    for fmt in ("%y/%m/%d", "%d/%m/%y", "%m/%d/%y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue

    return False


