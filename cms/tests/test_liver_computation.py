"""Tests for liver resource computation parity with R reference output."""

import csv
from io import StringIO
from pathlib import Path

from django.test import SimpleTestCase

from dashboard_visualisation.liver_resource.computation import (
    classify_genes,
    compute_module_ratios,
    get_module_gene_sets,
    map_ratios_to_colours,
    parse_de_file,
)
from dashboard_visualisation.liver_resource.reference_data import (
    clear_reference_data_cache,
    get_data_root,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "liver"
EXPECTED_DIR = FIXTURES_DIR / "expected"
TOLERANCE = 1e-6


class TestLiverComputation(SimpleTestCase):
    """Verify computation output matches R reference CSVs."""

    def tearDown(self) -> None:
        """Clear cached reference data between tests."""
        clear_reference_data_cache()

    def _load_r_reference(self, filename: str) -> dict[int, float]:
        path = EXPECTED_DIR / filename
        scores: dict[int, float] = {}
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                scores[int(row["Module"])] = float(row["DERatio"])
        return scores

    def _compare_ratios(
        self,
        python_ratios: dict[int, float | None],
        r_ratios: dict[int, float],
    ) -> float:
        max_diff = 0.0
        for module_id, r_value in r_ratios.items():
            python_value = python_ratios.get(module_id)
            if python_value is None:
                python_value = 0.0
            max_diff = max(max_diff, abs(python_value - r_value))
            self.assertLessEqual(
                abs(python_value - r_value),
                TOLERANCE,
                msg=f"Module {module_id}: Python={python_value}, R={r_value}",
            )
        return max_diff

    def test_csv_parse_matches_tab_for_hcc_control(self) -> None:
        """Test comma-separated DE files parse the same as tab-separated."""
        example_path = get_data_root() / "examples" / "HCC-Control.txt"
        tab_data = parse_de_file(example_path)

        buffer = StringIO()
        writer = csv.writer(buffer)
        with example_path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    writer.writerow(line.rstrip("\n").split("\t"))
        csv_data = parse_de_file(StringIO(buffer.getvalue()))

        self.assertEqual(tab_data["header"], csv_data["header"])
        self.assertEqual(tab_data["genes"][:20], csv_data["genes"][:20])
        sample_gene = tab_data["genes"][0]
        self.assertEqual(tab_data["data"][sample_gene], csv_data["data"][sample_gene])

    def test_hcc_control_standard_matches_r(self) -> None:
        """Test HCC-Control ratios with standard cutoff match R output."""
        example_path = get_data_root() / "examples" / "HCC-Control.txt"
        de_data = parse_de_file(example_path)
        classified = classify_genes(de_data, "standard")
        modules = get_module_gene_sets()
        ratios = compute_module_ratios(de_data["genes"], classified, modules)
        r_ratios = self._load_r_reference("HCC-Control_module_scores.csv")

        self.assertEqual(len(r_ratios), 105)
        self._compare_ratios(ratios, r_ratios)

    def test_sleep_deprived_top500_matches_r(self) -> None:
        """Test sleep.deprived ratios with top500 cutoff match R output."""
        example_path = get_data_root() / "examples" / "sleep.deprived.AK-control.AK.txt"
        de_data = parse_de_file(example_path)
        classified = classify_genes(de_data, "top500")
        modules = get_module_gene_sets()
        ratios = compute_module_ratios(de_data["genes"], classified, modules)
        r_ratios = self._load_r_reference("sleep.deprived.AK-control.AK_module_scores.csv")

        self.assertEqual(len(r_ratios), 105)
        self._compare_ratios(ratios, r_ratios)

    def test_map_ratios_to_colours_returns_hex_for_all_modules(self) -> None:
        """Test colour mapping returns a hex colour for every module."""
        example_path = get_data_root() / "examples" / "HCC-Control.txt"
        de_data = parse_de_file(example_path)
        classified = classify_genes(de_data, "standard")
        modules = get_module_gene_sets()
        ratios = compute_module_ratios(de_data["genes"], classified, modules)
        colours = map_ratios_to_colours(ratios)

        self.assertEqual(len(colours), 105)
        for colour in colours.values():
            self.assertRegex(colour, r"^#[0-9a-f]{6}$")
