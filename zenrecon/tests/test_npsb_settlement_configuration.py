# -*- coding: utf-8 -*-
import base64

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestNpsbSettlementConfiguration(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.report = cls.env["npsb.settlement.report"].create({
            "pdf_file": base64.b64encode(b"test"),
            "filename": "settlement.pdf",
            "state": "processed",
            "transaction_date": "2026-09-15",
            "settlement_date": "2026-09-16",
        })
        cls.env["npsb.settlement.summary.line"].create([
            {
                "report_id": cls.report.id,
                "sequence": 1,
                "issuer_acquirer": "Issuing",
                "delivery_channel": "ATM",
                "trans_type": "CW",
                "trans_amount": 1000.0,
                "fees_irf_amount": 20.0,
                "platform_fee": 5.0,
                "net_amount": 975.0,
            },
            {
                "report_id": cls.report.id,
                "sequence": 2,
                "issuer_acquirer": "Acquiring/Beneficiary",
                "delivery_channel": "ATM",
                "trans_type": "CW",
                "trans_amount": 600.0,
                "fees_irf_amount": 10.0,
                "platform_fee": 3.0,
                "net_amount": 587.0,
            },
            {
                "report_id": cls.report.id,
                "sequence": 3,
                "issuer_acquirer": False,
                "delivery_channel": "Other",
                "trans_type": "Adjustment",
                "trans_amount": 50.0,
            },
        ])

    def test_dynamic_filters_matching_and_gl_validation(self):
        configuration = self.env["npsb.settlement.configuration"].create({
            "source_report_id": self.report.id,
            "amount_trans_amount": True,
            "amount_fees_irf": False,
            "amount_platform_fee": False,
            "amount_net_amount": False,
        })
        options = self.env["npsb.settlement.filter.option"].search([
            ("report_id", "=", self.report.id),
        ])
        self.assertIn("Issuing", options.filtered(
            lambda option: option.field_name == "business_mode"
        ).mapped("name"))
        self.assertTrue(options.filtered(
            lambda option: option.field_name == "business_mode" and option.is_blank
        ))
        self.assertIn("Other", options.filtered(
            lambda option: option.field_name == "delivery_channel"
        ).mapped("name"))

        issuing = options.filtered(
            lambda option: option.field_name == "business_mode" and option.value == "Issuing"
        )
        configuration.business_mode_option_ids = issuing
        configuration.action_match_source()
        self.assertEqual(configuration.state, "matched")
        self.assertEqual(len(configuration.line_ids), 1)
        self.assertEqual(configuration.line_ids.matched_amount, 1000.0)

        with self.assertRaises(UserError):
            configuration.action_validate()
        configuration.line_ids.write({
            "posting_indicator": "DR",
            "gl_number": "100001",
            "gl_name": "NPSB Settlement",
            "debit_remarks": "NPSB debit",
            "credit_remarks": "NPSB credit",
        })
        configuration.action_validate()
        self.assertEqual(configuration.state, "ready")
