# -*- coding: utf-8 -*-
"""Pure parser for Mastercard clearing text reports."""
import re
from datetime import datetime


REPORT_START = re.compile(r"^(1IP\d{6}-[A-Z]{2})")
RUN_DATE = re.compile(r"RUN DATE:\s*(\d{2}/\d{2}/\d{2})")
CYCLE_IN_HEADER = re.compile(r"CLEARING CYCLE\s+(\d+)", re.I)
ISO_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
MEMBER = re.compile(r"MEMBER ID:\s*(\d+)")
BSL = re.compile(r"BUSINESS SERVICE LEVEL:\s*(\S+)")
BSID = re.compile(r"BUSINESS SERVICE ID:\s*(\S+)")
FILE_ID = re.compile(r"FILE ID:\s*(\S+)")
DAY_TOTAL_ASOF = re.compile(r"CLEARING DAY TOTAL AS OF CLEARING CYCLE\s+(\d+)", re.I)

DETAIL = re.compile(
    r"^\s*"
    r"(?P<func>FIRST PRES\.|FIRST C/B\s*-F|SECOND PRES\.|CREDIT)?"
    r"\s+"
    r"(?P<proc>PURCHASE|CASH|REFUND|CREDIT|UNIQUE|PAYMENT)"
    r"\s+"
    r"(?P<orig>ORIG|RVSL)"
    r"\s+"
    r"(?P<ird>[A-Z0-9]{2})"
    r"\s+"
    r"(?P<counts>\d+)"
    r"\s+"
    r"(?P<ramt>[\d,]+\.\d{2})\s+(?P<rdr>DR|CR)"
    r"\s+"
    r"(?P<rcur>\d{2,3}-[A-Z]{3})"
    r"\s+"
    r"(?P<famt>[\d,]+\.\d{2})\s+(?P<fdr>DR|CR)"
    r"\s+"
    r"(?P<fcur>\d{2,3}-[A-Z]{3})",
    re.I,
)
DAY_CURR = re.compile(r"^\s+(\d{2,3}-[A-Z]{3})\s+([\d,]+\.\d{2})\s+(DR|CR)\s*$")


def _date_mdy(text):
    try:
        return datetime.strptime(text, "%m/%d/%y").date()
    except ValueError:
        return False


def _date_iso(text):
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return False


def _money(text):
    return float(text.replace(",", ""))


