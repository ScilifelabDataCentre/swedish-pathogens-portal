"""Functions to make qualitative plots for the SLU WW dashboard visualisation."""

import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import polars as pl
from plotly.subplots import make_subplots

from ..utils.plotly import figure_to_json
from .constants import (
    base_legend,
    bgcolor,
    common_axes_settings,
    hmapcolors_map,
    horizontal_legend,
    plotly_to_html_settings,
    zero_margin,
)
from .helpers import get_range_date, get_timeline_annotation_updatemenus

category_map = {
    "Invalid sample": "1",
    "Negative sample": "2",
    "Positive sample": "3",
}

category_order = [c for c, _ in sorted(category_map.items(), key=lambda i: int(i[1]), reverse=True)]


def get_qual_overview_plot(
    data: pl.DataFrame | dict, as_fig: bool = False, as_html: bool = False
) -> str | go.Figure:
    """Create a qualitative stacked percent bar chart.

    The function aggregates the input dataframe into percent shares of sample
    categories per sampling date and creates a multi-facet horizontal stacked
    bar chart across targets.

    Args:
        data (pl.DataFrame | dict): Input dataframe or dictionary. Must contain sampling_date,
            target and category columns.
        as_fig (bool): If True, return the figure as a Plotly figure object.
        as_html (bool): If True, return the figure as an HTML string (fig.to_html()).
            Otherwise return a JSON string (fig.to_json()).

    Returns:
        str | go.Figure: JSON or HTML string or Plotly figure object representing
        the Plotly figure depending on the input parameters.

    """

    # check if data is a dict, if so convert it to dataframe
    if isinstance(data, dict):
        data = pl.DataFrame(data)

    cols_togroup = ["sampling_date", "target", "category"]
    cols_todrop = [
        "inhabitants",
        "pmmov_normalised",
        "copies_day_inhabitant",
        "copies_l",
    ]
    data = data.drop(cols_todrop).unique()

    data_bar = (
        data.group_by(cols_togroup)
        .agg(pl.len().alias("category_count"))
        .with_columns(
            (
                (pl.col("category_count") * 100)
                / (pl.col("category_count").sum().over(cols_togroup[:-1]))
            ).alias("category_percent")
        )
        .sort(
            cols_togroup,
            descending=[False, False, True],
        )
    )

    fig = px.bar(
        data_bar,
        x="sampling_date",
        y="category_percent",
        color="category",
        color_discrete_map=hmapcolors_map,
        category_orders={"category": category_order},
        facet_col="target",
        facet_col_wrap=2,
        facet_col_spacing=0.05,
        facet_row_spacing=0.15,
    )
    fig.update_traces(marker_line_width=0)

    fig.update_xaxes(matches=None, showticklabels=True, **common_axes_settings)

    fig.update_yaxes(matches=None, showticklabels=True, range=[0, 100], **common_axes_settings)

    fig.update_layout(
        plot_bgcolor=bgcolor,
        hovermode=False,
        barmode="stack",
        bargap=0,
        legend={"y": -0.2, **horizontal_legend},
        hoverlabel={"bgcolor": bgcolor},
        margin={"t": 20, "r": 20, "b": 0, "l": 0},
    )
    fig.for_each_annotation(
        lambda a: a.update(text=a.text.split("=")[-1], yshift=3, font={"size": 14})
    )

    if as_fig:
        return fig

    if as_html:
        return fig.to_html(**plotly_to_html_settings)

    return figure_to_json(fig)


def get_qual_plots(
    data: pl.DataFrame | dict, virus: str, as_fig: bool = False, as_html: bool = False
) -> str | go.Figure:
    """Create a combined heatmap and stacked bar chart for qualitative samples.

    The top panel is a heatmap with categories per city and sampling date, and the
    bottom panel is a stacked percentage bar chart summarising category distribution
    per date. The function accepts data as a DataFrame or dict of records.

    Args:
        data (pl.DataFrame): Input dataset with columns at least city,
            sampling_date, target and category. If a dict is supplied it is
            converted to a DataFrame.
        virus (str): The 'target' value to filter the dataset by.
        as_fig (bool): If True, return the figure as a Plotly figure object.
        as_html (bool): If True, return the figure as an HTML string; otherwise
            return a JSON string.

    Returns:
        str | go.Figure: JSON or HTML string or Plotly figure object representing
        the Plotly figure depending on the input parameters.

    """

    # check if data is a dict, if so convert it to dataframe
    if isinstance(data, dict):
        data = pl.DataFrame(data)

    cols_todrop = [
        "inhabitants",
        "pmmov_normalised",
        "copies_day_inhabitant",
        "copies_l",
    ]

    data = data.filter(pl.col("target") == virus).drop(cols_todrop).unique()

    # data processing for heatmap
    pdata = data.pivot(index="city", on="sampling_date", values="category", sort_columns=True).sort(
        "city"
    )
    y_val = pdata["city"].to_list()
    pdata = pdata.drop("city")
    pdata_numeric = pdata.with_columns(pl.all().replace(category_map))
    pdata_text = pdata.fill_null("Not Available")

    # data processing for stack bar
    data_bar = (
        data.group_by(["sampling_date", "category"])
        .agg(pl.len().alias("category_count"))
        .with_columns(
            (
                (pl.col("category_count") * 100)
                / pl.col("category_count").sum().over("sampling_date")
            ).alias("category_percent")
        )
        .sort(
            ["sampling_date", "category"],
            descending=[False, True],
        )
    )

    # make subplots layout
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05)

    for category, value in category_map.items():
        fig.add_trace(
            go.Heatmap(
                z=np.where(pdata_numeric.to_numpy() == value, pdata_numeric.to_numpy(), np.nan),
                x=pdata.columns,
                y=y_val,
                customdata=np.where(
                    pdata_text.to_numpy() == category, pdata_text.to_numpy(), np.nan
                ),
                colorscale=[[0, hmapcolors_map[category]], [1, hmapcolors_map[category]]],
                showscale=False,
                name=category,
                legendgroup=category,
                showlegend=False,
                hoverongaps=False,
                hovertemplate="Date: %{x}<br>City: %{y}<br>Type: %{customdata}<extra></extra>",
            ),
            row=1,
            col=1,
        )

    bar_fig = px.bar(
        data_bar,
        x="sampling_date",
        y="category_percent",
        color="category",
        color_discrete_map=hmapcolors_map,
        category_orders={"category": category_order},
    )
    fig.add_traces(bar_fig["data"], rows=2, cols=1)
    fig.update_traces(marker_line_width=0, row=2)

    fig.update_xaxes(**common_axes_settings)
    fig.update_yaxes(**common_axes_settings)
    fig.update_yaxes(range=[0, 100], row=2, col=1)

    years = data["sampling_date"].str.to_date().dt.year().unique().sort().to_list()

    fig.update_xaxes(range=get_range_date(data["sampling_date"], str(years[-1])), row=2, col=1)

    annotations, updatemenus = get_timeline_annotation_updatemenus(
        data["sampling_date"], years, x=0.5, y=-0.2
    )

    fig.update_layout(
        plot_bgcolor=bgcolor,
        barmode="stack",
        bargap=0,
        annotations=annotations,
        updatemenus=updatemenus,
        legend={**base_legend, "y": 0.95},
        hoverlabel={"bgcolor": bgcolor},
        margin=zero_margin,
    )

    if as_fig:
        return fig

    if as_html:
        return fig.to_html(**plotly_to_html_settings)

    return figure_to_json(fig)
