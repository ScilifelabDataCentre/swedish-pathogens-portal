"""Test functions for quantitative plots."""

import math

import polars as pl
from django.test import SimpleTestCase

from dashboard_visualisation.slu_wastewater.quantitative_plot import (
    get_all_sites_plot,
    get_quant_overview_plot,
    get_single_site_plot,
)
from dashboard_visualisation.tests.fixtures.slu_ww_sample_data import get_sample_data


class TestGetQuantOverviewPlot(SimpleTestCase):
    """Test quantitative overview scatter plot generation."""

    def test_calculates_population_weighted_values(self):
        """Test that values are aggregated using population-weighted means."""
        data = get_sample_data()

        figure = get_quant_overview_plot(data, as_fig=True, years=["2024"])

        scatter_traces = [trace for trace in figure.data if trace.mode == "markers"]

        self.assertEqual(len(scatter_traces), 2)

        values = list(scatter_traces[0].y)

        self.assertEqual(values, [406.25, 506.25, 606.25])

    def test_calculates_rolling_mean(self):
        """Test that the rolling line uses the requested rolling window."""
        data = get_sample_data()

        figure = get_quant_overview_plot(data, as_fig=True, years=["2024"], timeseries=["2"])

        line_traces = [trace for trace in figure.data if trace.mode == "lines"]

        self.assertEqual(len(line_traces), 2)

        rolling_values = list(line_traces[0].y)

        self.assertEqual(rolling_values, [406.25, 456.25, 556.25])

    def test_uses_requested_method(self):
        """Test that the requested measurement method is used for the y values."""
        data = get_sample_data()

        figure = get_quant_overview_plot(
            data, as_fig=True, years=["2024"], methods=["copies_day_inhabitant"]
        )

        scatter_traces = [trace for trace in figure.data if trace.mode == "markers"]

        values = list(scatter_traces[0].y)

        self.assertEqual(values[0], 4.0625)

    def test_filters_by_year(self):
        """Test that only the requested year is included."""
        data = get_sample_data()

        figure = get_quant_overview_plot(data, as_fig=True, years=["2024"])

        scatter_traces = [trace for trace in figure.data if trace.mode == "markers"]

        self.assertEqual(len(scatter_traces), 2)

        for trace in scatter_traces:
            self.assertEqual(list(trace.x), [2, 3, 4])

    def test_filters_by_site(self):
        """Test that only the requested site is included."""
        data = get_sample_data()

        figure = get_quant_overview_plot(data, as_fig=True, years=["2024"], sites=["Göteborg"])

        scatter_traces = [trace for trace in figure.data if trace.mode == "markers"]

        self.assertEqual(len(scatter_traces), 2)

        values = [list(trace.y) for trace in scatter_traces]

        self.assertIn([400.0, 500.0, 600.0], values)
        self.assertIn([450.0, 550.0, 650.0], values)

    def test_filters_by_month(self):
        """Test that only samples within the requested month range are included."""
        data = get_sample_data()

        figure = get_quant_overview_plot(data, as_fig=True, years=["2024"], months=["1"])

        scatter_traces = [trace for trace in figure.data if trace.mode == "markers"]

        self.assertEqual(len(scatter_traces), 2)

        for trace in scatter_traces:
            self.assertEqual(len(trace.x), 3)

    def test_creates_scatter_and_rolling_line(self):
        """Test that the figure contains both scatter points and rolling lines."""
        data = get_sample_data()

        figure = get_quant_overview_plot(data, as_fig=True)

        scatter_traces = [trace for trace in figure.data if trace.mode == "markers"]
        line_traces = [trace for trace in figure.data if trace.mode == "lines"]

        self.assertEqual(len(scatter_traces), 4)
        self.assertEqual(len(line_traces), 4)

    def test_accepts_dictionary_input(self):
        """Test that the function accepts dictionary input."""
        data = get_sample_data()

        figure = get_quant_overview_plot(data.to_dict(as_series=False), as_fig=True)

        self.assertTrue(figure.data)

    def test_returns_html_when_requested(self):
        """Test that the function returns an HTML plot fragment when requested."""
        data = get_sample_data()

        result = get_quant_overview_plot(data, as_html=True)

        self.assertIsInstance(result, str)
        self.assertIn("<div", result)
        self.assertIn("plotly", result)

    def test_returns_json_by_default(self):
        """Test that the function returns JSON by default."""
        data = get_sample_data()

        result = get_quant_overview_plot(data)

        self.assertIsInstance(result, dict)


