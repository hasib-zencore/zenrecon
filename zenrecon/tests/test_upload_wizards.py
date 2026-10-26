# -*- coding: utf-8 -*-
import base64

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestCommunityUploadWizards(TransactionCase):
    def test_vss_direct_upload_creates_linked_attachment(self):
        source = """REPORT ID:  VSS-110                                         VISANET SETTLEMENT SERVICE                        PAGE:              1
 REPORTING FOR:      1000000001 TEST ENTITY                INTERNATIONAL SETTLEMENT SERVICE                     PROC DATE:   01MAR18
 ROLLUP TO:          1000000001 TEST ENTITY                   SETTLEMENT SUMMARY REPORT                         REPORT DATE: 01MAR18
 FUNDS XFER ENTITY:  1000000001 TEST ENTITY
 SETTLEMENT CURRENCY:  USD
 *** NO DATA FOR THIS REPORT ***
 *** END OF VSS-110 REPORT ***"""
        wizard = self.env["bsr.vss.import.document.wizard"].create({
            "filename": "daily-vss.txt",
            "file": base64.b64encode(source.encode()),
        })

        action = wizard.action_import_and_process()
        batch = self.env["bsr.vss.import"].browse(action["res_id"])

        self.assertEqual(batch.state, "completed")
        self.assertEqual(batch.file_name, "daily-vss.txt")
        self.assertTrue(batch.attachment_id)
        self.assertEqual(batch.attachment_id.res_model, batch._name)
        self.assertEqual(batch.attachment_id.res_id, batch.id)

