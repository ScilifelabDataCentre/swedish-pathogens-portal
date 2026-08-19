"""Tests for qualitative plot generation."""

import polars as pl
from django.test import SimpleTestCase

from dashboard_visualisation.slu_wastewater.qualitative_plots import (
    get_qual_overview_plot,
    get_qual_plots,
)
from dashboard_visualisation.tests.fixtures.slu_ww_sample_data import get_sample_data


class TestGetQualOverviewPlot(SimpleTestCase):
    """Test qualitative overview plot generation."""

    def test_calculates_category_percentages(self):
        """Test that the function calculates the correct percentages for each category."""
        data = (
            get_sample_data()
            .head(2)
            .with_columns(
                [
                    pl.lit("2024-01-10").alias("sampling_date"),
                    pl.lit("virus_a").alias("target"),
                    pl.Series("category", ["Positive sample", "Negative sample"]),
                ]
            )
        )

        figure = get_qual_overview_plot(data, as_fig=True)

        traces = {trace.name: list(trace.y) for trace in figure.data}

        self.assertAlmostEqual(traces["Positive sample"][0], 50.0)
        self.assertAlmostEqual(traces["Negative sample"][0], 50.0)

    def test_generates_separate_traces_for_multiple_targets(self):
        """Test that the function creates separate traces for each target facet."""
        data = (
            get_sample_data()
            .head(4)
            .with_columns(
                [
                    pl.lit("2024-01-10").alias("sampling_date"),
                    pl.Series("target", ["virus_a", "virus_a", "virus_b", "virus_b"]),
                    pl.Series(
                        "category",
                        [
                            "Positive sample",
                            "Negative sample",
                            "Positive sample",
                            "Negative sample",
                        ],
                    ),
                ]
            )
        )

        figure = get_qual_overview_plot(data, as_fig=True)

        trace_names = [trace.name for trace in figure.data]

        self.assertEqual(trace_names.count("Positive sample"), 2)
        self.assertEqual(trace_names.count("Negative sample"), 2)

    def test_duplicate_rows_are_not_counted(self):
        """Test that the function removes duplicate rows before calculating percentages."""
        data = get_sample_data().head(2)

        data = data.with_columns(
            [
                pl.lit("2024-01-10").alias("sampling_date"),
                pl.lit("virus_a").alias("target"),
                pl.Series("category", ["Positive sample", "Negative sample"]),
            ]
        )

        # Add an exact duplicate of the positive row.
        data = pl.concat([data, data.head(1)])

        figure = get_qual_overview_plot(data, as_fig=True)

        traces = {trace.name: list(trace.y) for trace in figure.data}

        self.assertEqual(traces["Positive sample"], [50.0])
        self.assertEqual(traces["Negative sample"], [50.0])

    def test_returns_html_when_requested(self):
        """Test that the function returns HTML when requested."""
        data = get_sample_data().head(1)

        result = get_qual_overview_plot(data, as_html=True)

        self.assertIsInstance(result, str)
        self.assertIn("<div", result)
        self.assertIn("plotly", result.lower())

    def test_returns_json_by_default(self):
        """Test that the function returns JSON by default."""
        data = get_sample_data().head(1)

        result = get_qual_overview_plot(data)

        self.assertIsInstance(result, str)
        self.assertTrue(result.startswith("{"))


