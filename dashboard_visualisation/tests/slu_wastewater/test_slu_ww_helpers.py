"""Test functions for SLU Wastewater Helpers."""

from datetime import datetime

import polars as pl
from django.test import SimpleTestCase

from dashboard_visualisation.slu_wastewater.helpers import (
    get_range_date,
    get_timeline_annotation_updatemenus,
)


class TestGetRangeDate(SimpleTestCase):
    """Test cases for the `get_range_date` function."""

    def test_returns_range_for_string_dates(self):
        """Tests that the function returns a three-day-padded range for string dates."""
        dates = pl.Series("dates", ["2024-01-10", "2024-03-15", "2024-06-20"])

        result = get_range_date(dates, 2024)

        self.assertEqual(result, ["2024-01-07", "2024-06-23"])

    def test_returns_range_for_datetime_dates(self):
        """Tests that the function returns a three-day-padded range for datetime dates."""
        dates = pl.Series(
            "dates",
            [datetime(2024, 1, 10), datetime(2024, 3, 15), datetime(2024, 6, 20)],
        )

        result = get_range_date(dates, 2024)

        self.assertEqual(result, ["2024-01-07", "2024-06-23"])

    def test_accepts_year_as_string(self):
        """Tests that the function accepts the year as a string."""
        dates = pl.Series("dates", ["2023-06-10", "2024-01-10", "2024-06-20"])

        result = get_range_date(dates, "2024")

        self.assertEqual(result, ["2024-01-07", "2024-06-23"])

    def test_uses_custom_date_format(self):
        """Tests that the function formats the result using the supplied format."""
        dates = pl.Series("dates", ["2024-01-10", "2024-06-20"])

        result = get_range_date(dates, 2024, "%d/%m/%Y")

        self.assertEqual(result, ["07/01/2024", "23/06/2024"])

    def test_only_uses_dates_from_requested_year(self):
        """Tests that the function ignores dates belonging to other years."""
        dates = pl.Series("dates", ["2023-12-20", "2024-03-15", "2025-01-10"])

        result = get_range_date(dates, 2024)

        self.assertEqual(result, ["2024-03-12", "2024-03-18"])


class TestGetTimelineAnnotationUpdatemenus(SimpleTestCase):
    """Test timeline annotations and update menus."""

    def test_returns_empty_annotations_and_all_button(self):
        """Test that the function returns empty annotations and an All button."""
        timeline = pl.Series("timeline", [datetime(2023, 1, 10), datetime(2024, 1, 10)])

        annotations, updatemenus = get_timeline_annotation_updatemenus(timeline, [2023, 2024])

        self.assertEqual(annotations, [])
        self.assertEqual(len(updatemenus), 1)

        menu = updatemenus[0]
        self.assertEqual(menu["type"], "buttons")
        self.assertEqual(menu["direction"], "left")
        self.assertEqual(menu["active"], 2)

        all_button = menu["buttons"][0]
        self.assertEqual(all_button["label"], "All")
        self.assertEqual(all_button["method"], "relayout")
        self.assertEqual(
            all_button["args"],
            [{"xaxis.autorange": True}],
        )

    def test_creates_year_buttons_with_date_ranges(self):
        """Test that the function creates a button for each year with its date range."""
        timeline = pl.Series(
            "timeline",
            [
                datetime(2023, 1, 10),
                datetime(2023, 6, 20),
                datetime(2024, 2, 15),
                datetime(2024, 8, 25),
            ],
        )

        _, updatemenus = get_timeline_annotation_updatemenus(timeline, [2023, 2024])

        buttons = updatemenus[0]["buttons"]

        self.assertEqual(len(buttons), 3)

        self.assertEqual(buttons[1]["label"], 2023)
        self.assertEqual(buttons[1]["args"], [{"xaxis.range": ["2023-01-07", "2023-06-23"]}])

        self.assertEqual(buttons[2]["label"], 2024)
        self.assertEqual(buttons[2]["args"], [{"xaxis.range": ["2024-02-12", "2024-08-28"]}])

    def test_accepts_string_timeline(self):
        """Test that the function converts a string timeline to datetime values."""
        timeline = pl.Series("timeline", ["2024-01-10", "2024-06-20"])

        _, updatemenus = get_timeline_annotation_updatemenus(timeline, [2024])

        self.assertEqual(
            updatemenus[0]["buttons"][1]["args"], [{"xaxis.range": ["2024-01-07", "2024-06-23"]}]
        )

    def test_adds_yaxis_range_when_resize_yaxis_is_enabled(self):
        """Test that the function adds a y-axis range when resizing is enabled."""
        timeline = pl.Series("timeline", [datetime(2024, 1, 10), datetime(2024, 6, 20)])
        ydata = pl.Series("ydata", [10.0, 100.0])

        _, updatemenus = get_timeline_annotation_updatemenus(
            timeline, [2024], resize_yaxis=True, ydata=ydata
        )

        button = updatemenus[0]["buttons"][1]

        self.assertEqual(button["args"][0]["yaxis.range"], [-7.0, 120.0])

    def test_resizes_all_button_yaxis_when_enabled(self):
        """Test that the All button enables automatic y-axis resizing."""
        timeline = pl.Series("timeline", [datetime(2024, 1, 10)])

        _, updatemenus = get_timeline_annotation_updatemenus(timeline, [2024], resize_yaxis=True)

        all_button = updatemenus[0]["buttons"][0]

        self.assertEqual(all_button["args"], [{"xaxis.autorange": True, "yaxis.autorange": True}])

    def test_does_not_add_yaxis_range_without_ydata(self):
        """Test that the year button has no y-axis range when ydata is not provided."""
        timeline = pl.Series("timeline", [datetime(2024, 1, 10)])

        _, updatemenus = get_timeline_annotation_updatemenus(timeline, [2024], resize_yaxis=True)

        button = updatemenus[0]["buttons"][1]

        self.assertNotIn("yaxis.range", button["args"][0])
