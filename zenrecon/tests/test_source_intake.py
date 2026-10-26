# -*- coding: utf-8 -*-
import shutil
import tempfile
from pathlib import Path

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestSourceIntake(TransactionCase):
    def setUp(self):
        super().setUp()
        self.root = Path(tempfile.mkdtemp(prefix="zenrecon-intake-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.workspace = self.env["zenrecon.source.workspace"]._workspace_for_company()
        self.workspace.write({"root_path": "/unused/legacy/root"})
        for folder in self.workspace.folder_ids:
            folder.source_path = str(self.root / folder.relative_path)

    def test_default_streams_and_missing_status(self):
        self.assertEqual(len(self.workspace.folder_ids), 12)
        folder = self.workspace.folder_ids.filtered(lambda item: item.parser_type == "visa_vss")
        self.assertFalse(folder._scan("2026-10-26"))
        self.assertEqual(folder.last_status, "missing")

    def test_scan_deduplicates_same_file_content(self):
        folder = self.workspace.folder_ids.filtered(lambda item: item.parser_type == "visa_vss")
        source_dir = Path(folder.source_path)
        source_dir.mkdir(parents=True)
        (source_dir / "VSS_20261026.txt").write_text("same source identity", encoding="utf-8")

        first = folder._scan("2026-10-26")
        second = folder._scan("2026-10-26")

        self.assertEqual(first, second)
        self.assertEqual(len(folder.file_ids), 1)
        self.assertEqual(first.state, "ready")
        self.assertEqual(first.relative_file_path, "IN/Issuing/VISA/VSS/VSS_20261026.txt")

    def test_completed_file_is_not_processed_twice(self):
        folder = self.workspace.folder_ids.filtered(lambda item: item.parser_type == "visa_vss")
        source_dir = Path(folder.source_path)
        source_dir.mkdir(parents=True)
        (source_dir / "VSS_20261026.txt").write_text("already processed", encoding="utf-8")
        source_file = folder._scan("2026-10-26")
        source_file.write({"state": "processed"})

        wizard = self.env["zenrecon.source.export.wizard"].create({
            "workspace_id": self.workspace.id,
            "scope": "selected",
            "folder_ids": [(6, 0, folder.ids)],
            "business_date": "2026-10-26",
        })
        action = wizard.action_export_and_process()

        self.assertEqual(source_file.state, "processed")
        self.assertEqual(action["res_model"], "zenrecon.source.file")

    def test_folder_cannot_escape_workspace(self):
        with self.assertRaises(ValidationError):
            self.env["zenrecon.source.folder"].create({
                "workspace_id": self.workspace.id,
                "name": "Unsafe",
                "code": "UNSAFE",
                "domain_name": "Test",
                "stream_name": "Test",
                "parser_type": "visa_vss",
                "relative_path": "../outside",
                "file_pattern": "*",
            })

    def test_each_stream_uses_its_own_physical_path(self):
        folder = self.workspace.folder_ids.filtered(lambda item: item.parser_type == "cbs")
        independent_path = self.root / "completely-different" / "cbs-daily"
        independent_path.mkdir(parents=True)
        (independent_path / "CBS_20261026.csv").write_text("account,amount\n1,10", encoding="utf-8")
        folder.source_path = str(independent_path)

        files = folder._scan("2026-10-26")

        self.assertEqual(len(files), 1)
        self.assertEqual(files.source_directory, str(independent_path))
        self.assertEqual(files.relative_file_path, "IN/Reconciliation/CBS/CBS_20261026.csv")

    def test_physical_path_must_be_absolute(self):
        folder = self.workspace.folder_ids.filtered(lambda item: item.parser_type == "cms")
        with self.assertRaises(ValidationError):
            folder.source_path = "relative/cms"
