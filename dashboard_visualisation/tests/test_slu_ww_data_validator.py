"""Test functions for SLU Wastewater Data Validator."""

from django.test import SimpleTestCase

from dashboard_visualisation.slu_wastewater.constants import expected_columns
from dashboard_visualisation.slu_wastewater.data_validator import validate_source_columns


class TestValidateSourceColumns(SimpleTestCase):
    """Test cases for the `validate_source_columns` function."""

    def test_returns_none_when_all_expected_columns_are_present(self):
        """Test that the function returns None when all expected columns are present."""
        columns = list(expected_columns)

        result = validate_source_columns(columns)

        self.assertIsNone(result)

    def test_returns_missing_column_when_one_column_is_missing(self):
        """Test that the function returns the missing column when one column is missing."""
        columns = list(expected_columns)
        missing_column = columns.pop()

        result = validate_source_columns(columns)

        self.assertEqual(result, f"Missing columns: {missing_column}")

    def test_returns_all_missing_columns(self):
        """Test that the function returns all missing columns when multiple columns are missing."""
        columns = list(expected_columns)
        missing_columns = set(columns[:2])
        columns = columns[2:]

        result = validate_source_columns(columns)

        self.assertIsNotNone(result)
        self.assertTrue(result.startswith("Missing columns: "))

        reported_columns = set(result.removeprefix("Missing columns: ").split(", "))

        self.assertEqual(reported_columns, missing_columns)

    def test_extra_columns_are_allowed(self):
        """Test that the function allows extra columns in the input."""
        columns = list(expected_columns) + ["extra_column"]

        result = validate_source_columns(columns)

        self.assertIsNone(result)

    def test_empty_columns_reports_all_expected_columns_as_missing(self):
        """Test that the function reports all expected columns as missing when input is empty."""
        result = validate_source_columns([])

        self.assertIsNotNone(result)

        reported_columns = set(result.removeprefix("Missing columns: ").split(", "))

        self.assertEqual(reported_columns, set(expected_columns))
