# -*- coding: utf-8 -*-
"""Complete, audit-friendly Mastercard IPM XLSX export."""
import io

import xlsxwriter


RECORD_COLUMNS = [
    ("import_name", "Import"), ("file_name", "Source File"),
    ("record_no", "Record No"), ("logical_offset", "Logical Offset"),
    ("declared_length", "Declared Length"), ("input_encoding", "Encoding"),
    ("mti", "MTI"), ("function_code", "Function Code"),
    ("record_type", "Record Type"), ("bitmap_hex", "Bitmap Hex"),
    ("present_fields_display", "Present Fields"), ("pan_masked", "Masked PAN"),
    ("processing_code", "Processing Code"), ("transaction_amount", "Transaction Amount"),
    ("transaction_currency", "Transaction Currency"), ("settlement_amount", "Settlement Amount"),
    ("settlement_currency", "Settlement Currency"), ("stan", "STAN"),
    ("rrn", "RRN"), ("transaction_datetime", "Transaction Date/Time"),
    ("parse_status", "Parse Status"), ("consumed_bytes", "Consumed Bytes"),
    ("unparsed_bytes", "Unparsed Bytes"), ("error_message", "Error Message"),
]


def _write_value(sheet, row, column, value, text_format=None, number_format=None):
    if value is None or value is False:
        sheet.write_blank(row, column, None)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        sheet.write_number(row, column, value, number_format)
    else:
        sheet.write_string(row, column, str(value), text_format)


def _prepare_sheet(sheet, header_format, headers):
    sheet.freeze_panes(1, 0)
    sheet.autofilter(0, 0, 0, len(headers) - 1)
    sheet.set_row(0, 30)
    for column, header in enumerate(headers):
        sheet.write_string(0, column, header, header_format)


def build_complete_workbook(metadata, records, elements, errors):
    """Return XLSX bytes. Inputs are plain dictionaries for easy testing."""
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True, "strings_to_formulas": False})
    header = workbook.add_format({
        "bold": True, "font_color": "white", "bg_color": "#123B56",
        "border": 1, "align": "center", "valign": "vcenter", "text_wrap": True,
    })
    text = workbook.add_format({"valign": "top"})
    amount = workbook.add_format({"num_format": "#,##0.00", "valign": "top"})
    label = workbook.add_format({"bold": True, "bg_color": "#DDEBF1", "border": 1})

    # Fast indexed lookup also gives the exact dynamic DE column set.
    elements_by_record = {}
    data_elements = set()
    for element in elements:
        de = int(element["field_no"])
        data_elements.add(de)
        elements_by_record.setdefault(element["record_id"], {})[de] = element.get("value_text")
    data_elements = sorted(data_elements)

    info = workbook.add_worksheet("File Metadata")
    info.set_column(0, 0, 28)
    info.set_column(1, 1, 76)
    for row, (key, value) in enumerate(metadata.items()):
        info.write_string(row, 0, key, label)
        _write_value(info, row, 1, value, text)

    records_sheet = workbook.add_worksheet("IPM Records")
    dynamic_headers = [f"DE{de:03d}" for de in data_elements]
    record_headers = [title for _key, title in RECORD_COLUMNS] + dynamic_headers
    _prepare_sheet(records_sheet, header, record_headers)
    records_sheet.set_column(0, 1, 24)
    records_sheet.set_column(2, 8, 16)
    records_sheet.set_column(9, 9, 38)
    records_sheet.set_column(10, len(record_headers) - 1, 20)
    for row_no, record in enumerate(records, 1):
        record_elements = elements_by_record.get(record["id"], {})
        values = dict(record)
        values["present_fields_display"] = ", ".join(str(de) for de in record.get("present_fields") or [])
        # Odoo Float uses 0.0 for False. Use DE presence to preserve the semantic difference.
        if 4 not in record_elements:
            values["transaction_amount"] = None
        if 5 not in record_elements:
            values["settlement_amount"] = None
        for column, (key, _title) in enumerate(RECORD_COLUMNS):
            _write_value(records_sheet, row_no, column, values.get(key), text, amount if key.endswith("_amount") else None)
        offset = len(RECORD_COLUMNS)
        for column, de in enumerate(data_elements, offset):
            _write_value(records_sheet, row_no, column, record_elements.get(de), text)

    elements_sheet = workbook.add_worksheet("Data Elements")
    element_headers = ["Import", "Record No", "DE", "Field Type", "Data Class", "Length", "Value"]
    _prepare_sheet(elements_sheet, header, element_headers)
    elements_sheet.set_column(0, 1, 20)
    elements_sheet.set_column(2, 5, 14)
    elements_sheet.set_column(6, 6, 70)
    for row_no, element in enumerate(elements, 1):
        values = [element.get(key) for key in (
            "import_name", "record_no", "field_no", "field_type", "data_class", "field_length", "value_text"
        )]
        for column, value in enumerate(values):
            _write_value(elements_sheet, row_no, column, value, text)

    errors_sheet = workbook.add_worksheet("Parsing Errors")
    error_headers = ["Import", "Record No", "Logical Offset", "Stage", "Message"]
    _prepare_sheet(errors_sheet, header, error_headers)
    errors_sheet.set_column(0, 3, 20)
    errors_sheet.set_column(4, 4, 80)
    for row_no, error in enumerate(errors, 1):
        values = [error.get(key) for key in (
            "import_name", "record_no", "logical_offset", "error_stage", "error_message"
        )]
        for column, value in enumerate(values):
            _write_value(errors_sheet, row_no, column, value, text)

    workbook.close()
    return output.getvalue()
