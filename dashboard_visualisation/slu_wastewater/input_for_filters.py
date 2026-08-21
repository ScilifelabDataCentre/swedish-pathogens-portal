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
        "input_years": sampling_date.dt.year().unique().sort().cast(pl.String).to_list(),
        "input_months": sampling_date.dt.month().unique().sort().cast(pl.String).to_list(),
        "input_sites": data.get_column("city").unique().sort().to_list(),
        "input_methods": norm_methods_map,
        "input_timeseries": timeseries_map,
    }
