"""Tests for variants_region_uppsala visualisation module."""

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import plotly.graph_objects as go
import polars as pl
from django.test import SimpleTestCase

from dashboard_visualisation.registry import (
    generate_figures as registry_generate_figures,
)
from dashboard_visualisation.registry import (
    validate_source_columns as registry_validate_source_columns,
)
from dashboard_visualisation.variants_region_uppsala import (
    _add_week_start_dates,
    _lineage_four_recent_fig,
    _lineage_six_recent_fig,
    _lineage_wholetime_fig,
    generate_figures,
    validate_source_columns,
)

FIXTURE_CSV = (
    Path(__file__).resolve().parent / "fixtures" / "variants_region_uppsala" / "sample_cleaned.csv"
)


def _sample_df() -> pl.DataFrame:
    """Load the cleaned CSV fixture."""
    return pl.read_csv(FIXTURE_CSV)


class TestsValidateSourceColumns(SimpleTestCase):
    """Tests for validate_source_columns."""

    def test_valid_columns(self):
        """Accept the cleaned CSV header columns."""
        columns = [
            "lineage_groups01",
            "lineage_groups02",
            "lineage_groups03",
            "lineage_groups04",
            "lineage_groups05",
            "lineage_groups06",
            "Year-Week",
            "percentage_lineage6",
            "percentage_lineage4",
            "percentage_lineage1",
        ]
        self.assertIsNone(validate_source_columns(columns))

    def test_missing_column(self):
        """Report a single missing required column."""
        result = validate_source_columns(
            [
                "Year-Week",
                "lineage_groups01",
                "lineage_groups04",
                "lineage_groups06",
                "percentage_lineage1",
                "percentage_lineage4",
            ]
        )
        self.assertEqual(result, "Missing columns: percentage_lineage6")

    def test_multiple_missing_columns(self):
        """Report all missing required columns."""
        result = validate_source_columns(["Year-Week"])
        self.assertIsNotNone(result)
        self.assertIn("lineage_groups01", result)
        self.assertIn("percentage_lineage6", result)


class TestsAddWeekStartDates(SimpleTestCase):
    """Tests for Year-Week → Monday date conversion."""

    def test_iso_week_monday(self):
        """Map ISO year-week to the Monday of that week."""
        df = pl.DataFrame({"Year-Week": ["2024-01", "2024-33"]})
        result = _add_week_start_dates(df)
        self.assertEqual(result.get_column("date").to_list(), [date(2024, 1, 1), date(2024, 8, 12)])


class TestsLineageSixRecentFigure(SimpleTestCase):
    """Tests for the granular recent (groups06) figure."""

    def setUp(self):
        """Load fixture data."""
        self.df = _sample_df()

    def test_returns_figure(self):
        """Return a Plotly figure."""
        fig = _lineage_six_recent_fig(self.df)
        self.assertIsInstance(fig, go.Figure)
        self.assertGreaterEqual(len(fig.data), 1)

    def test_filters_before_october_2023(self):
        """Exclude weeks on or before 2023-10-01."""
        fig = _lineage_six_recent_fig(self.df)
        for trace in fig.data:
            for value in trace.x:
                self.assertGreater(value, date(2023, 10, 1))

    def test_has_select_and_window_menus(self):
        """Expose select/deselect and date-window button menus."""
        fig = _lineage_six_recent_fig(self.df)
        self.assertEqual(len(fig.layout.updatemenus), 2)
        labels = [button.label for menu in fig.layout.updatemenus for button in menu.buttons]
        self.assertIn("Select all lineages", labels)
        self.assertIn("Deselect all lineages", labels)
        self.assertIn("Data since Oct 2023", labels)
        self.assertIn("Last 16 weeks", labels)

    def test_layout_basics(self):
        """Match legacy axis titles and hover mode."""
        fig = _lineage_six_recent_fig(self.df)
        self.assertEqual(fig.layout.hovermode, "x unified")
        self.assertEqual(fig.layout.xaxis.title.text, "<b>Date</b>")
        self.assertEqual(fig.layout.yaxis.title.text, "<b>Percentage of Lineages<br></b>")