def parse_clearing_report(text):
    """Return values ready for ``mastercard.clearing.line.create``."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    rows = []
    context = _blank_context()
    in_day_total_block = False
    last_function = False
    sequence = 0

    for raw in lines:
        line = raw.rstrip()
        start = REPORT_START.match(line)
        if start:
            context = _blank_context()
            context["report_id"] = start.group(1)
            match = RUN_DATE.search(line)
            if match:
                context["run_date"] = _date_mdy(match.group(1))
            match = CYCLE_IN_HEADER.search(line)
            if match:
                context["mastercard_cycle"] = "CLEARING CYCLE %s" % match.group(1).zfill(3)
            upper = line.upper()
            if "ACKNOWLEDGEMENT" in upper:
                context["ack_notification"] = "ACKNOWLEDGEMENT"
            elif "NOTIFICATION" in upper:
                context["ack_notification"] = "NOTIFICATION"
            in_day_total_block = "CLEARING DAY TOTAL" in upper
            if in_day_total_block:
                context["ack_notification"] = "CLEARING DAY TOTAL"
            last_function = False
            continue

        if not context["report_id"]:
            continue
        if "NO DATA TO REPORT" in line:
            in_day_total_block = False
            continue

        match = BSL.search(line)
        if match:
            context["business_service_level"] = match.group(1).strip()
        match = BSID.search(line)
        if match:
            context["business_service_id"] = match.group(1).strip()
        match = FILE_ID.search(line)
        if match:
            context["file_id"] = match.group(1).strip()
        match = MEMBER.search(line)
        if match:
            context["member_id"] = match.group(1).strip()
        if not context["clearing_date"]:
            match = ISO_DATE.search(line)
            if match:
                context["clearing_date"] = _date_iso(match.group(1))
        match = CYCLE_IN_HEADER.search(line)
        if match and not (in_day_total_block and context["mastercard_cycle"]):
            context["mastercard_cycle"] = "CLEARING CYCLE %s" % match.group(1).zfill(3)
        if "NOTIFICATION" in line.upper() and context["report_id"].startswith("1IP727020"):
            context["ack_notification"] = "NOTIFICATION"
        if "ACKNOWLEDGEMENT" in line.upper() and context["report_id"].startswith("1IP727010"):
            context["ack_notification"] = "ACKNOWLEDGEMENT"
        if "MASTERCARD SETTLED" in line.upper():
            context["settled_coll_only"] = "MASTERCARD SETTLED"
        if "CLEARING DAY TOTAL" in line.upper() and context["report_id"].startswith("1IP728010"):
            in_day_total_block = True
            context["ack_notification"] = "CLEARING DAY TOTAL"

        if context["report_id"].startswith("1IP728010") and in_day_total_block:
            match = DAY_TOTAL_ASOF.search(line)
            if match:
                context["mastercard_cycle"] = "CLEARING CYCLE %s" % match.group(1).zfill(3)
                continue
            if "EXCEPTIONS" in line.upper():
                in_day_total_block = False
                continue
            match = DAY_CURR.match(line)
            if match:
                sequence += 1
                rows.append(_day_row(sequence, context, match, line))
            continue

        if not (
            context["report_id"].startswith("1IP727020")
            or context["report_id"].startswith("1IP727010")
        ):
            continue
        if "TOTAL" in line.upper() and ("FIRST" in line.upper() or "C/B" in line.upper()):
            continue
        if "SUBTOTAL" in line.upper() or "GRAND TOTAL" in line.upper():
            continue
        match = DETAIL.match(line)
        if not match:
            continue
        function = re.sub(r"\s+", " ", (match.group("func") or "").strip())
        if function:
            last_function = function
        else:
            function = last_function or ""
        sequence += 1
        default_ack = (
            "ACKNOWLEDGEMENT"
            if context["report_id"].startswith("1IP727010")
            else "NOTIFICATION"
        )
        rows.append(_detail_row(sequence, context, match, function, line, default_ack))
    return rows


def _detail_row(sequence, context, match, function, line, default_ack):
    return {
        "sequence": sequence,
        "report_id": context["report_id"],
        "settled_coll_only": context["settled_coll_only"] or "MASTERCARD SETTLED",
        "mastercard_cycle": context["mastercard_cycle"],
        "ack_notification": context["ack_notification"] or default_ack,
        "business_service_level": context["business_service_level"],
        "business_service_id": context["business_service_id"],
        "file_id": context["file_id"],
        "member_id": context["member_id"],
        "run_date": context["run_date"],
        "clearing_date": context["clearing_date"],
        "trans_func": function or False,
        "proc_code": "%s %s" % (match.group("proc").upper(), match.group("orig").upper()),
        "ird": match.group("ird").upper(),
        "counts": int(match.group("counts")),
        "recon_amount": _money(match.group("ramt")),
        "recon_dr_cr": match.group("rdr").upper(),
        "recon_curr_code": match.group("rcur"),
        "trans_fee": _money(match.group("famt")),
        "fee_dr_cr": match.group("fdr").upper(),
        "fee_curr_code": match.group("fcur"),
        "net_amount": 0.0,
        "net_dr_cr": False,
        "is_day_total": False,
        "raw_line": line.strip(),
    }


def _day_row(sequence, context, match, line):
    return {
        "sequence": sequence,
        "report_id": context["report_id"],
        "settled_coll_only": False,
        "mastercard_cycle": context["mastercard_cycle"],
        "ack_notification": "CLEARING DAY TOTAL",
        "business_service_level": False,
        "business_service_id": False,
        "file_id": False,
        "member_id": context["member_id"],
        "run_date": context["run_date"],
        "clearing_date": context["clearing_date"],
        "trans_func": False,
        "proc_code": False,
        "ird": False,
        "counts": 0,
        "recon_amount": 0.0,
        "recon_dr_cr": False,
        "recon_curr_code": match.group(1),
        "trans_fee": 0.0,
        "fee_dr_cr": False,
        "fee_curr_code": False,
        "net_amount": _money(match.group(2)),
        "net_dr_cr": match.group(3).upper(),
        "is_day_total": True,
        "raw_line": line.strip(),
    }


def _blank_context():
    return {
        "report_id": False,
        "settled_coll_only": False,
        "mastercard_cycle": False,
        "ack_notification": False,
        "business_service_level": False,
        "business_service_id": False,
        "file_id": False,
        "member_id": False,
        "run_date": False,
        "clearing_date": False,
    }
