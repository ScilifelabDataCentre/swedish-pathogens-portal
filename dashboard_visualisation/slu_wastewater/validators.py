"""Check if the data is valid for the dashboard visualisation."""

import polars as pl
from django.http import Http404
from django.http.request import QueryDict

from .constants import expected_columns
from .input_for_filters import get_input_for_filters


def validate_source_columns(columns: list[str]) -> str | None:
    """Validate that the uploaded file has the expected columns for this dashboard."""
    missing_columns = set(expected_columns) - set(columns)
    if missing_columns:
        return f"Missing columns: {', '.join(sorted(missing_columns))}"
    return None


def validate_overview_plot_request_params(
    q: QueryDict, raw_data: dict | pl.DataFrame
) -> dict[str, list[str]]:
    """Validate the request parameters for the overview plot.

    Ensures that the requested parameters are valid and present in the raw data.
    Raises Http404 if invalid.
    """

    # check if data is a dict, if so convert it to dataframe
    if isinstance(raw_data, dict):
        raw_data = pl.DataFrame(raw_data)

    expected_inputs = get_input_for_filters(raw_data)
    expected_inputs = {
        k.replace("input_", ""): set(v.keys()) if isinstance(v, dict) else set(v)
        for k, v in expected_inputs.items()
    }

    _validate_param_keys(q, expected_inputs)

    for param in q:
        values = q.getlist(param)
        expected_values = expected_inputs[param]
        if len(values) > len(expected_values):
            raise Http404(f"Too many values for parameter: {param}")

        values_set = set(values)
        if len(values_set) != len(values):
            raise Http404(f"Duplicate values found for parameter: {param}")
        if not values_set.issubset(expected_values):
            raise Http404(f"Invalid values for parameter: {param}")

    return dict(q)


def validate_analysis_plot_request_params(
    q: QueryDict, raw_data: dict | pl.DataFrame
) -> dict[str, list[str]]:
    """Validate the request parameters for the quantitative analysis plot.

    Ensures that the requested parameters are valid and present in the raw data.
    Raises Http404 if invalid.
    """

    # check if data is a dict, if so convert it to dataframe
    if isinstance(raw_data, dict):
        raw_data = pl.DataFrame(raw_data)

    input_for_filters = get_input_for_filters(raw_data)
    expected_inputs = {
        "plot-toggle": {"all", "single"},
        "sites": set(input_for_filters.get("input_sites", [])),
        "methods": set(input_for_filters.get("input_methods", {}).keys()),
        "timeseries": set(input_for_filters.get("input_timeseries", {}).keys()),
    }

    _validate_param_keys(q, expected_inputs)

    for param in q:
        values = q.getlist(param)
        if len(values) > 1:
            raise Http404(f"Too many values for parameter: {param}")
        if values[0] not in expected_inputs[param]:
            raise Http404(f"Invalid value for parameter: {param}")

    return dict(q)


# ---------------------------------------------------------------------------------------
# Private helper functions
# ---------------------------------------------------------------------------------------


def _validate_param_keys(passed_params: QueryDict, expected_inputs: dict[str, set[str]]) -> None:
    """Validate the request parameter keys against the expected input keys.

    Raises Http404 if any of the requested parameter keys are too many or missing.
    """

    if len(passed_params) > len(expected_inputs):
        raise Http404("Too many parameters provided in the request.")

    passed_param_keys = set(passed_params.keys())
    expected_param_keys = set(expected_inputs.keys())

    if missing_params := expected_param_keys - passed_param_keys:
        raise Http404(f"Missing parameters: {', '.join(sorted(missing_params))}")