class TestGetAllSitesPlot(SimpleTestCase):
    """Test all-sites quantitative time-series plot generation."""

    def test_creates_trace_for_each_site(self):
        """Test that the function creates one trace for each site."""
        data = get_sample_data()

        figure = get_all_sites_plot(data, "virus_a", as_fig=True)

        self.assertEqual({trace.name for trace in figure.data}, {"Göteborg", "Kalmar"})

    def test_trace_contains_expected_dates(self):
        """Test that each site trace contains its sampling dates."""
        data = get_sample_data()

        figure = get_all_sites_plot(data, "virus_a", as_fig=True)

        expected_dates = [
            "2023-01-10",
            "2023-01-17",
            "2023-01-24",
            "2024-01-10",
            "2024-01-17",
            "2024-01-24",
        ]

        for trace in figure.data:
            self.assertEqual(list(trace.x), expected_dates)

    def test_calculates_rolling_mean(self):
        """Test that the requested rolling window is applied per site."""
        data = get_sample_data()

        figure = get_all_sites_plot(data, "virus_a", as_fig=True, timeseries=["2"])

        traces = {trace.name: list(trace.y) for trace in figure.data}

        self.assertEqual(traces["Göteborg"], [100.0, 150.0, 250.0, 350.0, 450.0, 550.0])
        self.assertEqual(traces["Kalmar"], [200.0, 250.0, 350.0, 450.0, 550.0, 650.0])

    def test_filters_by_virus(self):
        """Test that samples belonging to other viruses are excluded."""
        data = get_sample_data()

        # Remove virus_a from Kalmar by changing those rows to virus_b.
        data = data.with_columns(
            pl.when((pl.col("city") == "Kalmar") & (pl.col("target") == "virus_a"))
            .then(pl.lit("virus_b"))
            .otherwise(pl.col("target"))
            .alias("target")
        )

        figure = get_all_sites_plot(data, "virus_a", as_fig=True)

        self.assertEqual(len(figure.data), 1)
        self.assertEqual(figure.data[0].name, "Göteborg")

    def test_uses_requested_method(self):
        """Test that the requested measurement method is used."""
        data = get_sample_data()

        figure = get_all_sites_plot(data, "virus_a", as_fig=True, methods=["copies_day_inhabitant"])

        traces = {trace.name: list(trace.y) for trace in figure.data}

        self.assertEqual(traces["Göteborg"], [1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
        self.assertEqual(traces["Kalmar"], [2.0, 3.0, 4.0, 5.0, 6.0, 7.0])

    def test_accepts_dictionary_input(self):
        """Test that the function accepts dictionary input."""
        data = get_sample_data()

        figure = get_all_sites_plot(data.to_dict(as_series=False), "virus_a", as_fig=True)

        self.assertEqual(len(figure.data), 2)

    def test_returns_html_when_requested(self):
        """Test that the function returns an HTML plot fragment when requested."""
        data = get_sample_data()

        result = get_all_sites_plot(data, "virus_a", as_html=True)

        self.assertIsInstance(result, str)
        self.assertIn("<div", result)
        self.assertIn("plotly", result)

    def test_returns_json_by_default(self):
        """Test that the function returns JSON by default."""
        data = get_sample_data()

        result = get_all_sites_plot(data, "virus_a")

        self.assertIsInstance(result, dict)


class TestGetSingleSitePlot(SimpleTestCase):
    """Test single-site quantitative time-series plot generation."""

    def test_creates_trace_for_each_method(self):
        """Test that the function creates one trace for each normalization method."""
        data = get_sample_data()

        figure = get_single_site_plot(data, "virus_a", as_fig=True, sites=["Göteborg"])

        self.assertEqual(
            {trace.name for trace in figure.data},
            {"PMMoV normalised", "Flow normalised", "Non normalised"},
        )

    def test_filters_by_site(self):
        """Test that only data from the requested site is plotted."""
        data = get_sample_data()

        figure = get_single_site_plot(data, "virus_a", as_fig=True, sites=["Göteborg"])

        expected_count = data.filter(
            (data["target"] == "virus_a") & (data["city"] == "Göteborg")
        ).height

        for trace in figure.data:
            self.assertEqual(len(trace.x), expected_count)

    def test_filters_by_virus(self):
        """Test that only data for the requested virus is plotted."""
        data = get_sample_data()

        figure = get_single_site_plot(data, "virus_b", as_fig=True, sites=["Göteborg"])

        expected_count = data.filter(
            (data["target"] == "virus_b") & (data["city"] == "Göteborg")
        ).height

        self.assertEqual(len(figure.data), 3)

        for trace in figure.data:
            self.assertEqual(len(trace.x), expected_count)

    def test_applies_rolling_mean(self):
        """Test that the requested rolling window is applied to each method."""
        data = get_sample_data()

        figure = get_single_site_plot(
            data, "virus_a", as_fig=True, sites=["Göteborg"], timeseries=["2"]
        )

        source = data.filter((data["target"] == "virus_a") & (data["city"] == "Göteborg")).sort(
            "sampling_date"
        )

        traces = {trace.name: list(trace.y) for trace in figure.data}

        scales = {"PMMoV normalised": 66983, "Flow normalised": 0.003, "Non normalised": 1}

        columns = {
            "PMMoV normalised": "pmmov_normalised",
            "Flow normalised": "copies_day_inhabitant",
            "Non normalised": "copies_l",
        }

        for trace_name, column in columns.items():
            values = source[column].to_list()

            self.assertTrue(math.isnan(traces[trace_name][0]))

            for actual, first, second in zip(
                traces[trace_name][1:], values[:-1], values[1:], strict=True
            ):
                expected = ((first + second) / 2) * scales[trace_name]
                self.assertAlmostEqual(actual, expected)

    def test_applies_method_scaling(self):
        """Test that each normalization method is multiplied by its configured scale."""
        data = get_sample_data()

        figure = get_single_site_plot(data, "virus_a", as_fig=True, sites=["Göteborg"])

        source = data.filter((data["target"] == "virus_a") & (data["city"] == "Göteborg")).sort(
            "sampling_date"
        )

        traces = {trace.name: list(trace.y) for trace in figure.data}

        expected = {
            "PMMoV normalised": [value * 66983 for value in source["pmmov_normalised"].to_list()],
            "Flow normalised": [
                value * 0.003 for value in source["copies_day_inhabitant"].to_list()
            ],
            "Non normalised": source["copies_l"].to_list(),
        }

        for trace_name, expected_values in expected.items():
            for actual, expected_value in zip(traces[trace_name], expected_values, strict=True):
                self.assertAlmostEqual(actual, expected_value)

    def test_uses_requested_rolling_window(self):
        """Test that changing the rolling window changes the plotted values."""
        data = get_sample_data()

        figure = get_single_site_plot(
            data, "virus_a", as_fig=True, sites=["Göteborg"], timeseries=["3"]
        )

        source = data.filter((data["target"] == "virus_a") & (data["city"] == "Göteborg")).sort(
            "sampling_date"
        )

        values = list(next(trace for trace in figure.data if trace.name == "Non normalised").y)

        source_values = source["copies_l"].to_list()

        self.assertTrue(math.isnan(values[0]))
        self.assertTrue(math.isnan(values[1]))

        for actual, window_values in zip(
            values[2:],
            zip(source_values[:-2], source_values[1:-1], source_values[2:], strict=True),
            strict=True,
        ):
            expected = sum(window_values) / 3
            self.assertAlmostEqual(actual, expected)

    def test_accepts_dictionary_input(self):
        """Test that the function accepts dictionary input."""
        data = get_sample_data()

        figure = get_single_site_plot(
            data.to_dict(as_series=False), "virus_a", as_fig=True, sites=["Göteborg"]
        )

        self.assertEqual(len(figure.data), 3)
        self.assertEqual(
            {trace.name for trace in figure.data},
            {"PMMoV normalised", "Flow normalised", "Non normalised"},
        )

    def test_creates_timeline_controls(self):
        """Test that the function creates timeline controls for available years."""
        data = get_sample_data()

        figure = get_single_site_plot(data, "virus_a", as_fig=True, sites=["Göteborg"])

        self.assertEqual(len(figure.layout.updatemenus), 1)

        buttons = figure.layout.updatemenus[0].buttons

        self.assertEqual(len(buttons), 3)
        self.assertEqual(buttons[0].label, "All")
        self.assertEqual(str(buttons[1].label), "2023")
        self.assertEqual(str(buttons[2].label), "2024")

    def test_returns_html_when_requested(self):
        """Test that the function returns an HTML plot fragment when requested."""
        data = get_sample_data()

        result = get_single_site_plot(data, "virus_a", as_html=True, sites=["Göteborg"])

        self.assertIsInstance(result, str)
        self.assertIn("<div", result)
        self.assertIn("plotly", result)

    def test_returns_json_by_default(self):
        """Test that the function returns JSON by default."""
        data = get_sample_data()

        result = get_single_site_plot(data, "virus_a", sites=["Göteborg"])

        self.assertIsInstance(result, dict)
