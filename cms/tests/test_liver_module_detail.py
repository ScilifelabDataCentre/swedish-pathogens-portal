"""Tests for liver resource module detail builder."""

from django.test import SimpleTestCase

from cms.services.liver_resource.computation import parse_de_file
from cms.services.liver_resource.module_detail import build_module_detail
from cms.services.liver_resource.reference_data import clear_reference_data_cache, get_data_root


class TestLiverModuleDetail(SimpleTestCase):
    """Verify module detail tables are built from session DE data."""

    def tearDown(self) -> None:
        """Clear cached reference data between tests."""
        clear_reference_data_cache()

    def test_build_module_detail_for_module_one(self) -> None:
        """Test module detail includes overlapping genes and summary counts."""
        example_path = get_data_root() / "examples" / "HCC-Control.txt"
        de_data = parse_de_file(example_path)
        detail = build_module_detail(de_data, module_id=1, cutoff="standard")
        if detail is None:
            self.fail("Expected module detail for module 1")
        self.assertEqual(detail.module_id, 1)
        self.assertGreater(detail.module_gene_count, 0)
        self.assertGreater(detail.overlap_count, 0)
        self.assertGreater(len(detail.genes), 0)

    def test_unknown_module_returns_none(self) -> None:
        """Test invalid module ids return None."""
        example_path = get_data_root() / "examples" / "HCC-Control.txt"
        de_data = parse_de_file(example_path)
        self.assertIsNone(build_module_detail(de_data, module_id=999, cutoff="standard"))
