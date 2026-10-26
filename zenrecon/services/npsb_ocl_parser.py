import json
from datetime import datetime

from lxml import etree


class OICXMLParseError(ValueError):
    """Raised when the uploaded OIC XML file is invalid or unsupported."""


def _text(node, path, default=""):
    value = node.findtext(path)
    return value.strip() if isinstance(value, str) else default


def _parse_datetime(value):
    if not value:
        return False
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return False


def _parse_date(value):
    if not value:
        return False
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return False


def _parse_float(value):
    if value in (None, ""):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _parm_map(doc, xpath):
    result = {}
    for parm in doc.findall(xpath):
        code = _text(parm, "ParmCode")
        if not code:
            continue
        result[code] = _text(parm, "Value")
    return result


def parse_oic_xml(raw_bytes, source_file_name=""):
    """Parse an OIC DocFile XML export into Odoo-ready dictionaries.

    Returns: (header, records)
    """
    if not raw_bytes:
        raise OICXMLParseError("The uploaded XML file is empty.")

    try:
        parser = etree.XMLParser(
            resolve_entities=False,
            no_network=True,
            recover=False,
            remove_blank_text=False,
            huge_tree=True,
        )
        root = etree.fromstring(raw_bytes, parser=parser)
    except (etree.XMLSyntaxError, ValueError, TypeError) as error:
        raise OICXMLParseError("Invalid XML file: %s" % error) from error

    if root.tag != "DocFile":
        raise OICXMLParseError(
            "Invalid OIC XML file. Expected root element <DocFile>, found <%s>." % root.tag
        )

    header_node = root.find("./FileHeader")
    if header_node is None:
        raise OICXMLParseError("Invalid OIC XML file: <FileHeader> was not found.")

    header = {
        "file_label": _text(header_node, "FileLabel"),
        "format_version": _text(header_node, "FormatVersion"),
        "sender": _text(header_node, "Sender"),
        "creation_date": _parse_date(_text(header_node, "CreationDate")),
        "creation_time": _text(header_node, "CreationTime"),
        "file_sequence_number": _text(header_node, "FileSeqNumber"),
        "receiver": _text(header_node, "Receiver"),
        "source_file_name": source_file_name or "",
    }

    records = []
    docs = root.findall("./DocList/Doc")
    for record_number, doc in enumerate(docs, start=1):
        refs = _parm_map(doc, "./DocRefSet/Parm")
        adds = _parm_map(doc, "./Transaction/Extra/AddData/Parm")

        transaction_amount_raw = _text(doc, "./Transaction/Amount")
        billing_amount_raw = _text(doc, "./Billing/Amount")
        reconciliation_amount_raw = _text(doc, "./Reconciliation/Amount")

        vals = {
            **header,
            "source_record_number": record_number,
            "msg_code": _text(doc, "./TransType/TransCode/MsgCode"),
            "fin_category": _text(doc, "./TransType/TransCode/FinCategory"),
            "request_category": _text(doc, "./TransType/TransCode/RequestCategory"),
            "service_class": _text(doc, "./TransType/TransCode/ServiceClass"),
            "transaction_type_code": _text(doc, "./TransType/TransCode/TransTypeCode"),
            "transaction_condition": _text(doc, "./TransType/TransCondition"),
            "original_transaction_condition": _text(doc, "./TransType/OrigTransCondition"),
            "dispute_reason_code": _text(doc, "./TransType/DisputeRules/ReasonCode"),
            "dispute_reason_details": _text(doc, "./TransType/DisputeRules/ReasonDetails"),
            "drn": refs.get("DRN", ""),
            "previous_drn": refs.get("PrevDRN", ""),
            "original_drn": refs.get("OrigDRN", ""),
            "summary_drn": refs.get("SummDRN", ""),
            "srn": refs.get("SRN", ""),
            "irn": refs.get("IRN", ""),
            "rrn": refs.get("RRN", ""),
            "arn": refs.get("ARN", ""),
            "auth_code": refs.get("AuthCode", ""),
            "trn": refs.get("TRN", ""),
            "reference_parameters": json.dumps(refs, ensure_ascii=False, indent=2, sort_keys=True),
            "local_datetime": _parse_datetime(_text(doc, "./LocalDt")),
            "network_datetime": _parse_datetime(_text(doc, "./NWDt")),
            "sic": _text(doc, "./SourceDtls/SIC"),
            "country": _text(doc, "./SourceDtls/Country"),
            "city": _text(doc, "./SourceDtls/City"),
            "merchant_name": _text(doc, "./SourceDtls/MerchantName"),
            "merchant_id": _text(doc, "./SourceDtls/MerchantID"),
            "originator_contract_number": _text(doc, "./Originator/ContractNumber"),
            "originator_member_id": _text(doc, "./Originator/MemberId"),
            "originator_transit_id": _text(doc, "./Originator/TransitId"),
            "originator_card_expiry": _text(doc, "./Originator/CardInfo/CardExpiry"),
            "originator_card_sequence": _text(doc, "./Originator/CardInfo/CardSeqN"),
            "originator_channel": _text(doc, "./Originator/Product/Channel"),
            "destination_contract_number": _text(doc, "./Destination/ContractNumber"),
            "destination_relation": _text(doc, "./Destination/Relation"),
            "destination_member_id": _text(doc, "./Destination/MemberId"),
            "destination_transit_id": _text(doc, "./Destination/TransitId"),
            "destination_card_expiry": _text(doc, "./Destination/CardInfo/CardExpiry"),
            "destination_card_sequence": _text(doc, "./Destination/CardInfo/CardSeqN"),
            "destination_channel": _text(doc, "./Destination/Product/Channel"),
            "transaction_currency_code": _text(doc, "./Transaction/Currency"),
            "transaction_amount": _parse_float(transaction_amount_raw),
            "transaction_amount_raw": transaction_amount_raw,
            "extra_type": _text(doc, "./Transaction/Extra/Type"),
            "transaction_code": adds.get("WHAT_TRX", ""),
            "additional_parameters": json.dumps(adds, ensure_ascii=False, indent=2, sort_keys=True),
            "billing_date": _parse_date(_text(doc, "./Billing/PhaseDate")),
            "billing_currency_code": _text(doc, "./Billing/Currency"),
            "billing_amount": _parse_float(billing_amount_raw),
            "billing_amount_raw": billing_amount_raw,
            "reconciliation_date": _parse_date(_text(doc, "./Reconciliation/PhaseDate")),
            "reconciliation_currency_code": _text(doc, "./Reconciliation/Currency"),
            "reconciliation_amount": _parse_float(reconciliation_amount_raw),
            "reconciliation_amount_raw": reconciliation_amount_raw,
            "original_transaction_datetime": _parse_datetime(_text(doc, "./ChainDtls/OrigTransDate")),
        }
        records.append(vals)

    if not records:
        raise OICXMLParseError("No <Doc> transaction records were found under <DocList>.")

    return header, records
