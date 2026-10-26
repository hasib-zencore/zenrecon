from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ..services.npsb_ocl_parser import parse_oic_xml


@tagged("post_install", "-at_install")
class TestNpsbOcl(TransactionCase):
    def test_ocl_parser_and_scheme_tables_are_isolated(self):
        raw = b"""<?xml version="1.0" encoding="UTF-8"?>
        <DocFile>
          <FileHeader>
            <FileLabel>OCL</FileLabel><FormatVersion>1</FormatVersion>
            <Sender>NPSB</Sender><Receiver>BANK</Receiver>
            <CreationDate>2026-10-17</CreationDate><CreationTime>09:00:00</CreationTime>
            <FileSeqNumber>1</FileSeqNumber>
          </FileHeader>
          <DocList><Doc>
            <TransType><TransCode><MsgCode>0200</MsgCode></TransCode></TransType>
            <DocRefSet><Parm><ParmCode>DRN</ParmCode><Value>DRN-1</Value></Parm></DocRefSet>
            <LocalDt>2026-10-17 09:00:00</LocalDt>
            <Transaction><Currency>050</Currency><Amount>125.50</Amount></Transaction>
          </Doc></DocList>
        </DocFile>"""
        header, values = parse_oic_xml(raw, source_file_name="sample.xml")
        self.assertEqual(header["file_label"], "OCL")
        self.assertEqual(values[0]["drn"], "DRN-1")
        self.assertEqual(values[0]["transaction_amount"], 125.5)

        batch = self.env["npsb.ocl.import"].create(
            {"name": "sample.xml", "company_id": self.env.company.id}
        )
        values[0].update({"batch_id": batch.id, "company_id": self.env.company.id})
        transaction = self.env["npsb.ocl.transaction"].create(values[0])
        self.assertEqual(transaction.batch_id, batch)
        self.assertEqual(batch.record_count, 1)

        tables = {
            self.env["visa.import.batch"]._table,
            self.env["bsr.ipm.import"]._table,
            self.env["npsb.ocl.import"]._table,
            self.env["npsb.settlement.report"]._table,
        }
        self.assertEqual(len(tables), 4)
