# -*- coding: utf-8 -*-
from decimal import Decimal
import unittest

from ..services.vss_parser import VSSParser


class TestVSSParser(unittest.TestCase):
    @staticmethod
    def _row_120(description, count="", clearing="", credit="", debit=""):
        return f"{description:<38}{'':14}{str(count):>18}{str(clearing):>26}{str(credit):>21}{str(debit):>16}"

    @staticmethod
    def _row_130(description, count="", interchange="", credit="", debit=""):
        return f"{description:<55}{str(count):>13}{str(interchange):>28}{str(credit):>22}{str(debit):>15}"

    @staticmethod
    def _row_140(description, count="", interchange="", credit="", debit=""):
        return f"{description:<60}{str(count):>12}{str(interchange):>24}{str(credit):>22}{str(debit):>15}"

    @staticmethod
    def _row_210(description, settlement="", settlement_fee="", clearing="", clearing_fee="", issuer_fee=""):
        return (
            f"{description:<38}{str(settlement):>18}{str(settlement_fee):>21}"
            f"{str(clearing):>21}{str(clearing_fee):>18}{str(issuer_fee):>17}"
        )

    def test_vss_120_continuation_rows_inherit_transaction_hierarchy(self):
        source = """\fREPORT ID:  VSS-120                                         VISANET SETTLEMENT SERVICE                        PAGE:              1
 REPORTING FOR:      1000126173 CITY BANK LTD              INTERNATIONAL SETTLEMENT SERVICE                    PROC DATE:   01MAR18
 ROLLUP TO:          1000126173 CITY BANK LTD                  INTERCHANGE VALUE REPORT                        REPORT DATE: 01MAR18
 FUNDS XFER ENTITY:  1000126173 CITY BANK LTD
 SETTLEMENT CURRENCY:  USD
 CLEARING CURRENCY:    BDT
 ACQUIRER TRANSACTIONS
   ATM CASH
    ORIGINAL WITHDRAWAL                28FEB18                  60           715,000.00CR             8,624.76
                                       01MAR18                  83           990,000.00CR            11,949.30
    TOTAL ORIGINAL WITHDRAWAL                                  143         1,705,000.00CR            20,574.06
 *** END OF VSS-120 REPORT ***"""

        reports, issues = VSSParser().parse(source)

        self.assertFalse(issues)
        self.assertEqual(len(reports), 1)
        self.assertFalse(reports[0].issues)
        self.assertEqual(len(reports[0].lines), 3)
        first, continuation, total = reports[0].lines
        self.assertEqual(first["transaction_category"], "ATM CASH")
        self.assertEqual(continuation["transaction_category"], "ATM CASH")
        self.assertEqual(continuation["transaction_type"], "ORIGINAL WITHDRAWAL")
        self.assertEqual(continuation["currency_table_date"].isoformat(), "2018-03-01")
        self.assertEqual(continuation["count"], 83)
        self.assertEqual(continuation["clearing_amount"], Decimal("990000.00"))
        self.assertEqual(continuation["interchange_credit"], Decimal("11949.30"))
        self.assertEqual(continuation["source_line_no"], first["source_line_no"] + 1)
        self.assertEqual(total["source_line_no"], continuation["source_line_no"] + 1)

    def test_vss_120_business_summary_does_not_inherit_last_category(self):
        source = "\n".join(
            [
                "REPORT ID:  VSS-120                                         VISANET SETTLEMENT SERVICE                        PAGE:              1",
                " REPORTING FOR:      1000000001 TEST ENTITY               INTERNATIONAL SETTLEMENT SERVICE                     PROC DATE:   01MAR18",
                " ROLLUP TO:          1000000001 TEST ENTITY                   INTERCHANGE VALUE REPORT                        REPORT DATE: 01MAR18",
                " FUNDS XFER ENTITY:  1000000001 TEST ENTITY",
                " SETTLEMENT CURRENCY:  BDT",
                " CLEARING CURRENCY:    BDT",
                " ISSUER TRANSACTIONS",
                "   MERCHANDISE CREDIT",
                self._row_120("    ORIGINAL", 1, "399.00CR", "399.00"),
                self._row_120("   TOTAL MERCHANDISE CREDIT", 1, "399.00CR", "399.00"),
                self._row_120("   NET MERCHANDISE CREDIT", "", "", "399.00"),
                self._row_120(" TOTAL ISSUER INTERCHANGE", 1, "399.00CR", "399.00"),
                self._row_120(" NET ISSUER INTERCHANGE", "", "", "399.00"),
                " *** END OF VSS-120 REPORT ***",
            ]
        )

        reports, issues = VSSParser().parse(source)

        self.assertFalse(issues)
        rows = reports[0].lines
        category_total = next(row for row in rows if row["transaction_type"] == "TOTAL MERCHANDISE CREDIT")
        business_total = next(row for row in rows if row["transaction_type"] == "TOTAL ISSUER INTERCHANGE")
        business_net = next(row for row in rows if row["transaction_type"] == "NET ISSUER INTERCHANGE")
        self.assertEqual(category_total["transaction_category"], "MERCHANDISE CREDIT")
        self.assertFalse(business_total["transaction_category"])
        self.assertFalse(business_net["transaction_category"])

    def test_vss_130_summary_rows_keep_only_valid_ancestors(self):
        source = "\n".join(
            [
                "REPORT ID:  VSS-130                                         VISANET SETTLEMENT SERVICE                        PAGE:              1",
                " REPORTING FOR:      1000000001 TEST ENTITY               INTERNATIONAL SETTLEMENT SERVICE                     PROC DATE:   01MAR18",
                " ROLLUP TO:          1000000001 TEST ENTITY                  REIMBURSEMENT FEES REPORT                        REPORT DATE: 01MAR18",
                " FUNDS XFER ENTITY:  1000000001 TEST ENTITY",
                " SETTLEMENT CURRENCY:  BDT",
                " ISSUER TRANSACTIONS",
                "    PURCHASE",
                "       ORIGINAL SALE",
                "          VISA A.P.",
                "             BNGLDESH - BNGLDESH",
                self._row_130("                AUTHENT SEC PLAT", 1, "100.00DB", "2.00"),
                self._row_130("             TOTAL BNGLDESH - BNGLDESH", "", "", "2.00"),
                self._row_130("          TOTAL VISA A.P.", "", "", "2.00"),
                self._row_130("       TOTAL ORIGINAL SALE", 1, "100.00DB", "2.00"),
                self._row_130("    TOTAL PURCHASE", 1, "100.00DB", "2.00"),
                self._row_130("    NET PURCHASE", "", "", "2.00"),
                self._row_130(" TOTAL ISSUER REIMB FEES", "", "", "2.00"),
                self._row_130(" NET ISSUER REIMB FEES", "", "", "2.00"),
                " *** END OF VSS-130 REPORT ***",
            ]
        )

        reports, issues = VSSParser().parse(source)

        self.assertFalse(issues)
        rows = {row["description"]: row for row in reports[0].lines}
        region = rows["TOTAL BNGLDESH - BNGLDESH"]
        self.assertEqual(
            (region["transaction_category"], region["transaction_type"], region["program_network"], region["region_country"]),
            ("PURCHASE", "ORIGINAL SALE", "VISA A.P.", "BNGLDESH - BNGLDESH"),
        )
        program = rows["TOTAL VISA A.P."]
        self.assertEqual(program["program_network"], "VISA A.P.")
        self.assertFalse(program["region_country"])
        transaction = rows["TOTAL ORIGINAL SALE"]
        self.assertEqual(transaction["transaction_type"], "ORIGINAL SALE")
        self.assertFalse(transaction["program_network"])
        category = rows["TOTAL PURCHASE"]
        self.assertEqual(category["transaction_category"], "PURCHASE")
        self.assertFalse(category["transaction_type"])
        business = rows["TOTAL ISSUER REIMB FEES"]
        self.assertFalse(business["transaction_category"])
        self.assertFalse(business["transaction_type"])
        self.assertFalse(business["program_network"])
        self.assertFalse(business["region_country"])

    def test_vss_140_and_210_summary_rows_unwind_hierarchy(self):
        source_140 = "\n".join(
            [
                "REPORT ID:  VSS-140                                         VISANET SETTLEMENT SERVICE                        PAGE:              1",
                " REPORTING FOR:      1000000001 TEST ENTITY               INTERNATIONAL SETTLEMENT SERVICE                     PROC DATE:   01MAR18",
                " ROLLUP TO:          1000000001 TEST ENTITY                       VISA CHARGES REPORT                            REPORT DATE: 01MAR18",
                " FUNDS XFER ENTITY:  1000000001 TEST ENTITY",
                " SETTLEMENT CURRENCY:  BDT",
                " ISSUER TRANSACTIONS",
                "   CURRENCY CONVERSION FEES",
                "     PURCHASE",
                "       ORIGINAL SALE",
                "         VISA INTERNATIONAL",
                self._row_140("            BNGLDESH - BNGLDESH", 1, "100.00DB", "2.00"),
                self._row_140("             TOTAL VISA INTERNATIONAL", "", "", "2.00"),
                self._row_140("       TOTAL PURCHASE", 1, "100.00DB", "2.00"),
                self._row_140("    TOTAL CURRENCY CONVERSION FEES", "", "", "2.00"),
                self._row_140(" TOTAL ISSUER CHARGES", "", "", "2.00"),
                " *** END OF VSS-140 REPORT ***",
            ]
        )
        reports, issues = VSSParser().parse(source_140)
        self.assertFalse(issues)
        rows = {row["description"]: row for row in reports[0].lines}
        self.assertEqual(rows["TOTAL VISA INTERNATIONAL"]["program_network"], "VISA INTERNATIONAL")
        self.assertFalse(rows["TOTAL PURCHASE"]["transaction_type"])
        self.assertFalse(rows["TOTAL CURRENCY CONVERSION FEES"]["transaction_category"])
        self.assertFalse(rows["TOTAL ISSUER CHARGES"]["charge_category"])

        source_210 = "\n".join(
            [
                "REPORT ID:  VSS-210                                         VISANET SETTLEMENT SERVICE                        PAGE:              1",
                " REPORTING FOR:      1000000001 TEST ENTITY               INTERNATIONAL SETTLEMENT SERVICE                     PROC DATE:   01MAR18",
                " ROLLUP TO:          1000000001 TEST ENTITY              CURRENCY CONVERSION FEES REPORT                     REPORT DATE: 01MAR18",
                " FUNDS XFER ENTITY:  1000000001 TEST ENTITY",
                " SETTLEMENT CURRENCY:  USD",
                " CLEARING CURRENCY:    BDT",
                " ISSUER TRANSACTIONS",
                " PURCHASE",
                "  ORIGINAL SALE",
                self._row_210("   VISA INTERNATIONAL", "100.00DB", "2.00", "80.00DB", "1.00", "0.50DB"),
                " TOTAL PURCHASE",
                self._row_210("", "100.00DB", "2.00", "80.00DB", "1.00", "0.50DB"),
                " TOTAL CURRENCY CONVERSION FEES",
                self._row_210("", "100.00DB", "2.00", "80.00DB", "1.00", "0.50DB"),
                " *** END OF VSS-210 REPORT ***",
            ]
        )
        reports, issues = VSSParser().parse(source_210)
        self.assertFalse(issues)
        rows = {row["description"]: row for row in reports[0].lines}
        self.assertEqual(rows["TOTAL PURCHASE"]["transaction_category"], "PURCHASE")
        self.assertFalse(rows["TOTAL PURCHASE"]["transaction_type"])
        self.assertFalse(rows["TOTAL CURRENCY CONVERSION FEES"]["transaction_category"])
        self.assertFalse(rows["TOTAL CURRENCY CONVERSION FEES"]["transaction_type"])

    def test_vss_110_data_and_no_data(self):
        source = """REPORT ID:  VSS-110                                         VISANET SETTLEMENT SERVICE                        PAGE:              1
 REPORTING FOR:      1000000001 TEST ENTITY                INTERNATIONAL SETTLEMENT SERVICE                     PROC DATE:   01MAR18
 ROLLUP TO:          1000000001 TEST ENTITY                   SETTLEMENT SUMMARY REPORT                         REPORT DATE: 01MAR18
 FUNDS XFER ENTITY:  1000000001 TEST ENTITY
 SETTLEMENT CURRENCY:  USD
 INTERCHANGE VALUE
    TOTAL ACQUIRER                                1                    100.00                      0.00                    100.00CR
    TOTAL ISSUER                                  0                      0.00                      0.00                      0.00
    TOTAL OTHER                                   0                      0.00                      0.00                      0.00
    TOTAL INTERCHANGE VALUE                       1                    100.00                      0.00                    100.00CR
 REIMBURSEMENT FEES
    TOTAL ACQUIRER                                                       0.00                      1.00                      1.00DB
    TOTAL ISSUER                                                         0.00                      0.00                      0.00
    TOTAL OTHER                                                          0.00                      0.00                      0.00
    TOTAL REIMBURSEMENT FEES                                             0.00                      1.00                      1.00DB
 VISA CHARGES
    TOTAL ACQUIRER                                                       0.00                      0.00                      0.00
    TOTAL ISSUER                                                         0.00                      0.00                      0.00
    TOTAL OTHER                                                          0.00                      0.00                      0.00
    TOTAL VISA CHARGES                                                   0.00                      0.00                      0.00
 TOTAL
    TOTAL ACQUIRER                                                     100.00                      1.00                     99.00CR
    TOTAL ISSUER                                                         0.00                      0.00                      0.00
    TOTAL OTHER                                                          0.00                      0.00                      0.00
    NET SETTLEMENT AMOUNT                                              100.00                      1.00                     99.00CR
 *** END OF VSS-110 REPORT ***
REPORT ID:  VSS-110                                         VISANET SETTLEMENT SERVICE                        PAGE:              1
 REPORTING FOR:      1000000002 NO DATA                    INTERNATIONAL SETTLEMENT SERVICE                     PROC DATE:   01MAR18
 ROLLUP TO:          1000000001 TEST ENTITY                   SETTLEMENT SUMMARY REPORT                         REPORT DATE: 01MAR18
 FUNDS XFER ENTITY:  1000000001 TEST ENTITY
 SETTLEMENT CURRENCY:  USD
 *** NO DATA FOR THIS REPORT ***
 *** END OF VSS-110 REPORT ***"""
        reports, issues = VSSParser().parse(source)
        self.assertFalse(issues)
        self.assertEqual(len(reports), 2)
        self.assertEqual(reports[0].header["data_status"], "data")
        self.assertEqual(len(reports[0].lines), 16)
        net = reports[0].lines[-1]
        self.assertEqual(net["record_type"], "net")
        self.assertEqual(net["total_amount"], Decimal("99.00"))
        self.assertEqual(net["direction"], "CR")
        self.assertEqual(reports[1].header["data_status"], "no_data")
        self.assertEqual(reports[1].lines, [])


if __name__ == "__main__":
    unittest.main()
