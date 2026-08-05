"""Tests for PlotlyFigureBlock rendering and HTML cache behaviour."""

from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase

from cms.blocks.plotly_figure import PlotlyFigureBlock


class TestPlotlyFigureBlockCache(SimpleTestCase):
    """Tests that cached Plotly HTML respects StreamField height changes."""

    def setUp(self) -> None:
        """Clear cache and prepare a minimal figure payload."""
        cache.clear()
        self.block = PlotlyFigureBlock()
        self.figure_json = {"data": [{"type": "scatter", "x": [1], "y": [2]}], "layout": {}}
        self.page = MagicMock()
        self.page.slug = "variants-region-uppsala"

    def tearDown(self) -> None:
        """Clear cache after each test."""
        cache.clear()

    @patch("cms.blocks.plotly_figure.plot_html_from_json")
    def test_cache_key_includes_height(self, mock_plot_html: MagicMock) -> None:
        """Regenerate Plotly HTML when only the block height changes."""
        mock_plot_html.side_effect = [
            '<div class="plotly-graph-div" style="height:500px;"></div>',
            '<div class="plotly-graph-div" style="height:800px;"></div>',
        ]

        first = self.block.get_context(
            {
                "figure_id": "lineage_six_recent",
                "alt_text": "chart",
                "height": 500,
            },
            {
                "page": self.page,
                "figures": {"lineage_six_recent": self.figure_json},
                "source_file_hash": "abc123",
            },
        )
        first_html = first["plot_html"]

        second = self.block.get_context(
            {
                "figure_id": "lineage_six_recent",
                "alt_text": "chart",
                "height": 800,
            },
            {
                "page": self.page,
                "figures": {"lineage_six_recent": self.figure_json},
                "source_file_hash": "abc123",
            },
        )

        self.assertEqual(mock_plot_html.call_count, 2)
        self.assertEqual(mock_plot_html.call_args_list[0].kwargs["height"], "500px")
        self.assertEqual(mock_plot_html.call_args_list[1].kwargs["height"], "800px")
        self.assertIn("500px", first_html)
        self.assertIn("800px", second["plot_html"])

    @patch("cms.blocks.plotly_figure.plot_html_from_json")
    def test_same_height_reuses_cache(self, mock_plot_html: MagicMock) -> None:
        """Reuse cached HTML when slug, figure, file hash, and height match."""
        mock_plot_html.return_value = '<div style="height:800px;"></div>'
        parent_context = {
            "page": self.page,
            "figures": {"lineage_six_recent": self.figure_json},
            "source_file_hash": "abc123",
        }
        value = {
            "figure_id": "lineage_six_recent",
            "alt_text": "chart",
            "height": 800,
        }

        self.block.get_context(value, parent_context)
        self.block.get_context(value, parent_context)

        self.assertEqual(mock_plot_html.call_count, 1)
