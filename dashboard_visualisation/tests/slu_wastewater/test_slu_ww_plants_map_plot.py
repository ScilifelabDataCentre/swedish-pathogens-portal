"""Tests for the plants map plot generation."""

import plotly.graph_objects as go
import polars as pl
from django.test import SimpleTestCase

from dashboard_visualisation.slu_wastewater.plants_map_plot import (
    combined_stockholm_text,
    get_ww_plants_map_plot,
)
from dashboard_visualisation.tests.fixtures.slu_ww_sample_data import get_sample_data


class TestGetWWPlantsMapPlot(SimpleTestCase):
    """Test the get_ww_plants_map_plot function."""

    def setUp(self):
        """Set up sample data for tests."""
        self.data = get_sample_data()

    def test_creates_map_with_counties_and_plant_markers(self):
        """Test that the figure contains the Sweden map and plant markers."""

        figure = get_ww_plants_map_plot(self.data, as_fig=True)

        self.assertEqual(len(figure.data), 2)
        self.assertIsInstance(figure.data[0], go.Choropleth)
        self.assertIsInstance(figure.data[1], go.Scattergeo)

    def test_combines_stockholm_sites(self):
        """Test that Stockholm sites are combined into one plant population."""
        data = pl.DataFrame(
            {
                "city": [
                    "Stockholm-Bromma",
                    "Stockholm-Grödinge",
                    "Stockholm-Hendriksdal",
                    "Stockholm-Käppala",
                ],
                "inhabitants": [100_000, 200_000, 300_000, 400_000],
            }
        )

        figure = get_ww_plants_map_plot(data, as_fig=True)

        plant_trace = figure.data[1]
        customdata = list(plant_trace.customdata)
        stockholm = next(row for row in customdata if row[4] == combined_stockholm_text)

        self.assertIsNotNone(stockholm)
        self.assertEqual(stockholm[3], 1_000_000)

    def test_returns_html_when_requested(self):
        """Test that the function returns an HTML string when as_html is True."""
        result = get_ww_plants_map_plot(self.data, as_html=True)

        self.assertIsInstance(result, str)
        self.assertIn("<div", result)
        self.assertIn("plotly", result.lower())

    def test_returns_json_by_default(self):
        """Test that the function returns a JSON string when as_fig and as_html are False."""
        result = get_ww_plants_map_plot(self.data)
        self.assertIsInstance(result, dict)
