"""Tests for liver DashboardData upload and figure generation."""

from datetime import date

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from cms.snippets.dashboard_data import DashboardData
from dashboard_visualisation import generate_figures
from dashboard_visualisation.liver_resource.examples import EXAMPLE_SLUG
from dashboard_visualisation.liver_resource.reference_data import get_data_root
from dashboard_visualisation.liver_resource.session import DEFAULT_CUTOFF


class TestLiverDashboardDataSnippet(TestCase):
    """Verify liver DE upload auto-generates DashboardData figures."""

    def test_liver_upload_generates_base_and_example_figures(self) -> None:
        """Test saving a liver DashboardData row fills base_tln and example keys."""
        example_path = get_data_root() / "examples" / "HCC-Control.txt"
        upload = SimpleUploadedFile(
            name="HCC-Control.txt",
            content=example_path.read_bytes(),
            content_type="text/plain",
        )
        row = DashboardData.objects.create(
            dashboard_title="DINA Liver Resource",
            dashboard_slug="liver-resource",
            source_file=upload,
            data_updated_at=date(2026, 4, 20),
        )
        row.refresh_from_db()

        self.assertIn("base_tln", row.data)
        self.assertIn("data", row.data["base_tln"])
        self.assertIn("examples", row.data)
        self.assertIn(EXAMPLE_SLUG, row.data["examples"])
        self.assertIn(DEFAULT_CUTOFF, row.data["examples"][EXAMPLE_SLUG])

    def test_generate_figures_registry_entry(self) -> None:
        """Test registry dispatch builds expected figure keys from a DE upload."""
        example_path = get_data_root() / "examples" / "HCC-Control.txt"
        figures = generate_figures("liver-resource", example_path)

        self.assertIn("base_tln", figures)
        self.assertIn("examples", figures)
        stats = figures["examples"][EXAMPLE_SLUG][DEFAULT_CUTOFF]["stats"]
        self.assertEqual(stats["filename"], "HCC-Control.txt")
        self.assertGreater(stats["gene_count"], 10_000)
