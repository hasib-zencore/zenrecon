# -*- coding: utf-8 -*-
"""Mastercard IPM deblocking and ISO 8583:1993 parsing.

This is the Odoo-native form of the supplied CMS IPM reference parser.  It
accepts bytes (not filesystem paths) and never returns full PAN or raw payloads
for persistence.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal


BLOCK_SIZE = 1014
DATA_SIZE = 1012
MAX_RECORD = 32767
PARSER_VERSION = "cms-ipm-odoo-1.0.0"


@dataclass(frozen=True)
class FieldSpec:
    de: int
    kind: str
    max_len: int
    encoding: str


def _spec(de, kind, max_len, encoding):
    return FieldSpec(de, kind, max_len, encoding)


# Mastercard std8583_93Map supplied with the reference implementation.
FIELD_MAP = {
    1: _spec(1, "BM_FIXED", 8, "BME_B"), 2: _spec(2, "BM_LLVAR", 19, "BME_N"),
    3: _spec(3, "BM_FIXED", 6, "BME_N"), 4: _spec(4, "BM_FIXED", 12, "BME_N"),
    5: _spec(5, "BM_FIXED", 12, "BME_N"), 6: _spec(6, "BM_FIXED", 12, "BME_N"),
    7: _spec(7, "BM_FIXED", 10, "BME_N"), 8: _spec(8, "BM_FIXED", 8, "BME_N"),
    9: _spec(9, "BM_FIXED", 8, "BME_N"), 10: _spec(10, "BM_FIXED", 8, "BME_N"),
    11: _spec(11, "BM_FIXED", 6, "BME_N"), 12: _spec(12, "BM_FIXED", 12, "BME_N"),
    13: _spec(13, "BM_FIXED", 4, "BME_N"), 14: _spec(14, "BM_FIXED", 4, "BME_N"),
    15: _spec(15, "BM_FIXED", 6, "BME_N"), 16: _spec(16, "BM_FIXED", 4, "BME_N"),
    17: _spec(17, "BM_FIXED", 4, "BME_N"), 18: _spec(18, "BM_FIXED", 4, "BME_N"),
    19: _spec(19, "BM_FIXED", 3, "BME_N"), 20: _spec(20, "BM_FIXED", 3, "BME_N"),
    21: _spec(21, "BM_FIXED", 3, "BME_N"), 22: _spec(22, "BM_FIXED", 12, "BME_AN"),
    23: _spec(23, "BM_FIXED", 3, "BME_N"), 24: _spec(24, "BM_FIXED", 3, "BME_N"),
    25: _spec(25, "BM_FIXED", 4, "BME_N"), 26: _spec(26, "BM_FIXED", 4, "BME_N"),
    27: _spec(27, "BM_FIXED", 1, "BME_N"), 28: _spec(28, "BM_FIXED", 6, "BME_N"),
    29: _spec(29, "BM_FIXED", 3, "BME_N"), 30: _spec(30, "BM_FIXED", 24, "BME_N"),
    31: _spec(31, "BM_LLVAR", 99, "BME_ANS"), 32: _spec(32, "BM_LLVAR", 11, "BME_N"),
    33: _spec(33, "BM_LLVAR", 11, "BME_N"), 34: _spec(34, "BM_LLVAR", 28, "BME_N"),
    35: _spec(35, "BM_LLVAR", 37, "BME_Z"), 36: _spec(36, "BM_LLLVAR", 104, "BME_Z"),
    37: _spec(37, "BM_FIXED", 12, "BME_AN"), 38: _spec(38, "BM_FIXED", 6, "BME_AN"),
    39: _spec(39, "BM_FIXED", 3, "BME_N"), 40: _spec(40, "BM_FIXED", 3, "BME_N"),
    41: _spec(41, "BM_FIXED", 8, "BME_ANS"), 42: _spec(42, "BM_FIXED", 15, "BME_ANS"),
    43: _spec(43, "BM_LLVAR", 99, "BME_ANS"), 44: _spec(44, "BM_LLVAR", 99, "BME_ANS"),
    45: _spec(45, "BM_LLVAR", 76, "BME_ANS"), 46: _spec(46, "BM_LLLVAR", 204, "BME_ANS"),
    47: _spec(47, "BM_LLLVAR", 999, "BME_ANS"), 48: _spec(48, "BM_LLLVAR", 999, "BME_ANS"),
    49: _spec(49, "BM_FIXED", 3, "BME_N"), 50: _spec(50, "BM_FIXED", 3, "BME_N"),
    51: _spec(51, "BM_FIXED", 3, "BME_N"), 52: _spec(52, "BM_FIXED", 8, "BME_B"),
    53: _spec(53, "BM_LLVAR", 48, "BME_B"), 54: _spec(54, "BM_LLLVAR", 240, "BME_ANS"),
    55: _spec(55, "BM_LLLVAR", 255, "BME_B"), 56: _spec(56, "BM_LLVAR", 35, "BME_N"),
    57: _spec(57, "BM_FIXED", 3, "BME_N"), 58: _spec(58, "BM_LLVAR", 11, "BME_N"),
    59: _spec(59, "BM_LLLVAR", 999, "BME_ANS"), 60: _spec(60, "BM_LLLVAR", 999, "BME_ANS"),
    61: _spec(61, "BM_LLLVAR", 999, "BME_ANS"), 62: _spec(62, "BM_LLLVAR", 999, "BME_ANS"),
    63: _spec(63, "BM_LLLVAR", 999, "BME_ANS"), 64: _spec(64, "BM_FIXED", 64, "BME_B"),
    65: _spec(65, "BM_FIXED", 64, "BME_B"), 66: _spec(66, "BM_LLLVAR", 204, "BME_ANS"),
    67: _spec(67, "BM_FIXED", 2, "BME_N"), 68: _spec(68, "BM_FIXED", 3, "BME_N"),
    69: _spec(69, "BM_FIXED", 3, "BME_N"), 70: _spec(70, "BM_FIXED", 3, "BME_N"),
    71: _spec(71, "BM_FIXED", 8, "BME_N"), 72: _spec(72, "BM_LLLVAR", 999, "BME_ANS"),
    73: _spec(73, "BM_FIXED", 6, "BME_N"),
    **{de: _spec(de, "BM_FIXED", 10, "BME_N") for de in range(74, 86)},
    **{de: _spec(de, "BM_FIXED", 16, "BME_N") for de in range(86, 90)},
    90: _spec(90, "BM_FIXED", 10, "BME_N"), 91: _spec(91, "BM_FIXED", 3, "BME_N"),
    92: _spec(92, "BM_FIXED", 3, "BME_N"), 93: _spec(93, "BM_LLVAR", 11, "BME_N"),
    94: _spec(94, "BM_LLVAR", 11, "BME_N"), 95: _spec(95, "BM_LLVAR", 99, "BME_ANS"),
    96: _spec(96, "BM_LLLVAR", 999, "BME_B"), 97: _spec(97, "BM_FIXED", 17, "BME_ANS"),
    98: _spec(98, "BM_FIXED", 25, "BME_ANS"), 99: _spec(99, "BM_LLVAR", 11, "BME_N"),
    100: _spec(100, "BM_LLVAR", 11, "BME_N"), 101: _spec(101, "BM_LLVAR", 17, "BME_ANS"),
    102: _spec(102, "BM_LLVAR", 28, "BME_ANS"), 103: _spec(103, "BM_LLVAR", 28, "BME_ANS"),
    104: _spec(104, "BM_LLLVAR", 100, "BME_ANS"), 105: _spec(105, "BM_LLLVAR", 999, "BME_ANS"),
    106: _spec(106, "BM_FIXED", 16, "BME_N"), 107: _spec(107, "BM_FIXED", 10, "BME_N"),
    108: _spec(108, "BM_FIXED", 10, "BME_N"), 109: _spec(109, "BM_LLVAR", 84, "BME_ANS"),
    110: _spec(110, "BM_LLVAR", 84, "BME_ANS"),
    **{de: _spec(de, "BM_LLLVAR", 999, "BME_ANS") for de in range(111, 128)},
    128: _spec(128, "BM_FIXED", 64, "BME_B"),
}

RECORD_TYPES = {
    ("1240", "200"): "FIRST_PRESENTMENT", ("1240", "205"): "SECOND_PRESENTMENT",
    ("1240", "282"): "SECOND_PRESENTMENT", ("1442", "450"): "FEE_COLLECTION",
    ("1442", "451"): "FEE_COLLECTION", ("1442", "453"): "FEE_COLLECTION",
    ("1442", "454"): "FEE_COLLECTION", ("1644", "603"): "CURRENCY_UPDATE",
    ("1644", "640"): "RECONCILIATION", ("1644", "680"): "FILE_CONTROL",
    ("1644", "681"): "FILE_CONTROL", ("1644", "685"): "FILE_CONTROL",
    ("1644", "688"): "FILE_CONTROL", ("1644", "691"): "FILE_CONTROL",
    ("1644", "693"): "FILE_CONTROL", ("1644", "695"): "TRAILER",
    ("1644", "696"): "FILE_CONTROL", ("1644", "697"): "HEADER",
    ("1644", "699"): "FILE_CONTROL", ("1740", "700"): "NETWORK_MANAGEMENT",
    ("1740", "780"): "NETWORK_MANAGEMENT", ("1740", "781"): "NETWORK_MANAGEMENT",
    ("1740", "782"): "NETWORK_MANAGEMENT", ("1740", "783"): "NETWORK_MANAGEMENT",
}


def deblock(raw):
    output = bytearray()
    for offset in range(0, len(raw), BLOCK_SIZE):
        block = raw[offset:offset + BLOCK_SIZE]
        output.extend(block[:min(DATA_SIZE, len(block))])
    return bytes(output)


def iter_rdw_records(stream):
    offset = record_no = 0
    while offset < len(stream):
        while offset < len(stream) and stream[offset] in (0x20, 0x40):
            offset += 1
        if offset >= len(stream):
            break
        if offset + 4 > len(stream):
            raise ValueError(f"truncated RDW at logical offset {offset}")
        record_offset = offset
        length = int.from_bytes(stream[offset:offset + 4], "big")
        offset += 4
        if not length:
            continue
        if length > MAX_RECORD:
            raise ValueError(f"invalid RDW length {length} at logical offset {record_offset}")
        if offset + length > len(stream):
            raise ValueError(f"record length {length} at {record_offset} exceeds remaining stream")
        record_no += 1
        yield record_no, record_offset, stream[offset:offset + length]
        offset += length


def _decode(raw, encoding):
    return raw.decode("cp037" if encoding == "ebcdic" else "ascii", errors="replace")


def _digits(raw, encoding):
    value = _decode(raw, encoding)
    if not value.isdigit():
        raise ValueError(f"invalid {encoding} length digits {raw.hex()} decoded={value!r}")
    return value


def _bitmap_fields(bitmap):
    return [index * 8 + bit + 1 for index, byte in enumerate(bitmap)
            for bit in range(8) if byte & (0x80 >> bit)]


def detect_encoding(record):
    for encoding, codec in (("ascii", "ascii"), ("ebcdic", "cp037")):
        mti = record[:4].decode(codec, errors="ignore")
        if len(mti) == 4 and mti.isdigit():
            return encoding
    raise ValueError(f"cannot detect MTI encoding from {record[:4].hex()}")


def mask_pan(value):
    value = value or ""
    if len(value) <= 10:
        return "*" * len(value)
    return value[:6] + "*" * (len(value) - 10) + value[-4:]


def parse_iso8583(record, encoding):
    if len(record) < 12:
        raise ValueError("record shorter than MTI + primary bitmap")
    mti = _decode(record[:4], encoding)
    if len(mti) != 4 or not mti.isdigit():
        raise ValueError(f"invalid MTI {mti!r}")
    cursor = 4
    primary = record[cursor:cursor + 8]
    cursor += 8
    bits = _bitmap_fields(primary)
    secondary = b""
    if 1 in bits:
        if cursor + 8 > len(record):
            raise ValueError("secondary bitmap indicated but missing")
        secondary = record[cursor:cursor + 8]
        cursor += 8
        bits = _bitmap_fields(primary + secondary)
    present = [de for de in bits if de != 1]
    parsed_fields = {}
    for de in present:
        spec = FIELD_MAP.get(de)
        if not spec:
            raise ValueError(f"no std8583_93Map definition for DE{de}")
        if spec.kind == "BM_FIXED":
            length = spec.max_len
        elif spec.kind == "BM_LLVAR":
            if cursor + 2 > len(record):
                raise ValueError(f"DE{de} missing LLVAR prefix")
            length = int(_digits(record[cursor:cursor + 2], encoding))
            cursor += 2
        elif spec.kind == "BM_LLLVAR":
            if cursor + 3 > len(record):
                raise ValueError(f"DE{de} missing LLLVAR prefix")
            length = int(_digits(record[cursor:cursor + 3], encoding))
            cursor += 3
        else:
            raise ValueError(f"DE{de} unsupported kind {spec.kind}")
        if length > spec.max_len:
            raise ValueError(f"DE{de} length {length} > map maximum {spec.max_len}")
        if cursor + length > len(record):
            raise ValueError(f"DE{de} length {length} exceeds record")
        raw_value = record[cursor:cursor + length]
        cursor += length
        value = raw_value.hex().upper() if spec.encoding == "BME_B" else _decode(raw_value, encoding)
        parsed_fields[str(de)] = {
            "length": length, "type": spec.kind, "data_class": spec.encoding, "value": value,
        }
    function_code = parsed_fields.get("24", {}).get("value")
    return {
        "mti": mti,
        "function_code": function_code,
        "record_type": RECORD_TYPES.get((mti, function_code), "UNMAPPED"),
        "bitmap_hex": (primary + secondary).hex().upper(),
        "present_fields": present,
        "fields": parsed_fields,
        "consumed_bytes": cursor,
        "unparsed_bytes": len(record) - cursor,
    }


def parse_ipm(raw, filename="", forced_encoding=None):
    """Parse one physical IPM file and return sanitized metadata and records."""
    stream = deblock(raw)
    records = []
    errors = []
    for number, offset, record in iter_rdw_records(stream):
        item = {"record_no": number, "logical_offset": offset, "declared_length": len(record)}
        try:
            encoding = forced_encoding or detect_encoding(record)
            item["encoding"] = encoding
            item.update(parse_iso8583(record, encoding))
            pan = item["fields"].get("2", {}).get("value")
            if pan is not None:
                item["pan_masked"] = mask_pan(pan)
                item["fields"]["2"]["value"] = item["pan_masked"]
            item["status"] = "parsed" if not item["unparsed_bytes"] else "remainder"
        except Exception as exc:  # keep all valid records and audit the bad one
            item.update({"status": "error", "error": str(exc)})
            errors.append({"record_no": number, "logical_offset": offset, "error": str(exc)})
        records.append(item)
    encodings = sorted({row.get("encoding") for row in records if row.get("encoding")})
    return {
        "file": {
            "source_filename": filename,
            "source_size": len(raw),
            "source_sha256": hashlib.sha256(raw).hexdigest(),
            "physical_block_size": BLOCK_SIZE,
            "data_bytes_per_block": DATA_SIZE,
            "logical_size": len(stream),
            "input_encoding": encodings[0] if len(encodings) == 1 else ("mixed" if encodings else False),
            "parser_version": PARSER_VERSION,
            "record_count": len(records),
            "error_count": len(errors),
        },
        "records": records,
        "errors": errors,
    }


def field_value(record, de):
    return record.get("fields", {}).get(str(de), {}).get("value")


def amount_value(record, de):
    value = field_value(record, de)
    return Decimal(value) / Decimal("100") if value and value.isdigit() else False
