"""Test functions for SLU Wastewater Data Validator."""

from django.http import Http404, QueryDict
from django.test import SimpleTestCase

from dashboard_visualisation.slu_wastewater.constants import expected_columns
from dashboard_visualisation.slu_wastewater.validators import (
    validate_analysis_plot_request_params,
    validate_overview_plot_request_params,
    validate_source_columns,
)
from dashboard_visualisation.tests.fixtures.slu_ww_sample_data import get_sample_data


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


class TestValidateOverviewPlotRequestParams(SimpleTestCase):
    """Test validation of overview plot request parameters."""

    def test_valid_request_params(self):
        """Test that valid parameters are accepted."""
        q = QueryDict(
            "years=2023&years=2024"
            "&months=1"
            "&sites=Göteborg&sites=Kalmar"
            "&methods=pmmov_normalised"
            "&timeseries=1"
        )
        result = validate_overview_plot_request_params(q, get_sample_data())

        self.assertEqual(result, dict(q))

    def test_dict_raw_data_is_accepted(self):
        """Test that dictionary raw data is accepted."""
        raw_data = get_sample_data().to_dict(as_series=False)
        q = QueryDict("years=2023&months=1&sites=Göteborg&methods=pmmov_normalised&timeseries=1")
        result = validate_overview_plot_request_params(q, raw_data)

        self.assertEqual(result, dict(q))

    def test_too_many_parameters_are_rejected(self):
        """Test that too many parameters are rejected."""
        q = QueryDict(
            "years=2023"
            "&months=1"
            "&sites=Göteborg"
            "&methods=pmmov_normalised"
            "&timeseries=1"
            "&extra=value"
            "&another_extra=value"
        )

        with self.assertRaises(Http404) as context:
            validate_overview_plot_request_params(q, get_sample_data())

        self.assertEqual(str(context.exception), "Too many parameters provided in the request.")

    def test_missing_parameter_is_rejected(self):
        """Test that a missing parameter is rejected."""
        q = QueryDict("years=2023&sites=Göteborg&methods=pmmov_normalised")

        with self.assertRaises(Http404) as context:
            validate_overview_plot_request_params(q, get_sample_data())

        self.assertEqual(str(context.exception), "Missing parameters: months, timeseries")

    def test_too_many_parameter_values_are_rejected(self):
        """Test that too many values for a parameter are rejected."""
        q = QueryDict(
            "years=2023"
            "&months=1"
            "&sites=Göteborg&sites=Kalmar&sites=Umea"
            "&methods=pmmov_normalised"
            "&timeseries=1"
        )

        with self.assertRaises(Http404) as context:
            validate_overview_plot_request_params(q, get_sample_data())

        self.assertEqual(str(context.exception), "Too many values for parameter: sites")

    def test_duplicate_parameter_values_are_rejected(self):
        """Test that duplicate parameter values are rejected."""
        q = QueryDict("years=2023&years=2023&months=1&sites=Göteborg&methods=copies_l&timeseries=1")

        with self.assertRaises(Http404) as context:
            validate_overview_plot_request_params(q, get_sample_data())

        self.assertEqual(str(context.exception), "Duplicate values found for parameter: years")

    def test_invalid_parameter_value_is_rejected(self):
        """Test that an invalid parameter value is rejected."""
        q = QueryDict("years=2023&months=1&sites=Kalmar&methods=invalid&timeseries=1")

        with self.assertRaises(Http404) as context:
            validate_overview_plot_request_params(q, get_sample_data())

        self.assertEqual(str(context.exception), "Invalid values for parameter: methods")


class TestValidateAnalysisPlotRequestParams(SimpleTestCase):
    """Test validation of quantitative analysis plot request parameters."""

    def test_valid_request_params(self):
        """Test that valid analysis plot parameters are accepted."""
        q = QueryDict("plot-toggle=all&sites=Göteborg&methods=pmmov_normalised&timeseries=1")
        result = validate_analysis_plot_request_params(q, get_sample_data())

        self.assertEqual(result, dict(q))

    def test_dict_raw_data_is_accepted(self):
        """Test that dictionary raw data is accepted."""
        raw_data = get_sample_data().to_dict(as_series=False)
        q = QueryDict("plot-toggle=all&sites=Göteborg&methods=pmmov_normalised&timeseries=1")
        result = validate_analysis_plot_request_params(q, raw_data)

        self.assertEqual(result, dict(q))

    def test_too_many_parameters_are_rejected(self):
        """Test that too many analysis parameters are rejected."""
        q = QueryDict("plot-toggle=all&sites=Goteborg&methods=copies_l&timeseries=1&extra=value")

        with self.assertRaises(Http404) as context:
            validate_analysis_plot_request_params(q, get_sample_data())

        self.assertEqual(str(context.exception), "Too many parameters provided in the request.")

    def test_missing_parameter_is_rejected(self):
        """Test that a missing analysis parameter is rejected."""
        q = QueryDict("plot-toggle=all&sites=Goteborg&methods=pmmov_normalised")

        with self.assertRaises(Http404) as context:
            validate_analysis_plot_request_params(q, get_sample_data())

        self.assertEqual(str(context.exception), "Missing parameters: timeseries")

    def test_only_one_parameter_value_is_accepted(self):
        """Test that only one value for each analysis parameter is accepted."""
        q = QueryDict("plot-toggle=all&sites=Kalmar&sites=Kalmar&methods=copies_l&timeseries=1")

        with self.assertRaises(Http404) as context:
            validate_analysis_plot_request_params(q, get_sample_data())

        self.assertEqual(str(context.exception), "Too many values for parameter: sites")

    def test_invalid_parameter_value_is_rejected(self):
        """Test that an invalid parameter value is rejected."""
        q = QueryDict("plot-toggle=invalid&sites=Goteborg&methods=pmmov_normalised&timeseries=1")

        with self.assertRaises(Http404) as context:
            validate_analysis_plot_request_params(q, get_sample_data())

        self.assertEqual(str(context.exception), "Invalid value for parameter: plot-toggle")
