"""Tests for liver resource CSV exports."""

import csv
import io
from pathlib import Path

from django.test import SimpleTestCase

from dashboard_visualisation.liver_resource.computation import parse_de_file
from dashboard_visualisation.liver_resource.exports import build_genes_csv, build_module_scores_csv
from dashboard_visualisation.liver_resource.reference_data import clear_reference_data_cache, get_data_root

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "liver" / "expected"


class TestLiverExports(SimpleTestCase):
    """Verify exported CSV content matches R reference output."""

    def tearDown(self) -> None:
        """Clear cached reference data between tests."""
        clear_reference_data_cache()

    def _load_reference_rows(self, filename: str) -> list[dict[str, str]]:
        path = FIXTURES_DIR / filename
        with path.open(encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))

    def _parse_csv(self, content: str) -> list[dict[str, str]]:
        return list(csv.DictReader(io.StringIO(content)))

    def test_module_scores_match_r_reference(self) -> None:
        """Test module scores CSV matches R output for HCC-Control."""
        example_path = get_data_root() / "examples" / "HCC-Control.txt"
        de_data = parse_de_file(example_path)
        generated = self._parse_csv(build_module_scores_csv(de_data, "standard"))
        reference = self._load_reference_rows("HCC-Control_module_scores.csv")

        self.assertEqual(len(generated), 105)
        self.assertEqual(len(reference), 105)

        for generated_row, reference_row in zip(generated, reference, strict=True):
            self.assertEqual(generated_row["Module"], reference_row["Module"])
            self.assertEqual(generated_row["GeneCount"], reference_row["GeneCount"])
            self.assertAlmostEqual(
                float(generated_row["DERatio"]),
                float(reference_row["DERatio"]),
                places=6,
            )
            self.assertEqual(generated_row["DEcutoff"], reference_row["DEcutoff"])

    def test_genes_csv_has_expected_shape(self) -> None:
        """Test gene export includes all genes and expected columns."""
        example_path = get_data_root() / "examples" / "HCC-Control.txt"
        de_data = parse_de_file(example_path)
        rows = self._parse_csv(build_genes_csv(de_data, "standard"))

        self.assertEqual(len(rows), len(de_data["genes"]))
        self.assertEqual(
            set(rows[0].keys()),
            {"EnsemblID", "Symbol", "Module", "logFC", "adj.P.Val", "Direction"},
        )
        directions = {row["Direction"] for row in rows}
        self.assertTrue({"up", "down", "ns"}.issuperset(directions))