class TestGetQualPlots(SimpleTestCase):
    """Test qualitative heatmap and stacked bar plot generation."""

    def test_returns_figure_for_requested_virus(self):
        """Test that the function returns a figure for the requested virus."""
        data = get_sample_data()

        figure = get_qual_plots(data, "virus_a", as_fig=True)

        heatmaps = [trace for trace in figure.data if trace.type == "heatmap"]
        bars = [trace for trace in figure.data if trace.type == "bar"]

        self.assertEqual(len(heatmaps), 3)

        expected_categories = data.filter(pl.col("target") == "virus_a")["category"].unique().len()

        self.assertEqual(len(bars), expected_categories)
        self.assertTrue(all(trace.type == "heatmap" for trace in heatmaps))
        self.assertTrue(all(trace.type == "bar" for trace in bars))

    def test_creates_heatmap_trace_for_each_category(self):
        """Test that the function creates a heatmap trace for each category."""
        data = get_sample_data()

        figure = get_qual_plots(data, "virus_a", as_fig=True)

        heatmaps = [trace for trace in figure.data if trace.type == "heatmap"]

        self.assertEqual(
            {trace.name for trace in heatmaps},
            {"Invalid sample", "Negative sample", "Positive sample"},
        )

    def test_heatmap_contains_expected_cities_and_dates(self):
        """Test that the heatmap contains the expected cities and sampling dates."""
        data = get_sample_data().filter(pl.col("target") == "virus_a")

        figure = get_qual_plots(data, "virus_a", as_fig=True)

        heatmap = next(trace for trace in figure.data if trace.name == "Positive sample")

        expected_cities = data["city"].unique().sort().to_list()
        expected_dates = data["sampling_date"].unique().sort().to_list()

        self.assertEqual(list(heatmap.y), expected_cities)
        self.assertEqual(list(heatmap.x), expected_dates)

    def test_creates_correct_percentage_bar_values(self):
        """Test that the stacked bars contain correct category percentages."""
        data = get_sample_data().filter(pl.col("target") == "virus_a")

        figure = get_qual_plots(data, "virus_a", as_fig=True)

        bars = {trace.name: list(trace.y) for trace in figure.data if trace.type == "bar"}

        expected = (
            data.group_by(["sampling_date", "category"])
            .agg(pl.len().alias("count"))
            .with_columns(
                (pl.col("count") * 100 / pl.col("count").sum().over("sampling_date")).alias(
                    "percent"
                )
            )
            .sort(["sampling_date", "category"])
        )

        for category in expected["category"].unique():
            actual_values = bars[category]
            expected_values = (
                expected.filter(pl.col("category") == category)
                .sort("sampling_date")["percent"]
                .to_list()
            )

            self.assertEqual(len(actual_values), len(expected_values))

            for actual, expected_value in zip(actual_values, expected_values, strict=True):
                self.assertAlmostEqual(actual, expected_value)

    def test_filters_data_by_virus(self):
        """Test that data for other viruses is excluded from the plot."""
        data = get_sample_data()

        figure = get_qual_plots(data, "virus_b", as_fig=True)

        heatmaps = [trace for trace in figure.data if trace.type == "heatmap"]
        bars = [trace for trace in figure.data if trace.type == "bar"]

        self.assertEqual(len(heatmaps), 3)

        virus_data = data.filter(pl.col("target") == "virus_b")
        expected_categories = set(virus_data["category"].unique())

        self.assertEqual(len(bars), len(expected_categories))
        self.assertEqual({trace.name for trace in bars}, expected_categories)

    def test_accepts_dictionary_input(self):
        """Test that the function accepts dictionary input."""
        data = get_sample_data()

        figure = get_qual_plots(data.to_dict(as_series=False), "virus_a", as_fig=True)

        self.assertTrue(figure.data)

    def test_creates_timeline_controls(self):
        """Test that the function creates timeline controls for available years."""
        data = get_sample_data().filter(pl.col("target") == "virus_a")

        figure = get_qual_plots(data, "virus_a", as_fig=True)

        self.assertEqual(len(figure.layout.updatemenus), 1)

        buttons = figure.layout.updatemenus[0].buttons

        years = data["sampling_date"].str.to_date().dt.year().unique().sort().to_list()

        self.assertEqual(len(buttons), len(years) + 1)
        self.assertEqual(buttons[0].label, "All")

        for button, year in zip(buttons[1:], years, strict=True):
            self.assertEqual(str(button.label), str(year))

    def test_returns_html_when_requested(self):
        """Test that the function returns an HTML plot fragment when requested."""
        data = get_sample_data()

        result = get_qual_plots(data, "virus_a", as_html=True)

        self.assertIsInstance(result, str)
        self.assertIn("<div", result)
        self.assertIn("plotly", result.lower())

    def test_returns_json_by_default(self):
        """Test that the function returns JSON by default."""
        data = get_sample_data()

        result = get_qual_plots(data, "virus_a")

        self.assertIsInstance(result, str)
        self.assertTrue(result.startswith("{"))
