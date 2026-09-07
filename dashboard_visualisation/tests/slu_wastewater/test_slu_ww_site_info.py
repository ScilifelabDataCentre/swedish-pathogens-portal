"""Tests for the site info functionality."""

import polars as pl
from django.test import SimpleTestCase

from dashboard_visualisation.slu_wastewater.site_info import get_sites_info


class TestGetSitesInfo(SimpleTestCase):
    """Test site information generation from dashboard data."""

    def test_returns_sorted_unique_site_information(self):
        """Test that the function returns unique sites sorted by city."""
        data = pl.DataFrame(
            {
                "city": ["Stockholm", "Gothenburg", "Stockholm", "Uppsala"],
                "inhabitants": [100000, 50000, 100000, 30000],
            }
        )

        result = get_sites_info(data)

        self.assertEqual(
            result,
            [
                ("Site", "Num. of residents"),
                ("Gothenburg", 50000),
                ("Stockholm", 100000),
                ("Uppsala", 30000),
            ],
        )

    def test_returns_header_when_data_is_empty(self):
        """Test that the function returns only the header for empty data."""
        data = pl.DataFrame(
            {"city": [], "inhabitants": []}, schema={"city": pl.String, "inhabitants": pl.Int64}
        )

        result = get_sites_info(data)

        self.assertEqual(result, [("Site", "Num. of residents")])

    def test_does_not_modify_input_data(self):
        """Test that the function does not modify the input DataFrame."""
        data = pl.DataFrame(
            {
                "city": ["Stockholm", "Gothenburg"],
                "inhabitants": [100000, 50000],
                "extra": ["a", "b"],
            }
        )
        original = data.clone()

        get_sites_info(data)

        self.assertTrue(data.equals(original))
