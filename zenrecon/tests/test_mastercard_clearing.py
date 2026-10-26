# -*- coding: utf-8 -*-
import base64
import unittest

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ..services.mastercard_clearing_parser import parse_clearing_report


SAMPLE_CLEARING = """1IP727020-AA NOTIFICATION RUN DATE: 10/20/26 CLEARING CYCLE 7
MEMBER ID: 12345
BUSINESS SERVICE LEVEL: TEST
BUSINESS SERVICE ID: SVC01
FILE ID: FILE01
2026-10-21
MASTERCARD SETTLED
 FIRST PRES. PURCHASE ORIG A1 2 1,000.00 DR 050-BDT 10.00 CR 050-BDT
1IP728010-AA CLEARING DAY TOTAL RUN DATE: 10/20/26
MEMBER ID: 12345
2026-10-21
CLEARING DAY TOTAL AS OF CLEARING CYCLE 7
  050-BDT 990.00 DR
"""


class TestMastercardClearingParser(unittest.TestCase):
    def test_detail_and_day_total_rows(self):
        rows = parse_clearing_report(SAMPLE_CLEARING)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["report_id"], "1IP727020-AA")
        self.assertEqual(rows[0]["recon_amount"], 1000.0)
        self.assertEqual(rows[0]["member_id"], "12345")
        self.assertFalse(rows[0]["is_day_total"])
        self.assertEqual(rows[1]["report_id"], "1IP728010-AA")
        self.assertEqual(rows[1]["net_amount"], 990.0)
        self.assertTrue(rows[1]["is_day_total"])


@tagged("post_install", "-at_install")
class TestMastercardClearingImport(TransactionCase):
    def test_upload_wizard_stores_dedicated_clearing_rows(self):
        wizard = self.env["mastercard.clearing.import.wizard"].create({
            "filename": "daily-clearing.txt",
            "file": base64.b64encode(SAMPLE_CLEARING.encode()),
        })

        action = wizard.action_process()
        clearing_import = self.env["mastercard.clearing.import"].browse(action["res_id"])

        self.assertEqual(clearing_import.state, "done")
        self.assertEqual(clearing_import.filename, "daily-clearing.txt")
        self.assertEqual(clearing_import.line_count, 2)
        self.assertEqual(clearing_import.line_ids.mapped("is_day_total"), [False, True])
