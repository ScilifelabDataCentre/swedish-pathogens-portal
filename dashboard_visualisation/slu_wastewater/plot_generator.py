"""Generate plots for SLU wastewater dashboard visualisation."""

from typing import Any

import polars as pl
from django.utils.text import slugify

from ..utils.uploads import SourceFile, read_csv_dataframe
from .constants import VIRUSES_OF_INTEREST, city_display_names, expected_columns
from .input_for_filters import get_input_for_filters
from .qualitative_plots import get_qual_overview_plot, get_qual_plots
from .recent_data import get_recent_data_info
from .site_info import get_sites_info


def generate_figures(source_file: SourceFile) -> dict[str, Any]:
    """Generate Plotly figures for the SLU wastewater dashboard."""

    figures = {}

    source_df = read_csv_dataframe(
        source_file, columns=expected_columns, null_values=["", "NA", "N/A"]
    )
    data = source_df.filter(pl.col("target").is_in(VIRUSES_OF_INTEREST))
    data = data.with_columns(pl.col("city").replace(city_display_names).alias("city"))

    # store the raw data to be used while generating the plots with filters
    figures["raw_data"] = data.to_dict(as_series=False)

    # site info for methodology page
    figures["sites_info"] = get_sites_info(data=data)

    # input information for filters
    figures["filter_input_context"] = get_input_for_filters(data=data)

    # recent data summary
    figures["recent_data_info"] = get_recent_data_info(data=data)

    # combined qualitative overview plot
    figures["qual_overview_plot"] = get_qual_overview_plot(data=data)

    # qualitative plot for each virus
    for virus in data["target"].unique().sort().to_list():
        figures[f"qual_plot_{slugify(virus)}"] = get_qual_plots(data=data, virus=virus)

    return figures
