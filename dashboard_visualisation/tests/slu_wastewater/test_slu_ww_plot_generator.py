"""Test functions for the plot generator."""

from unittest.mock import patch

import polars as pl
from django.test import SimpleTestCase

from dashboard_visualisation.slu_wastewater.constants import expected_columns
from dashboard_visualisation.slu_wastewater.plot_generator import generate_figures
from dashboard_visualisation.tests.fixtures.slu_ww_sample_data import get_sample_data


class TestGenerateFigures(SimpleTestCase):
    """Test generation of serology dashboard figures."""

    def setUp(self):
        """Set up mock patches for helper functions."""
        patch(
            "dashboard_visualisation.slu_wastewater.plot_generator.VIRUSES_OF_INTEREST",
            ["virus_a", "virus_b"],
        ).start()

        self.read_csv = patch(
            "dashboard_visualisation.slu_wastewater.plot_generator.read_csv_dataframe"
        ).start()

        self.sites_info = patch(
            "dashboard_visualisation.slu_wastewater.plot_generator.get_sites_info"
        ).start()

        self.filter_input = patch(
            "dashboard_visualisation.slu_wastewater.plot_generator.get_input_for_filters"
        ).start()

        self.recent_data = patch(
            "dashboard_visualisation.slu_wastewater.plot_generator.get_recent_data_info"
        ).start()

        self.qual_overview = patch(
            "dashboard_visualisation.slu_wastewater.plot_generator.get_qual_overview_plot"
        ).start()

        self.qual_plots = patch(
            "dashboard_visualisation.slu_wastewater.plot_generator.get_qual_plots"
        ).start()

        self.addCleanup(patch.stopall)

        self.data = get_sample_data()

        self.read_csv.return_value = self.data
        self.sites_info.return_value = [("Site", "Num. of residents")]
        self.filter_input.return_value = {"input_years": [2024]}
        self.recent_data.return_value = {"sampling_date": "2024-01-15"}
        self.qual_overview.return_value = "qual-overview"
        self.qual_plots.return_value = "qual-plot"

    def test_returns_expected_figure_keys(self):
        """Test that the function returns all expected figure entries."""
        result = generate_figures(object())

        self.assertIn("raw_data", result)
        self.assertIn("sites_info", result)
        self.assertIn("filter_input_context", result)
        self.assertIn("recent_data_info", result)
        self.assertIn("qual_overview_plot", result)
        self.assertIn("qual_plot_virus_a", result)
        self.assertIn("qual_plot_virus_b", result)

    def test_stores_raw_data_as_dictionary(self):
        """Test that filtered raw data is stored as a dictionary."""
        result = generate_figures(object())

        self.assertIsInstance(result["raw_data"], dict)

    def test_filters_data_to_viruses_of_interest(self):
        """Test that only viruses of interest are included."""
        result = generate_figures(object())

        raw_data = pl.DataFrame(result["raw_data"])

        self.assertTrue(set(raw_data["target"].unique()).issubset({"virus_a", "virus_b"}))

    def test_calls_helper_functions(self):
        """Test that the expected helper functions are called."""
        generate_figures(object())

        self.sites_info.assert_called_once()
        self.filter_input.assert_called_once()
        self.recent_data.assert_called_once()
        self.qual_overview.assert_called_once()

    def test_creates_one_plot_per_virus(self):
        """Test that one qualitative plot is generated for each virus."""
        result = generate_figures(object())

        self.assertEqual(self.qual_plots.call_count, 2)

        called_viruses = {call.kwargs["virus"] for call in self.qual_plots.call_args_list}

        self.assertEqual(called_viruses, {"virus_a", "virus_b"})
        self.assertIn("qual_plot_virus_a", result)
        self.assertIn("qual_plot_virus_b", result)

    def test_reads_source_file_with_expected_arguments(self):
        """Test that the source file is read with the expected configuration."""
        source_file = object()

        generate_figures(source_file)

        self.read_csv.assert_called_once_with(
            source_file, columns=expected_columns, null_values=["", "NA", "N/A"]
        )
