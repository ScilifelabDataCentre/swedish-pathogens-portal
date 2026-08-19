"""Functions to make quantitative plots for the SLU WW dashboard visualisation."""

import plotly.express as px
import plotly.graph_objects as go
import polars as pl

from ..utils.plotly import figure_to_json
from .constants import (
    bgcolor,
    cities_graph_info,
    common_axes_settings,
    gridcolor,
    horizontal_legend,
    plotly_to_html_settings,
    scatter_axes_settings,
    yearcolors_map,
    zero_margin,
)
from .helpers import get_range_date, get_timeline_annotation_updatemenus


def get_quant_overview_plot(
    data: pl.DataFrame | dict, as_fig: bool = False, as_html: bool = False, **f_args
) -> str:
    """Build a quantitative overview scatter plot.

    The function builds a multi-facet Plotly scatter with rolling trendlines for
    the supplied dataset. If `data` is provided as a dict, it is converted to a
    pandas DataFrame first. Optional filtering and display behaviour can be
    provided via keyword arguments.

    Args:
        data (pl.DataFrame | dict): Input dataset as a DataFrame
            dict. Must include at least the columns used by the plot (sampling_date,
            target, inhabitants, and numeric value columns).
        as_fig (bool): If True, return the Plotly figure object.
            If False (default), return a JSON or HTML string depending on `as_html`.
        as_html (bool): If True, return the Plotly figure as an HTML string
            (fig.to_html()). If False (default), return a JSON string (fig.to_json()).
        **f_args: Additional filter arguments provided by the dashboard that affect
            the output. Recognised keys include:
            - year: list[int | str] (years to include)
            - months: list[int | str] (start/end months)
            - site: list[str] (cities/sites to include)
            - method: list[str] (normalisation method, e.g. 'pmmov_normalised')
            - timeseries: list[int | str] (rolling window for trendline)

    Returns:
        str | go.Figure: JSON or HTML string or Plotly figure object representing
        the Plotly figure depending on the input parameters.

    """

    # check if data is a dict, if so convert it to dataframe
    if isinstance(data, dict):
        data = pl.DataFrame(data)

    data = data.with_columns(pl.col("sampling_date").str.to_date())

    # get passed filter args, if not passed use defaults
    f_year = (
        list(map(int, f_args.get("year", [])))
        or data["sampling_date"].dt.year().unique().sort().to_list()
    )
    f_month = [1, int(f_args.get("months", ["12"])[0])]
    f_sites = f_args.get("site", data["city"].unique().sort().to_list())
    f_method = f_args.get("method", ["pmmov_normalised"])[0]
    f_roll = int(f_args.get("timeseries", ["1"])[0])

    cols_common = ["target", "sampling_date", "week", "month", "year"]
    cols_values = ["pmmov_normalised", "copies_day_inhabitant", "copies_l"]
    cols_todrop = ["city", "category"] + cols_values

    data = data.with_columns(
        [
            pl.when(
                (pl.col("sampling_date").dt.week() == 1)
                & (pl.col("sampling_date").dt.month() == 12)
            )
            .then(53)
            .otherwise(pl.col("sampling_date").dt.week())
            .alias("week"),
            pl.col("sampling_date").dt.month().alias("month"),
            pl.col("sampling_date").dt.year().alias("year"),
        ]
    )

    data_filtered = (
        data.filter(
            pl.col("city").is_in(f_sites)
            & pl.col("year").is_in(f_year)
            & (pl.col("month") >= f_month[0])
            & (pl.col("month") <= f_month[1])
        )
        .with_columns(pl.col(f_method).alias("y_val"))
        .drop(cols_todrop)
    )

    data_processed = (
        data_filtered.group_by(cols_common)
        .agg(
            ((pl.col("y_val") * pl.col("inhabitants")).sum() / pl.col("inhabitants").sum()).alias(
                "y_val"
            )
        )
        .with_columns(pl.col("year").cast(pl.String))
        .sort(["target", "year", "week"])
        .with_columns(
            pl.col("y_val")
            .rolling_mean(
                window_size=f_roll,
                min_samples=1,
            )
            .over(["target", "year"])
            .alias("y_rolling")
        )
    )

    fig = px.scatter(
        data_processed,
        x="week",
        y="y_val",
        color="year",
        facet_col="target",
        facet_col_wrap=2,
        facet_col_spacing=0.05,
        facet_row_spacing=0.15,
        color_discrete_map=yearcolors_map,
    )

    rolling_fig = px.line(
        data_processed,
        x="week",
        y="y_rolling",
        color="year",
        facet_col="target",
        facet_col_wrap=2,
        facet_col_spacing=0.05,
        facet_row_spacing=0.15,
        color_discrete_map=yearcolors_map,
    )

    for trace in rolling_fig.data:
        trace.showlegend = False
        trace.hoverinfo = "skip"
        trace.line.width = 2
        fig.add_trace(trace)

    fig.update_xaxes(showticklabels=True, **scatter_axes_settings)
    fig.update_yaxes(showticklabels=True, **scatter_axes_settings)

    fig.update_layout(
        plot_bgcolor=bgcolor,
        hovermode=False,
        title={
            "text": "Week",
            "x": 0.51,
            "y": 0.1,
            "xanchor": "center",
            "yanchor": "bottom",
            "font": {"size": 16},
        },
        legend={"y": -0.25, **horizontal_legend},
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


def get_all_sites_plot(
    data: pl.DataFrame | dict, virus: str, as_fig: bool = False, as_html: bool = False, **f_args
) -> str | go.Figure:
    """Generate a time-series Plotly figure.

    The function filters data for the requested virus and plots a line per site
    using the selected normalisation method and rolling average.

    Args:
        data (pl.DataFrame | dict): Input dataset with sampling_date, city, target
            and numeric series columns. If provided as a dict, it is converted to a
            DataFrame.
        virus (str): The 'target'/virus value to filter the data by.
        as_fig (bool): If True, return a Plotly figure object.
        as_html (bool): If True, return an HTML string representing the Plotly figure.
            Otherwise return the JSON string.
        **f_args: Optional filter arguments coming from the dashboard UI:
            - method: list[str] with chosen normalisation method (default 'pmmov_normalised')
            - timeseries: list[int | str] with rolling window size (default '1')

    Returns:
        str | go.Figure: JSON or HTML string or Plotly figure object representing
        the Plotly figure depending on the input parameters.

    """

    # check if data is a dict, if so convert it to dataframe
    if isinstance(data, dict):
        data = pl.DataFrame(data)

    # filter args processing and default
    f_method = f_args.get("method", ["pmmov_normalised"])[0]
    f_roll = int(f_args.get("timeseries", ["1"])[0])

    cols_todrop = ["inhabitants", "category"]
    cols_tosort = ["city", "sampling_date"]

    data = (
        data.filter(pl.col("target") == virus)
        .drop(cols_todrop)
        .sort(cols_tosort)
        .with_columns(
            pl.col(f_method)
            .rolling_mean(
                window_size=f_roll,
                min_samples=1,
            )
            .over("city")
            .alias("y_rolling")
        )
    )

    plot_trace = [
        go.Scatter(
            name=city,
            x=group["sampling_date"],
            y=group["y_rolling"],
            mode="lines+markers",
            marker={"color": cities_graph_info[city]["colour"]},
            line={"color": cities_graph_info[city]["colour"]},
        )
        for (city,), group in data.partition_by("city", as_dict=True).items()
    ]

    fig = go.Figure(data=plot_trace)

    fig.update_xaxes(hoverformat="%b %d, %Y (week %V)", **common_axes_settings)
    fig.update_yaxes(showgrid=True, gridcolor=gridcolor, gridwidth=0.8, **common_axes_settings)

    years = data["sampling_date"].str.to_date().dt.year().unique().sort().to_list()
    fig.update_xaxes(range=get_range_date(data["sampling_date"], years[-1]))

    ymax = data.filter(pl.col("sampling_date").str.contains(str(years[-1])))[f_method].max()
    fig.update_yaxes(range=[round(ymax * -0.07, 2), ymax * 1.2])

    annotations, updatemenus = get_timeline_annotation_updatemenus(
        data["sampling_date"],
        years,
        x=0.55,
        y=-0.22,
        resize_yaxis=True,
        ydata=data[f_method],
    )

    fig.update_layout(
        plot_bgcolor=bgcolor,
        hovermode="x unified",
        hoverdistance=1,
        annotations=annotations,
        updatemenus=updatemenus,
        legend={"font": {"size": 10}, "y": 0.95},
        margin=zero_margin,
    )

    if as_fig:
        return fig

    if as_html:
        return fig.to_html(**plotly_to_html_settings)

    return figure_to_json(fig)


def get_single_site_plot(
    data: pl.DataFrame | dict, virus: str, as_fig: bool = False, as_html: bool = False, **f_args
) -> str | go.Figure:
    """Build a single-site timeseries for multiple normalization methods.

    The function filters data for the requested virus, computes rolling
    averages, scales the series for consistent visualization, and returns
    a Plotly figure with multiple traces — one per normalization method.

    Args:
        data (pl.DataFrame | dict): Input dataset; if provided as a dict it will
            be converted to a DataFrame.
        virus (str): The 'target' name to filter the dataset by.
        as_fig (bool): If True, return a Plotly figure object.
        as_html (bool): If True, return an HTML string for the figure. Otherwise
            return a JSON string.
        **f_args: Any: additional filters passed by the UI:
            - timeseries: list[int | str] rolling average window size
            - site: list[str] the site to render

    Returns:
        str | go.Figure: JSON or HTML string or Plotly figure object representing
        the Plotly figure depending on the input parameters.

    """

    # check if data is a dict, if so convert it to dataframe
    if isinstance(data, dict):
        data = pl.DataFrame(data)

    f_roll = int(f_args.get("timeseries", ["1"])[0])
    f_site = f_args.get("site", data["city"].unique().sort().to_list())[0]

    cols_todrop = ["target", "inhabitants", "category"]
    cols_values = ["pmmov_normalised", "copies_day_inhabitant", "copies_l"]
    methods_map = {
        "pmmov_normalised": {
            "name": "PMMoV normalised",
            "scale": 66983,
            "colour": "#4393c3",
        },
        "copies_day_inhabitant": {
            "name": "Flow normalised",
            "scale": 0.003,
            "colour": "#9400d3",
        },
        "copies_l": {"name": "Non normalised", "scale": 1, "colour": "#b691d2"},
    }

    data = (
        data.filter((pl.col("target") == virus) & (pl.col("city") == f_site))
        .drop(cols_todrop)
        .unique()
        .sort("sampling_date")
        .with_columns(
            [pl.col(col).rolling_mean(window_size=f_roll).alias(col) for col in cols_values]
        )
    )

    plot_traces = [
        go.Scatter(
            name=methods_map[vcol]["name"],
            x=data["sampling_date"],
            y=data[vcol] * methods_map[vcol]["scale"],
            mode="lines+markers",
            marker={"color": methods_map[vcol]["colour"]},
            line={"color": methods_map[vcol]["colour"]},
        )
        for vcol in cols_values
    ]

    fig = go.Figure(data=plot_traces)

    fig.update_xaxes(**scatter_axes_settings)
    fig.update_yaxes(showticklabels=False, **scatter_axes_settings)

    years = data["sampling_date"].str.to_date().dt.year().unique().sort().to_list()
    fig.update_xaxes(range=get_range_date(data["sampling_date"], str(years[-1])))

    annotations, updatemenus = get_timeline_annotation_updatemenus(
        data["sampling_date"], years, x=0.5, y=-0.39
    )

    fig.update_layout(
        plot_bgcolor=bgcolor,
        annotations=annotations,
        updatemenus=updatemenus,
        hovermode="x unified",
        legend={**horizontal_legend, "y": -0.22},
        margin=zero_margin,
    )

    if as_fig:
        return fig

    if as_html:
        return fig.to_html(**plotly_to_html_settings)

    return figure_to_json(fig)
