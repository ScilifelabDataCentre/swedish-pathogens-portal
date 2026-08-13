"""Function to generate the input for the filters used in dashboard."""

import polars as pl

from .constants import norm_methods_map, timeseries_map


def get_input_for_filters(data: pl.DataFrame) -> dict:
    """Return context used to populate dashboard filter inputs.

    Args:
        data: DataFrame containing a "sampling_date", "target",
        and "city" columns.

    Returns:
        Dictionary mapping input names to values/options.

    """
    sampling_date = data["sampling_date"].str.to_date()
    return {
        "input_years": sorted(sampling_date.dt.year().unique().to_list()),
        "input_months": sorted(sampling_date.dt.month().unique().to_list()),
        "input_viruses": sorted(data.get_column("target").unique().to_list()),
        "input_sites": sorted(data.get_column("city").unique().to_list()),
        "input_methods": norm_methods_map,
        "input_timeseries": timeseries_map,
    }
