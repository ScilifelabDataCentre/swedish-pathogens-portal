"""Unit tests for liver DashboardData figure read helpers."""

from unittest.mock import patch

from django.test import SimpleTestCase

from dashboard_visualisation.liver_resource.analysis import analyse_de_uploads
from dashboard_visualisation.liver_resource.computation import parse_de_file
from dashboard_visualisation.liver_resource.dashboard_figures import (
    get_stored_example,
    resolve_base_tln_figure,
    stored_example_entry_from_analysis,
)
from dashboard_visualisation.liver_resource.examples import EXAMPLE_SLUG
from dashboard_visualisation.liver_resource.reference_data import get_data_root
from dashboard_visualisation.liver_resource.thresholds import (
    DEFAULT_ADJ_P,
    DEFAULT_LOGFC_FOLD,
    DEFAULT_THRESHOLD_KEY,
)

_FIXTURE_FILENAME = "HCC-Control.txt"


class TestLiverDashboardFigures(SimpleTestCase):
    """Verify stored figure accessors and fallbacks."""

    def test_resolve_base_tln_figure_uses_stored_json(self) -> None:
        """Test stored base_tln is returned when present."""
        stored = {"data": [{"type": "scatter"}], "layout": {"title": {"text": "stored"}}}
        with patch(
            "dashboard_visualisation.liver_resource.dashboard_figures.build_base_figure_json"
        ) as mock_build:
            figure = resolve_base_tln_figure({"base_tln": stored})
            mock_build.assert_not_called()
        self.assertEqual(figure, stored)

    def test_resolve_base_tln_figure_falls_back_when_missing(self) -> None:
        """Test live base figure is built when DashboardData has no base_tln."""
        fallback = {"data": [{"type": "scatter"}], "layout": {"title": {"text": "live"}}}
        with patch(
            "dashboard_visualisation.liver_resource.dashboard_figures.build_base_figure_json",
            return_value=fallback,
        ):
            figure = resolve_base_tln_figure({})
        self.assertEqual(figure, fallback)

    def test_get_stored_example_reads_analysis_entry(self) -> None:
        """Test round-trip from analysis to stored JSON and back."""
        example_path = get_data_root() / "examples" / _FIXTURE_FILENAME
        de_data = parse_de_file(example_path)
        analysis = analyse_de_uploads(
            [(_FIXTURE_FILENAME, de_data)],
            adj_p=DEFAULT_ADJ_P,
            logfc_fold=DEFAULT_LOGFC_FOLD,
        )
        payload = {
            "examples": {
                EXAMPLE_SLUG: {
                    DEFAULT_THRESHOLD_KEY: stored_example_entry_from_analysis(analysis),
                }
            }
        }

        stored = get_stored_example(
            payload,
            slug=EXAMPLE_SLUG,
            cutoff=DEFAULT_THRESHOLD_KEY,
            adj_p=DEFAULT_ADJ_P,
            logfc_fold=DEFAULT_LOGFC_FOLD,
        )
        self.assertIsNotNone(stored)
        if stored is None:
            self.fail("Expected stored example figure")
        self.assertEqual(stored.plot_mode, "solid")
        self.assertEqual(stored.comparisons[0].filename, _FIXTURE_FILENAME)
        self.assertIn("data", stored.figure_json)

    def test_get_stored_example_ignores_legacy_standard_key(self) -> None:
        """Test figures keyed only as ``standard`` are not used for default thresholds."""
        payload = {
            "examples": {
                EXAMPLE_SLUG: {
                    "standard": {
                        "figure": {"data": [], "layout": {}},
                        "plot_mode": "solid",
                        "leaf_trace_index": 2,
                        "stats": {
                            "filename": "legacy.txt",
                            "gene_count": 1,
                            "n_up": 0,
                            "n_down": 0,
                        },
                    }
                }
            }
        }
        stored = get_stored_example(
            payload,
            slug=EXAMPLE_SLUG,
            cutoff=DEFAULT_THRESHOLD_KEY,
            adj_p=DEFAULT_ADJ_P,
            logfc_fold=DEFAULT_LOGFC_FOLD,
        )
        self.assertIsNone(stored)
