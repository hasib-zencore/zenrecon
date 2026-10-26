# -*- coding: utf-8 -*-
"""Pure-Python parser for selected VisaNet Settlement Service reports.

The parser intentionally has no Odoo dependency so it can be tested against source
files outside an Odoo runtime. It supports the daily report families required by
Bank System Reconciliation: VSS-110, VSS-120, VSS-130, VSS-140 and VSS-210.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
import re
from typing import Dict, Iterable, List, Optional, Tuple


TARGET_REPORTS = ("VSS-110", "VSS-120", "VSS-130", "VSS-140", "VSS-210")
REPORT_NAMES = {
    "VSS-110": "Settlement Summary Report",
    "VSS-120": "Interchange Value Report",
    "VSS-130": "Reimbursement Fees Report",
    "VSS-140": "Visa Charges Report",
    "VSS-210": "Currency Conversion Fees Report",
}
SERVICE_NAMES = (
    "INTERNATIONAL SETTLEMENT SERVICE",
    "BANGLADESH NATIONAL NET SERVICE",
    "BANGLADESH NATIONAL NET",
)

_START_RE = re.compile(
    r"^\s*REPORT ID:\s*(VSS-(?:110|120|130|140|210))(?!-).*?PAGE:\s*(\d+)",
    re.IGNORECASE,
)
_ANY_REPORT_RE = re.compile(r"^\s*REPORT ID:\s*(VSS-[0-9A-Z-]+).*?PAGE:\s*(\d+)", re.IGNORECASE)
_NO_DATA_RE = re.compile(r"\*{3}\s*NO DATA FOR THIS REPORT\s*\*{3}", re.IGNORECASE)
_DATE_RE = re.compile(r"^\d{2}[A-Z]{3}\d{2}$")
_AMOUNT_RE = re.compile(r"^([+-]?(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d+)?)(CR|DB)?$", re.IGNORECASE)


@dataclass
class ParseIssue:
    severity: str
    message: str
    source_line_no: Optional[int] = None
    raw_line: Optional[str] = None


@dataclass
class LogicalReport:
    report_code: str
    start_line: int
    end_line: int
    lines: List[Tuple[int, str]]
    complete: bool = True
    issues: List[ParseIssue] = field(default_factory=list)


@dataclass
class ParsedReport:
    header: Dict
    lines: List[Dict]
    issues: List[ParseIssue] = field(default_factory=list)


class VSSParser:
    """Segment and parse target VSS reports from a complete fixed-width text file."""

    def parse(self, text: str) -> Tuple[List[ParsedReport], List[ParseIssue]]:
        logical_reports, global_issues = self.segment(text)
        parsed: List[ParsedReport] = []
        for sequence_no, logical in enumerate(logical_reports, start=1):
            try:
                parsed_report = self.parse_report(logical, sequence_no=sequence_no)
            except Exception as exc:  # defensive: one malformed report must not kill the batch
                header = self._parse_header(logical)
                header.update(
                    {
                        "sequence_no": sequence_no,
                        "data_status": "parse_error",
                        "processing_status": "error",
                    }
                )
                issue = ParseIssue(
                    severity="error",
                    message=f"Unexpected parser error: {exc}",
                    source_line_no=logical.start_line,
                )
                parsed_report = ParsedReport(header=header, lines=[], issues=logical.issues + [issue])
            parsed.append(parsed_report)
        return parsed, global_issues

    def segment(self, text: str) -> Tuple[List[LogicalReport], List[ParseIssue]]:
        """Return complete logical reports, grouping continuation pages until END marker.

        Monthly variants (e.g. VSS-110-M) are excluded by the exact start regex.
        """
        # A form-feed prefixes the next page in VisaNet files; it is not an
        # additional source line. Removing it preserves auditable line numbers
        # while still allowing the following REPORT ID header to match.
        normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n").replace("\f", "")
        raw_lines = normalized.split("\n")
        reports: List[LogicalReport] = []
        issues: List[ParseIssue] = []
        current: Optional[LogicalReport] = None

        for line_no, raw_line in enumerate(raw_lines, start=1):
            start_match = _START_RE.match(raw_line)
            any_match = _ANY_REPORT_RE.match(raw_line)

            if current is None:
                if start_match:
                    code = start_match.group(1).upper()
                    page = int(start_match.group(2))
                    current = LogicalReport(code, line_no, line_no, [(line_no, raw_line)])
                    if page != 1:
                        current.complete = False
                        current.issues.append(
                            ParseIssue(
                                "error",
                                f"Logical report starts at page {page}, not page 1.",
                                line_no,
                                raw_line,
                            )
                        )
                continue

            # A PAGE 1 report header before the current END marker means the current report is incomplete.
            if any_match:
                seen_code = any_match.group(1).upper()
                seen_page = int(any_match.group(2))
                if seen_page == 1 and line_no != current.start_line:
                    if seen_code == current.report_code or seen_code != current.report_code:
                        current.complete = False
                        current.end_line = line_no - 1
                        current.issues.append(
                            ParseIssue(
                                "error",
                                f"Missing END marker before new report {seen_code}.",
                                line_no,
                                raw_line,
                            )
                        )
                        reports.append(current)
                        current = None
                        if start_match:
                            code = start_match.group(1).upper()
                            current = LogicalReport(code, line_no, line_no, [(line_no, raw_line)])
                        continue

            current.lines.append((line_no, raw_line))
            current.end_line = line_no
            if self._is_end_marker(raw_line, current.report_code):
                reports.append(current)
                current = None

        if current is not None:
            current.complete = False
            current.issues.append(
                ParseIssue(
                    "error",
                    "End of file reached before report END marker.",
                    current.end_line,
                )
            )
            reports.append(current)

        if not reports:
            issues.append(ParseIssue("error", "No supported VSS daily reports were found in the source file."))
        return reports, issues

    def parse_report(self, logical: LogicalReport, sequence_no: int = 0) -> ParsedReport:
        header = self._parse_header(logical)
        header["sequence_no"] = sequence_no
        issues = list(logical.issues)
        joined = "\n".join(line for _, line in logical.lines)
        explicit_no_data = bool(_NO_DATA_RE.search(joined))

        if not logical.complete:
            header["data_status"] = "incomplete"
            header["processing_status"] = "error"
            return ParsedReport(header=header, lines=[], issues=issues)

        if explicit_no_data:
            header["data_status"] = "no_data"
            header["processing_status"] = "success"
            return ParsedReport(header=header, lines=[], issues=issues)

        parser = {
            "VSS-110": self._parse_110,
            "VSS-120": self._parse_120,
            "VSS-130": self._parse_130,
            "VSS-140": self._parse_140,
            "VSS-210": self._parse_210,
        }[logical.report_code]
        data_lines, body_issues = parser(logical)
        issues.extend(body_issues)

        if data_lines:
            header["data_status"] = "data"
            header["processing_status"] = "warning" if any(i.severity == "warning" for i in issues) else "success"
        else:
            header["data_status"] = "parse_error"
            header["processing_status"] = "error"
            issues.append(
                ParseIssue(
                    "error",
                    "Report contains no NO DATA marker, but no supported data rows could be parsed.",
                    logical.start_line,
                )
            )
        return ParsedReport(header=header, lines=data_lines, issues=issues)

    # ------------------------------------------------------------------
    # Header parsing
    # ------------------------------------------------------------------

    def _parse_header(self, logical: LogicalReport) -> Dict:
        lines = [line for _, line in logical.lines]
        first_line = lines[0] if lines else ""
        report_code = logical.report_code
        page_numbers = []
        service_name = ""
        reporting_for = ""
        rollup_to = ""
        funds_xfer = ""
        settlement_currency = ""
        clearing_currencies: List[str] = []
        proc_date = None
        report_date = None
        funds_transfer_amount = None
        funds_transfer_direction = ""

        for line in lines:
            page_match = re.search(r"PAGE:\s*(\d+)", line)
            if line.lstrip().startswith("REPORT ID:") and page_match:
                page_numbers.append(int(page_match.group(1)))

            if line.lstrip().startswith("REPORTING FOR:") and not reporting_for:
                for service in SERVICE_NAMES:
                    if service in line:
                        service_name = service
                        break
                reporting_for = self._header_entity_value(line, "REPORTING FOR:", service_name or "PROC DATE:")
                proc_date = proc_date or self._extract_label_date(line, "PROC DATE:")

            elif line.lstrip().startswith("ROLLUP TO:") and not rollup_to:
                report_title = REPORT_NAMES.get(report_code, "").upper()
                rollup_to = self._header_entity_value(line, "ROLLUP TO:", report_title or "REPORT DATE:")
                report_date = report_date or self._extract_label_date(line, "REPORT DATE:")

            elif line.lstrip().startswith("FUNDS XFER ENTITY:") and not funds_xfer:
                funds_xfer = line.split("FUNDS XFER ENTITY:", 1)[1].strip()

            elif line.lstrip().startswith("SETTLEMENT CURRENCY:") and not settlement_currency:
                value = line.split("SETTLEMENT CURRENCY:", 1)[1].strip().split()
                settlement_currency = value[0] if value else ""

            elif line.lstrip().startswith("CLEARING CURRENCY:"):
                value = line.split("CLEARING CURRENCY:", 1)[1].strip().split()
                if value:
                    code = value[0]
                    if code and code not in clearing_currencies:
                        clearing_currencies.append(code)

            elif "FUNDS TRANSFER AMOUNT:" in line and funds_transfer_amount is None:
                token = line.split("FUNDS TRANSFER AMOUNT:", 1)[1].strip().split()[0]
                amount, direction = self._parse_amount(token)
                funds_transfer_amount = amount
                funds_transfer_direction = direction

            if proc_date is None:
                proc_date = self._extract_label_date(line, "PROC DATE:")
            if report_date is None:
                report_date = self._extract_label_date(line, "REPORT DATE:")

        reporting_for_id, reporting_for_name = self._split_entity(reporting_for)
        rollup_to_id, rollup_to_name = self._split_entity(rollup_to)
        funds_xfer_id, funds_xfer_name = self._split_entity(funds_xfer)
        if not service_name:
            for line in lines[:6]:
                for service in SERVICE_NAMES:
                    if service in line:
                        service_name = service
                        break

        return {
            "report_code": report_code,
            "report_name": REPORT_NAMES.get(report_code, report_code),
            "service_name": service_name.title() if service_name else "",
            "reporting_for_ref": reporting_for_id,
            "reporting_for_name": reporting_for_name,
            "rollup_to_ref": rollup_to_id,
            "rollup_to_name": rollup_to_name,
            "funds_xfer_entity_ref": funds_xfer_id,
            "funds_xfer_entity_name": funds_xfer_name,
            "settlement_currency": settlement_currency,
            "clearing_currencies": ", ".join(clearing_currencies),
            "processing_date": proc_date,
            "report_date": report_date,
            "first_page": min(page_numbers) if page_numbers else 1,
            "last_page": max(page_numbers) if page_numbers else 1,
            "page_count": len(page_numbers) if page_numbers else 1,
            "source_start_line": logical.start_line,
            "source_end_line": logical.end_line,
            "funds_transfer_amount": funds_transfer_amount,
            "funds_transfer_direction": funds_transfer_direction,
            "raw_header": "\n".join(lines[:8]),
        }

    @staticmethod
    def _header_entity_value(line: str, label: str, stop_text: str) -> str:
        value = line.split(label, 1)[1]
        if stop_text and stop_text in value:
            value = value.split(stop_text, 1)[0]
        elif "PROC DATE:" in value:
            value = value.split("PROC DATE:", 1)[0]
        elif "REPORT DATE:" in value:
            value = value.split("REPORT DATE:", 1)[0]
        return value.strip()

    @staticmethod
    def _split_entity(value: str) -> Tuple[str, str]:
        value = (value or "").strip()
        match = re.match(r"^(\d+)\s*(.*)$", value)
        if not match:
            return "", value
        return match.group(1), match.group(2).strip()

    @staticmethod
    def _extract_label_date(line: str, label: str):
        if label not in line:
            return None
        remainder = line.split(label, 1)[1].strip()
        token = remainder.split()[0] if remainder else ""
        return VSSParser._parse_date(token)

    @staticmethod
    def _parse_date(token: str):
        token = (token or "").strip().upper()
        if not _DATE_RE.match(token):
            return None
        try:
            return datetime.strptime(token, "%d%b%y").date()
        except ValueError:
            return None

    @staticmethod
    def _is_end_marker(line: str, report_code: str) -> bool:
        return bool(
            re.search(
                rf"\*{{3}}\s+END OF\s+{re.escape(report_code)}\s+REPORT\s+\*{{3}}",
                line,
                flags=re.IGNORECASE,
            )
        )

    @staticmethod
    def _parse_amount(token: str) -> Tuple[Optional[Decimal], str]:
        token = (token or "").strip()
        if not token:
            return None, ""
        match = _AMOUNT_RE.match(token)
        if not match:
            return None, ""
        try:
            amount = Decimal(match.group(1).replace(",", ""))
        except InvalidOperation:
            return None, ""
        return amount, (match.group(2) or "").upper()

    @staticmethod
    def _parse_int(token: str) -> Optional[int]:
        token = (token or "").strip().replace(",", "")
        if not token:
            return None
        if not re.fullmatch(r"\d+", token):
            return None
        return int(token)

    @staticmethod
    def _page_from_line(line: str, fallback: int) -> int:
        m = re.search(r"PAGE:\s*(\d+)", line)
        return int(m.group(1)) if m else fallback

    @staticmethod
    def _record_type(description: str) -> str:
        desc = re.sub(r"\s+", " ", (description or "").strip()).upper()
        if desc.startswith("NET ") or desc.startswith("NET SETTLEMENT"):
            return "net"
        if desc.startswith("TOTAL "):
            return "total"
        return "detail"

    @staticmethod
    def _normalize_desc(value: str) -> str:
        return re.sub(r"\s+", " ", (value or "").strip())

    @staticmethod
    def _skip_common_line(stripped: str) -> bool:
        upper = stripped.upper()
        if not stripped:
            return True
        prefixes = (
            "REPORT ID:",
            "REPORTING FOR:",
            "ROLLUP TO:",
            "FUNDS XFER ENTITY:",
            "SETTLEMENT CURRENCY:",
            "CLEARING CURRENCY:",
        )
        if upper.startswith(prefixes):
            return True
        if "VISANET SETTLEMENT SERVICE" in upper:
            return True
        if "NO DATA FOR THIS REPORT" in upper or "END OF VSS-" in upper:
            return True
        return False

    # ------------------------------------------------------------------
    # VSS-110
    # ------------------------------------------------------------------

    def _parse_110(self, logical: LogicalReport) -> Tuple[List[Dict], List[ParseIssue]]:
        result: List[Dict] = []
        issues: List[ParseIssue] = []
        section = ""
        page = 1
        section_names = {"INTERCHANGE VALUE", "REIMBURSEMENT FEES", "VISA CHARGES", "TOTAL"}
        labels = (
            "TOTAL INTERCHANGE VALUE",
            "TOTAL REIMBURSEMENT FEES",
            "TOTAL VISA CHARGES",
            "NET SETTLEMENT AMOUNT",
            "TOTAL ACQUIRER",
            "TOTAL ISSUER",
            "TOTAL OTHER",
        )

        for line_no, raw in logical.lines:
            if raw.lstrip().startswith("REPORT ID:"):
                page = self._page_from_line(raw, page)
            stripped = raw.strip()
            if stripped in section_names:
                section = stripped
                continue
            label = next((x for x in labels if stripped.startswith(x)), None)
            if not label or not section:
                continue
            remainder = stripped[len(label) :].strip().split()
            count = None
            credit = debit = total = None
            direction = ""
            if section == "INTERCHANGE VALUE":
                if len(remainder) >= 4:
                    count = self._parse_int(remainder[0])
                    credit, _ = self._parse_amount(remainder[-3])
                    debit, _ = self._parse_amount(remainder[-2])
                    total, direction = self._parse_amount(remainder[-1])
                else:
                    issues.append(ParseIssue("warning", f"Could not fully parse VSS-110 row: {stripped}", line_no, raw))
                    continue
            else:
                if len(remainder) >= 3:
                    credit, _ = self._parse_amount(remainder[-3])
                    debit, _ = self._parse_amount(remainder[-2])
                    total, direction = self._parse_amount(remainder[-1])
                else:
                    issues.append(ParseIssue("warning", f"Could not fully parse VSS-110 row: {stripped}", line_no, raw))
                    continue
            result.append(
                {
                    "source_page": page,
                    "source_line_no": line_no,
                    "particulars": section,
                    "entity": label,
                    "count": count,
                    "credit_amount": credit,
                    "debit_amount": debit,
                    "total_amount": total,
                    "direction": direction,
                    "record_type": (
                        "net"
                        if label == "NET SETTLEMENT AMOUNT"
                        else "total"
                        if label in ("TOTAL INTERCHANGE VALUE", "TOTAL REIMBURSEMENT FEES", "TOTAL VISA CHARGES")
                        else "detail"
                    ),
                    "raw_source_line": raw.rstrip(),
                }
            )
        return result, issues

    # ------------------------------------------------------------------
    # VSS-120
    # ------------------------------------------------------------------

    def _parse_120(self, logical: LogicalReport) -> Tuple[List[Dict], List[ParseIssue]]:
        result: List[Dict] = []
        issues: List[ParseIssue] = []
        page = 1
        clearing_currency = ""
        business_mode = ""
        transaction_category = ""
        last_detail_transaction_type = ""
        last_detail_disposition = ""
        body_started = False

        for line_no, raw in logical.lines:
            if raw.lstrip().startswith("REPORT ID:"):
                page = self._page_from_line(raw, page)
                continue
            stripped = raw.strip()
            upper = stripped.upper()
            if raw.lstrip().startswith("CLEARING CURRENCY:"):
                value = raw.split("CLEARING CURRENCY:", 1)[1].strip().split()
                clearing_currency = value[0] if value else ""
                continue
            if self._skip_common_line(stripped):
                continue
            if upper in ("ACQUIRER TRANSACTIONS", "ISSUER TRANSACTIONS", "OTHER TRANSACTIONS"):
                business_mode = upper.replace(" TRANSACTIONS", "")
                transaction_category = ""
                last_detail_transaction_type = ""
                last_detail_disposition = ""
                body_started = True
                continue
            if not body_started:
                continue
            header_tokens = set(upper.split())
            if header_tokens and header_tokens <= {
                "AMOUNT",
                "CLEARING",
                "COUNT",
                "CREDITS",
                "CURRENCY",
                "DATE",
                "DEBITS",
                "INTERCHANGE",
                "TABLE",
                "VALUE",
            }:
                # Repeated multi-line column headers on every source page.
                continue
            padded = raw.ljust(133)
            description = self._normalize_desc(padded[0:38])
            currency_date_token = padded[38:52].strip()
            count_token = padded[52:70].strip()
            clearing_token = padded[70:96].strip()
            credit_token = padded[96:117].strip()
            debit_token = padded[117:133].strip()
            has_values = any((count_token, clearing_token, credit_token, debit_token))

            if has_values:
                count = self._parse_int(count_token)
                clearing_amount, clearing_direction = self._parse_amount(clearing_token)
                credit, _ = self._parse_amount(credit_token)
                debit, _ = self._parse_amount(debit_token)
                if description:
                    disposition = "RVRSL" if re.search(r"\bRVRSL\b", description, re.IGNORECASE) else ""
                    transaction_type = re.sub(r"\s+RVRSL\b", "", description, flags=re.IGNORECASE).strip()
                    record_type = self._record_type(description)
                    if record_type == "detail":
                        last_detail_transaction_type = transaction_type
                        last_detail_disposition = disposition
                    else:
                        last_detail_transaction_type = ""
                        last_detail_disposition = ""
                elif last_detail_transaction_type:
                    # VisaNet prints a transaction description once and leaves
                    # it blank on subsequent currency-date detail rows.
                    transaction_type = last_detail_transaction_type
                    disposition = last_detail_disposition
                    record_type = "detail"
                else:
                    issues.append(
                        ParseIssue(
                            "warning",
                            "VSS-120 value row has no description and no preceding detail row to inherit.",
                            line_no,
                            raw,
                        )
                    )
                    continue
                row_transaction_category = transaction_category
                summary_target = re.sub(
                    r"^(?:TOTAL|NET)\s+", "", transaction_type, flags=re.IGNORECASE
                ).strip()
                if record_type != "detail" and self._normalize_desc(summary_target).upper() == (
                    f"{business_mode} INTERCHANGE"
                ):
                    # Business-mode summaries are siblings of transaction
                    # categories, not children of the last category printed.
                    row_transaction_category = ""
                result.append(
                    {
                        "source_page": page,
                        "source_line_no": line_no,
                        "clearing_currency": clearing_currency,
                        "business_mode": business_mode,
                        "transaction_category": row_transaction_category,
                        "transaction_type": transaction_type,
                        "disposition": disposition,
                        "currency_table_date": self._parse_date(currency_date_token),
                        "count": count,
                        "clearing_amount": clearing_amount,
                        "clearing_direction": clearing_direction,
                        "interchange_credit": credit,
                        "interchange_debit": debit,
                        "record_type": record_type,
                        "raw_source_line": raw.rstrip(),
                    }
                )
                continue

            # Hierarchy/category lines. Do not let totals without values overwrite state.
            if not stripped or upper.startswith(("TOTAL ", "NET ")):
                continue
            indent = len(raw) - len(raw.lstrip(" "))
            if indent <= 4 and upper not in ("ACQUIRER TRANSACTIONS", "ISSUER TRANSACTIONS", "OTHER TRANSACTIONS"):
                transaction_category = self._normalize_desc(stripped)
                last_detail_transaction_type = ""
                last_detail_disposition = ""
        return result, issues

    # ------------------------------------------------------------------
    # VSS-130
    # ------------------------------------------------------------------

    def _parse_130(self, logical: LogicalReport) -> Tuple[List[Dict], List[ParseIssue]]:
        result: List[Dict] = []
        issues: List[ParseIssue] = []
        page = 1
        business_mode = ""
        category = ""
        txn_type = ""
        program = ""
        region = ""
        body_started = False

        for line_no, raw in logical.lines:
            if raw.lstrip().startswith("REPORT ID:"):
                page = self._page_from_line(raw, page)
                continue
            stripped = raw.strip()
            upper = stripped.upper()
            if self._skip_common_line(stripped):
                continue
            if upper in ("ACQUIRER TRANSACTIONS", "ISSUER TRANSACTIONS", "OTHER TRANSACTIONS"):
                business_mode = upper.replace(" TRANSACTIONS", "")
                category = txn_type = program = region = ""
                body_started = True
                continue
            if not body_started:
                continue
            if upper in ("COUNT", "INTERCHANGE", "AMOUNT", "CREDITS", "DEBITS") or (
                "COUNT" in upper and "INTERCHANGE" in upper
            ):
                continue

            padded = raw.ljust(133)
            desc = self._normalize_desc(padded[0:55])
            count_token = padded[55:68].strip()
            interchange_token = padded[68:96].strip()
            fee_credit_token = padded[96:118].strip()
            fee_debit_token = padded[118:133].strip()
            has_values = any((count_token, interchange_token, fee_credit_token, fee_debit_token))

            if has_values and desc:
                count = self._parse_int(count_token)
                interchange_amount, interchange_direction = self._parse_amount(interchange_token)
                fee_credit, _ = self._parse_amount(fee_credit_token)
                fee_debit, _ = self._parse_amount(fee_debit_token)
                rtype = self._record_type(desc)
                fee_category = desc if rtype == "detail" else ""
                row_category = category
                row_txn_type = txn_type
                row_program = program
                row_region = region
                if rtype != "detail":
                    # Summary indentation identifies the hierarchy node being
                    # closed. Retain that node and its ancestors only.
                    indent = len(raw) - len(raw.lstrip(" "))
                    if indent <= 1:  # business-mode reimbursement summary
                        row_category = row_txn_type = row_program = row_region = ""
                    elif indent <= 5:  # transaction-category summary
                        row_txn_type = row_program = row_region = ""
                    elif indent <= 8:  # transaction-type summary
                        row_program = row_region = ""
                    elif indent <= 11:  # program-network summary
                        row_region = ""
                result.append(
                    {
                        "source_page": page,
                        "source_line_no": line_no,
                        "business_mode": business_mode,
                        "transaction_category": row_category,
                        "transaction_type": row_txn_type,
                        "program_network": row_program,
                        "region_country": row_region,
                        "fee_category": fee_category,
                        "description": desc,
                        "count": count,
                        "interchange_amount": interchange_amount,
                        "interchange_direction": interchange_direction,
                        "fee_credit": fee_credit,
                        "fee_debit": fee_debit,
                        "record_type": rtype,
                        "raw_source_line": raw.rstrip(),
                    }
                )
                continue

            if not stripped or upper.startswith(("TOTAL ", "NET ")):
                continue
            # Ignore repeated column header fragments.
            if upper in {"FEE", "REIMBURSEMENT FEE", "REIMBURSEMENT"}:
                continue
            indent = len(raw) - len(raw.lstrip(" "))
            if indent <= 5:
                category = self._normalize_desc(stripped)
                txn_type = program = region = ""
            elif indent <= 8:
                txn_type = self._normalize_desc(stripped)
                program = region = ""
            elif indent <= 11:
                program = self._normalize_desc(stripped)
                region = ""
            elif indent <= 14:
                region = self._normalize_desc(stripped)
        return result, issues

    # ------------------------------------------------------------------
    # VSS-140
    # ------------------------------------------------------------------

    def _parse_140(self, logical: LogicalReport) -> Tuple[List[Dict], List[ParseIssue]]:
        result: List[Dict] = []
        issues: List[ParseIssue] = []
        page = 1
        business_mode = ""
        charge_category = ""
        txn_category = ""
        txn_type = ""
        program = ""
        body_started = False

        for line_no, raw in logical.lines:
            if raw.lstrip().startswith("REPORT ID:"):
                page = self._page_from_line(raw, page)
                continue
            stripped = raw.strip()
            upper = stripped.upper()
            if self._skip_common_line(stripped):
                continue
            if upper in ("ACQUIRER TRANSACTIONS", "ISSUER TRANSACTIONS", "OTHER TRANSACTIONS"):
                business_mode = upper.replace(" TRANSACTIONS", "")
                charge_category = txn_category = txn_type = program = ""
                body_started = True
                continue
            if not body_started:
                continue
            if "COUNT" in upper and "INTERCHANGE" in upper:
                continue
            if upper in ("AMOUNT", "CREDITS", "DEBITS"):
                continue

            padded = raw.ljust(133)
            desc = self._normalize_desc(padded[0:60])
            count_token = padded[60:72].strip()
            interchange_token = padded[72:96].strip()
            charge_credit_token = padded[96:118].strip()
            charge_debit_token = padded[118:133].strip()
            has_values = any((count_token, interchange_token, charge_credit_token, charge_debit_token))

            if has_values and desc:
                count = self._parse_int(count_token)
                interchange_amount, interchange_direction = self._parse_amount(interchange_token)
                charge_credit, _ = self._parse_amount(charge_credit_token)
                charge_debit, _ = self._parse_amount(charge_debit_token)
                rtype = self._record_type(desc)
                region_country = desc if rtype == "detail" else ""
                row_charge_category = charge_category
                row_txn_category = txn_category
                row_txn_type = txn_type
                row_program = program
                if rtype != "detail":
                    indent = len(raw) - len(raw.lstrip(" "))
                    if indent <= 1:  # business-mode charge summary
                        row_charge_category = row_txn_category = row_txn_type = row_program = ""
                    elif indent <= 4:  # charge-category summary
                        row_txn_category = row_txn_type = row_program = ""
                    elif indent <= 7:  # transaction-category summary
                        row_txn_type = row_program = ""
                    elif indent <= 10:  # transaction-type summary
                        row_program = ""
                result.append(
                    {
                        "source_page": page,
                        "source_line_no": line_no,
                        "business_mode": business_mode,
                        "charge_category": row_charge_category,
                        "transaction_category": row_txn_category,
                        "transaction_type": row_txn_type,
                        "program_network": row_program,
                        "region_country": region_country,
                        "description": desc,
                        "count": count,
                        "interchange_amount": interchange_amount,
                        "interchange_direction": interchange_direction,
                        "visa_charge_credit": charge_credit,
                        "visa_charge_debit": charge_debit,
                        "record_type": rtype,
                        "raw_source_line": raw.rstrip(),
                    }
                )
                continue

            if not stripped or upper.startswith(("TOTAL ", "NET ")):
                continue
            indent = len(raw) - len(raw.lstrip(" "))
            # Observed VSS-140 hierarchy: charge section (3), category (5), type (7), program (9), region/detail (12).
            if indent <= 4:
                charge_category = self._normalize_desc(stripped)
                txn_category = txn_type = program = ""
            elif indent <= 6:
                txn_category = self._normalize_desc(stripped)
                txn_type = program = ""
            elif indent <= 8:
                txn_type = self._normalize_desc(stripped)
                program = ""
            elif indent <= 11:
                program = self._normalize_desc(stripped)
        return result, issues

    # ------------------------------------------------------------------
    # VSS-210
    # ------------------------------------------------------------------

    def _parse_210(self, logical: LogicalReport) -> Tuple[List[Dict], List[ParseIssue]]:
        result: List[Dict] = []
        issues: List[ParseIssue] = []
        page = 1
        clearing_currency = ""
        business_mode = ""
        txn_category = ""
        txn_type = ""
        pending_total_label = ""
        body_started = False

        for line_no, raw in logical.lines:
            if raw.lstrip().startswith("REPORT ID:"):
                page = self._page_from_line(raw, page)
                continue
            stripped = raw.strip()
            upper = stripped.upper()
            if raw.lstrip().startswith("CLEARING CURRENCY:"):
                value = raw.split("CLEARING CURRENCY:", 1)[1].strip().split()
                clearing_currency = value[0] if value else ""
                continue
            if self._skip_common_line(stripped):
                continue
            if upper in ("ACQUIRER TRANSACTIONS", "ISSUER TRANSACTIONS", "OTHER TRANSACTIONS"):
                business_mode = upper.replace(" TRANSACTIONS", "")
                txn_category = txn_type = pending_total_label = ""
                body_started = True
                continue
            if not body_started:
                continue
            if "SETTLEMENT CURRENCY" in upper or "CLEARING CURRENCY" in upper:
                continue
            if any(x in upper for x in ("INTERCHANGE", "CONVERSION", "OPT ISSUER")) and not upper.startswith("TOTAL "):
                continue
            if upper in ("AMOUNT", "FEE"):
                continue

            padded = raw.ljust(133)
            desc = self._normalize_desc(padded[0:38])
            settlement_interchange_token = padded[38:56].strip()
            settlement_conversion_token = padded[56:77].strip()
            clearing_interchange_token = padded[77:98].strip()
            clearing_conversion_token = padded[98:116].strip()
            optional_issuer_token = padded[116:133].strip()
            has_values = any(
                (
                    settlement_interchange_token,
                    settlement_conversion_token,
                    clearing_interchange_token,
                    clearing_conversion_token,
                    optional_issuer_token,
                )
            )

            if has_values:
                effective_desc = desc or pending_total_label
                if not effective_desc:
                    continue
                settlement_interchange, settlement_direction = self._parse_amount(settlement_interchange_token)
                settlement_conversion, _ = self._parse_amount(settlement_conversion_token)
                clearing_interchange, clearing_direction = self._parse_amount(clearing_interchange_token)
                clearing_conversion, _ = self._parse_amount(clearing_conversion_token)
                optional_issuer, optional_issuer_direction = self._parse_amount(optional_issuer_token)
                rtype = self._record_type(effective_desc)
                program_network = effective_desc if rtype == "detail" else ""
                row_txn_category = txn_category
                row_txn_type = txn_type
                if rtype != "detail":
                    summary_target = re.sub(
                        r"^(?:TOTAL|NET)\s+", "", effective_desc, flags=re.IGNORECASE
                    ).strip()
                    if self._normalize_desc(summary_target).upper() == self._normalize_desc(txn_category).upper():
                        row_txn_type = ""
                    elif self._normalize_desc(summary_target).upper() != self._normalize_desc(txn_type).upper():
                        # Report/business summary: neither transaction node is
                        # an ancestor of this row.
                        row_txn_category = row_txn_type = ""
                result.append(
                    {
                        "source_page": page,
                        "source_line_no": line_no,
                        "clearing_currency": clearing_currency,
                        "business_mode": business_mode,
                        "transaction_category": row_txn_category,
                        "transaction_type": row_txn_type,
                        "program_network": program_network,
                        "description": effective_desc,
                        "settlement_interchange_amount": settlement_interchange,
                        "settlement_interchange_direction": settlement_direction,
                        "settlement_conversion_fee": settlement_conversion,
                        "clearing_interchange_amount": clearing_interchange,
                        "clearing_interchange_direction": clearing_direction,
                        "clearing_conversion_fee": clearing_conversion,
                        "optional_issuer_fee": optional_issuer,
                        "optional_issuer_fee_direction": optional_issuer_direction,
                        "record_type": rtype,
                        "raw_source_line": raw.rstrip(),
                    }
                )
                pending_total_label = ""
                continue

            if not stripped:
                continue
            if upper.startswith("TOTAL "):
                pending_total_label = self._normalize_desc(stripped)
                continue
            if upper.startswith("NET "):
                pending_total_label = self._normalize_desc(stripped)
                continue
            indent = len(raw) - len(raw.lstrip(" "))
            if indent <= 1:
                txn_category = self._normalize_desc(stripped)
                txn_type = ""
            elif indent <= 2:
                txn_type = self._normalize_desc(stripped)
        return result, issues
