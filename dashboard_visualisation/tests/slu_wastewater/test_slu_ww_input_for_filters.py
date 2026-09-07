"""Tests for the input for filters functionality."""

import polars as pl
from django.test import SimpleTestCase

from dashboard_visualisation.slu_wastewater.constants import norm_methods_map, timeseries_map
from dashboard_visualisation.slu_wastewater.input_for_filters import get_input_for_filters


class TestGetInputForFilters(SimpleTestCase):
    """Test filter input generation from dashboard data."""

    def test_returns_sorted_filter_values(self):
        """Test that the function returns sorted years, months, viruses, and sites."""
        data = pl.DataFrame(
            {
                "sampling_date": ["2024-06-15", "2023-03-10", "2024-01-20", "2023-06-05"],
                "target": ["virus_b", "virus_a", "virus_b", "virus_a"],
                "city": ["Stockholm", "Gothenburg", "Gothenburg", "Stockholm"],
            }
        )

        result = get_input_for_filters(data)

        self.assertEqual(result["input_years"], ["2023", "2024"])
        self.assertEqual(result["input_sites"], ["Gothenburg", "Stockholm"])

    def test_returns_configured_methods_and_timeseries(self):
        """Test that the function returns the configured methods and timeseries."""
        data = pl.DataFrame(
            {"sampling_date": ["2024-01-10"], "target": ["virus_a"], "city": ["Stockholm"]}
        )

        result = get_input_for_filters(data)

        self.assertIs(result["input_methods"], norm_methods_map)
        self.assertIs(result["input_timeseries"], timeseries_map)
        self.assertEqual(result["input_months"], list(map(str, range(1, 13))))

    def test_returns_unique_filter_values(self):
        """Test that duplicate dates, viruses, and sites are returned only once."""
        data = pl.DataFrame(
            {
                "sampling_date": ["2024-01-10", "2024-01-10", "2024-01-10"],
                "target": ["virus_a", "virus_a", "virus_a"],
                "city": ["Stockholm", "Stockholm", "Stockholm"],
            }
        )

        result = get_input_for_filters(data)

        self.assertEqual(result["input_years"], ["2024"])
        self.assertEqual(result["input_sites"], ["Stockholm"])
