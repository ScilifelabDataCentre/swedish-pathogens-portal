"""Tests for the recent data functionality."""

import polars as pl
from django.test import SimpleTestCase

from dashboard_visualisation.slu_wastewater.recent_data import get_recent_data_info
from dashboard_visualisation.tests.fixtures.slu_ww_sample_data import get_sample_data


class TestGetRecentDataInfo(SimpleTestCase):
    """Test recent sampling data information."""

    def test_returns_recent_data_summary(self):
        """Test that the function returns the summary for the most recent sampling date."""
        data = get_sample_data()

        result = get_recent_data_info(data)

        self.assertEqual(result["sampling_date"], "2024-01-24")
        self.assertEqual(result["sampling_sites"], "Goteborg and Kalmar.")

        expected_population = round(((600000 + 40000) / 10587710) * 100)

        self.assertEqual(result["sampling_sites_pop"], expected_population)
        self.assertEqual(
            result["sample_summary"],
            [
                ("Target", "Analysed", "Positive", "Valid"),
                ("virus_a", 2, 1, 2),
                ("virus_b", 2, 1, 2),
            ],
        )

    def test_returns_single_sampling_site_without_and(self):
        """Test that the function formats a single sampling site without and."""
        data = pl.DataFrame(
            {
                "sampling_date": ["2024-01-10", "2024-01-17"],
                "city": ["Goteborg", "Goteborg"],
                "inhabitants": [100000, 100000],
                "target": ["virus_a", "virus_a"],
                "category": ["Positive sample", "Negative sample"],
            }
        ).with_columns(pl.col("sampling_date").str.to_date())

        result = get_recent_data_info(data)

        self.assertEqual(result["sampling_sites"], "Goteborg.")
        self.assertEqual(
            result["sample_summary"],
            [("Target", "Analysed", "Positive", "Valid"), ("virus_a", 1, 0, 1)],
        )

    def test_uses_only_most_recent_sampling_date(self):
        """Test that the summary excludes samples from earlier sampling dates."""
        data = pl.DataFrame(
            {
                "sampling_date": ["2024-01-10", "2024-01-10", "2024-01-17"],
                "city": ["Goteborg", "Kalmar", "Goteborg"],
                "inhabitants": [100000, 50000, 100000],
                "target": ["virus_old", "virus_old", "virus_current"],
                "category": ["Positive sample", "Positive sample", "Negative sample"],
            }
        ).with_columns(pl.col("sampling_date").str.to_date())

        result = get_recent_data_info(data)

        self.assertEqual(
            result["sample_summary"],
            [("Target", "Analysed", "Positive", "Valid"), ("virus_current", 1, 0, 1)],
        )
        self.assertEqual(result["sampling_sites"], "Goteborg.")
