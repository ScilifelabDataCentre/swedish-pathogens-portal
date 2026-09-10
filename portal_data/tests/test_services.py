"""Tests for portal data service helpers."""

from __future__ import annotations

import tempfile
from pathlib import Path

from django.test import TestCase, override_settings

from portal_data.services import load_all_items, parse_investigation_file


class ParseInvestigationFileTests(TestCase):
    """Tests for parsing ISA investigation files into study metadata."""

    def setUp(self) -> None:
        """Create a temporary directory for each test."""
        self.tmpdir_context = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmpdir_context.name)

    def tearDown(self) -> None:
        """Remove the temporary directory."""
        self.tmpdir_context.cleanup()

    def test_parse_investigation_file_extracts_study_metadata(self) -> None:
        """Parse study metadata fields from an ISA investigation file."""
        investigation = self.tmp_path / "i_Investigation.txt"
        investigation.write_text(
            "\n".join(
                [
                    "Study Title\tExample metabolomics study",
                    "Study Description\tA useful description.",
                    "Study Public Release Date\t2024-01-15",
                    "Study Factor Name\tTreatment\tTimepoint",
                    "Study Design Type\tcase control design",
                    "Study Assay Technology Platform\tLC-MS",
                    "Study Assay Technology Type\tmass spectrometry",
                ]
            ),
            encoding="utf-8",
        )

        meta = parse_investigation_file(investigation)

        self.assertEqual(meta["study_title"], "Example metabolomics study")
        self.assertEqual(meta["study_description"], "A useful description.")
        self.assertEqual(meta["study_public_release_date"], "2024-01-15")
        self.assertEqual(meta["factors"], ["Treatment", "Timepoint"])
        self.assertEqual(meta["design_types"], ["case control design"])
        self.assertEqual(meta["platforms"], ["LC-MS"])
        self.assertEqual(meta["technology"], "mass spectrometry")


class LoadAllItemsTests(TestCase):
    """Tests for loading MetaboLights study directories from the dataset root."""

    def setUp(self) -> None:
        """Create a temporary dataset root for each test."""
        self.tmpdir_context = tempfile.TemporaryDirectory()
        self.datasets_root = Path(self.tmpdir_context.name)

    def tearDown(self) -> None:
        """Remove the temporary dataset root."""
        self.tmpdir_context.cleanup()

    def test_load_all_items_reads_valid_metabolights_dirs(self) -> None:
        """Load only valid MetaboLights study directories from the dataset root."""
        study = self.datasets_root / "MTBLS9999"
        study.mkdir()
        (study / "i_Investigation.txt").write_text(
            "Study Title\tExample study\nStudy Public Release Date\t2024-01-15\n",
            encoding="utf-8",
        )

        ignored = self.datasets_root / "not-a-study"
        ignored.mkdir()

        with override_settings(DATASETS_ROOT=self.datasets_root):
            items = load_all_items("metabolomics")

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["accession"], "MTBLS9999")
        self.assertEqual(items[0]["title"], "Example study")
        self.assertEqual(items[0]["year"], "2024")