class TestsLineageFourRecentFigure(SimpleTestCase):
    """Tests for the mid-granularity (groups04) figure."""

    def setUp(self):
        """Load fixture data."""
        self.df = _sample_df()

    def test_returns_figure(self):
        """Return a Plotly figure."""
        fig = _lineage_four_recent_fig(self.df)
        self.assertIsInstance(fig, go.Figure)
        self.assertGreaterEqual(len(fig.data), 1)

    def test_filters_before_january_2023(self):
        """Exclude weeks on or before 2023-01-01."""
        fig = _lineage_four_recent_fig(self.df)
        for trace in fig.data:
            for value in trace.x:
                self.assertGreater(value, date(2023, 1, 1))

    def test_window_menu_label(self):
        """Use the January 2023 full-window button label."""
        fig = _lineage_four_recent_fig(self.df)
        labels = [button.label for menu in fig.layout.updatemenus for button in menu.buttons]
        self.assertIn("Data since Jan 2023", labels)
        self.assertEqual(len(fig.layout.updatemenus), 2)


class TestsLineageWholetimeFigure(SimpleTestCase):
    """Tests for the full-timeline (groups01) figure."""

    def setUp(self):
        """Load fixture data."""
        self.df = _sample_df()

    def test_returns_figure(self):
        """Return a Plotly figure."""
        fig = _lineage_wholetime_fig(self.df)
        self.assertIsInstance(fig, go.Figure)
        self.assertGreaterEqual(len(fig.data), 1)

    def test_only_select_deselect_menu(self):
        """Full timeline has select/deselect only (no 16-week window)."""
        fig = _lineage_wholetime_fig(self.df)
        self.assertEqual(len(fig.layout.updatemenus), 1)
        labels = [button.label for button in fig.layout.updatemenus[0].buttons]
        self.assertEqual(labels, ["Select all lineages", "Deselect all lineages"])

    def test_includes_pre_2023_dates(self):
        """Keep weeks from before the recent-window cutoffs."""
        fig = _lineage_wholetime_fig(self.df)
        all_dates: list[date] = []
        for trace in fig.data:
            all_dates.extend(trace.x)
        self.assertTrue(any(value <= date(2023, 1, 1) for value in all_dates))


class TestsGenerateFigures(SimpleTestCase):
    """Tests for generate_figures."""

    def test_generate_figures_from_fixture(self):
        """Produce all three figure_id keys from the cleaned fixture."""
        result = generate_figures(FIXTURE_CSV)
        self.assertEqual(
            set(result.keys()),
            {"lineage_six_recent", "lineage_four_recent", "lineage_wholetime"},
        )
        for figure_json in result.values():
            self.assertIn("data", figure_json)
            self.assertIn("layout", figure_json)
            self.assertGreaterEqual(len(figure_json["data"]), 1)

    @patch("dashboard_visualisation.variants_region_uppsala.figure_to_json")
    @patch("dashboard_visualisation.variants_region_uppsala.read_csv_dataframe")
    def test_generate_figures_dispatch(
        self, mock_read_csv_dataframe: MagicMock, mock_figure_to_json: MagicMock
    ):
        """Convert each builder output through figure_to_json."""
        mock_read_csv_dataframe.return_value = _sample_df()
        mock_figure_to_json.side_effect = [{"six": 1}, {"four": 2}, {"one": 3}]

        result = generate_figures(source_file="dummy")

        self.assertEqual(
            result,
            {
                "lineage_six_recent": {"six": 1},
                "lineage_four_recent": {"four": 2},
                "lineage_wholetime": {"one": 3},
            },
        )
        mock_read_csv_dataframe.assert_called_once()
        self.assertEqual(mock_figure_to_json.call_count, 3)


class TestsRegistryIntegration(SimpleTestCase):
    """Tests for registry dispatch to the Uppsala variants module."""

    def test_registry_validate_source_columns_ok(self):
        """Accept cleaned CSV columns via registry for the dashboard slug."""
        columns = list(_sample_df().columns)
        self.assertIsNone(registry_validate_source_columns("variants-region-uppsala", columns))

    def test_registry_validate_source_columns_missing(self):
        """Reject incomplete headers via registry for the dashboard slug."""
        result = registry_validate_source_columns(
            "variants-region-uppsala",
            ["Year-Week", "lineage_groups01"],
        )
        self.assertIsNotNone(result)
        self.assertIn("Missing columns:", result)

    def test_registry_generate_figures(self):
        """Dispatch generate_figures for variants-region-uppsala to three keys."""
        result = registry_generate_figures("variants-region-uppsala", FIXTURE_CSV)
        self.assertEqual(
            set(result.keys()),
            {"lineage_six_recent", "lineage_four_recent", "lineage_wholetime"},
        )
