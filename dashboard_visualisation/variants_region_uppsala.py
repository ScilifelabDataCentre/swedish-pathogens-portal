"""SARS-CoV-2 variants (Region Uppsala) visualisation code.

Ports the ClinMicro lineage plotting scripts to Polars. Expects the cleaned
CSV historically published as ``lineage-cleaned-data.csv`` on blobserver
(not the offline raw strain file). Cleaning remains a manual offline step.

Figure IDs (Wagtail ``plotly_figure`` / ``DashboardData.data`` keys):

* ``lineage_six_recent`` — granular Pango since Oct 2023
  (legacy blob ``lineage_six_recent.json``)
* ``lineage_four_recent`` — mid-granularity Pango since Jan 2023
  (legacy blob ``lineage_four_recent.json``)
* ``lineage_wholetime`` — WHO / Pango full timeline
  (legacy blob ``lineage_one_wholetime.json``)
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import plotly.express as px
import plotly.graph_objects as go
import polars as pl

from .utils.plotly import figure_to_json
from .utils.uploads import SourceFile, read_csv_dataframe

REQUIRED_COLUMNS = frozenset(
    {
        "Year-Week",
        "lineage_groups01",
        "lineage_groups04",
        "lineage_groups06",
        "percentage_lineage1",
        "percentage_lineage4",
        "percentage_lineage6",
    }
)

# Legacy colour palettes from ClinMicro plotting scripts.
COLOURS_SIX = [
    "#FCD12A",
    "#784B84",
    "#FF2400",
    "#1E90FF",
    "#D5B85A",
    "#81007F",
    "#CD5C5C",
    "#79BAEC",
    "#CC7722",
    "#DE73FF",
    "#421310",
    "#87AFC7",
    "#EFFD5F",
    "#7852A9",
    "#BF0A30",
    "#FFF200",
    "#151B54",
    "#D30000",
    "#B200ED",
    "#8D021F",
    "#0000FF",
    "#bf02af",
    "#0221bf",
    "#f7f302",
    "#030303",
    "#5c5c5b",
    "#5b5c5c",
    "#5602f2",
]

COLOURS_FOUR = [
    "#FCD12A",
    "#784B84",
    "#FF2400",
    "#1E90FF",
    "#D5B85A",
    "#81007F",
    "#CD5C5C",
    "#79BAEC",
    "#CC7722",
    "#DE73FF",
    "#421310",
    "#87AFC7",
    "#EFFD5F",
    "#7852A9",
    "#BF0A30",
    "#D30000",
    "#151B54",
    "#FFF200",
    "#B200ED",
    "#8D021F",
    "#0000FF",
]

COLOURS_ONE = [
    "#D30000",
    "#151B54",
    "#FFF200",
    "#B200ED",
    "#8D021F",
    "#0000FF",
    "#FCD12A",
    "#784B84",
    "#FF2400",
    "#1E90FF",
    "#D5B85A",
    "#81007F",
    "#CD5C5C",
    "#79BAEC",
    "#CC7722",
    "#DE73FF",
    "#421310",
    "#87AFC7",
    "#EFFD5F",
    "#7852A9",
    "#BF0A30",
]

# Known lineage sort ranks from legacy scripts; unknowns use a high default.
SORT_SIX: dict[str, int] = {
    "KP.3.1.1*": 1,
    "KP.* Other": 2,
    "Non KP JN.1*": 3,
    "JN.2*": 4,
    "BA.2.86* and JN* Other": 5,
    "XBB*": 6,
    "XEC": 7,
    "Omicron Other": 8,
}

SORT_FOUR: dict[str, int] = {
    "BA.1": 1,
    "BA.2": 2,
    "CH": 3,
    "DV.7.1": 4,
    "BA.2.75 Other": 5,
    "BA.2.86/Pirola": 6,
    "BA.4": 7,
    "BA.5": 8,
    "BQ": 9,
    "XBB.1.5": 10,
    "XBB.1.9.1": 11,
    "XBB.1.9.2": 12,
    "EG.5/Eris": 13,
    "XBB.1.16": 14,
    "XBB.2.3": 15,
    "XBB Other": 16,
    "Omicron Other": 17,
}

_UNKNOWN_SORT_RANK = 999


def _add_week_start_dates(df: pl.DataFrame) -> pl.DataFrame:
    """Add Monday-of-ISO-week ``date`` from ``Year-Week`` (``YYYY-WW``)."""
    return (
        df.with_columns(
            pl.col("Year-Week").str.slice(0, 4).cast(pl.Int32).alias("_year"),
            pl.col("Year-Week").str.split("-").list.get(1).cast(pl.Int32).alias("_week_no"),
        )
        .with_columns(
            pl.struct(["_year", "_week_no"])
            .map_elements(
                lambda row: date.fromisocalendar(row["_year"], row["_week_no"], 1),
                return_dtype=pl.Date,
            )
            .alias("date")
        )
        .drop(["_year", "_week_no"])
    )


def _colour_map(ordered_lineages: list[str], colours: list[str]) -> dict[str, str]:
    """Map lineages to colours in display order, cycling if needed."""
    return {name: colours[index % len(colours)] for index, name in enumerate(ordered_lineages)}


def _prepare_lineage_frame(
    df: pl.DataFrame,
    *,
    lineage_col: str,
    percentage_col: str,
    sort_map: dict[str, int] | None,
    sort_ascending: bool,
    after_date: date | None,
) -> pl.DataFrame:
    """Filter, sort, and select columns needed for one area chart."""
    prepared = _add_week_start_dates(df)
    if after_date is not None:
        prepared = prepared.filter(pl.col("date") > after_date)

    if prepared.is_empty():
        raise ValueError(
            f"No rows left after filtering for {lineage_col}"
            + (f" after {after_date.isoformat()}" if after_date else "")
        )

    if sort_map is not None:
        prepared = prepared.with_columns(
            pl.col(lineage_col)
            .replace_strict(sort_map, default=_UNKNOWN_SORT_RANK)
            .alias("_sort_lineages")
        ).sort("_sort_lineages")
    else:
        prepared = prepared.sort(lineage_col, descending=not sort_ascending)

    return prepared.select(["date", lineage_col, percentage_col])


def _select_deselect_menu() -> dict[str, Any]:
    """Return Plotly buttons to show or hide all lineage traces."""
    return {
        "buttons": [
            {
                "label": "Select all lineages",
                "method": "update",
                "args": [{"visible": [True]}],
            },
            {
                "label": "Deselect all lineages",
                "method": "update",
                "args": [{"visible": "legendonly"}],
            },
        ],
        "type": "buttons",
        "pad": {"r": 0, "t": 15},
        "showactive": True,
        "x": 0.98,
        "xanchor": "left",
        "y": 1.23,
        "yanchor": "top",
    }


def _window_menu(
    *,
    full_label: str,
    dates: list[date],
    percentages: list[float],
) -> dict[str, Any]:
    """Return Plotly buttons for full date window vs last 16 weeks."""
    min_date = min(dates)
    max_date = max(dates)
    min_pct = min(percentages)
    max_pct = max(percentages)
    return {
        "buttons": [
            {
                "label": full_label,
                "method": "relayout",
                "args": [
                    {
                        "xaxis.range": (min_date, max_date),
                        "yaxis.range": (min_pct, max_pct),
                    }
                ],
            },
            {
                "label": "Last 16 weeks",
                "method": "relayout",
                "args": [
                    {
                        "xaxis.range": (max_date - timedelta(weeks=16), max_date),
                        "yaxis.range": (min_pct, max_pct),
                    }
                ],
            },
        ],
        "type": "buttons",
        "pad": {"r": 0, "t": 15},
        "showactive": True,
        "x": 0,
        "xanchor": "left",
        "y": 1.23,
        "yanchor": "top",
    }


def _area_figure(
    df: pl.DataFrame,
    *,
    lineage_col: str,
    percentage_col: str,
    colours: list[str],
    margin_top: int,
    y_range_max: float,
    legend_traceorder: str,
    window_full_label: str | None,
) -> go.Figure:
    """Build a stacked area chart with legacy layout and updatemenus."""
    ordered = df.get_column(lineage_col).unique(maintain_order=True).to_list()
    color_map = _colour_map(ordered, colours)

    fig = px.area(
        df,
        x="date",
        y=percentage_col,
        color=lineage_col,
        line_group=lineage_col,
        color_discrete_map=color_map,
        hover_data={percentage_col: ":.2f"},
    )
    fig.update_layout(
        title=" ",
        yaxis={
            "title": "<b>Percentage of Lineages<br></b>",
            "ticktext": [" ", "20%", "40%", "60%", "80%", "100%"],
            "tickvals": ["0", "20", "40", "60", "80", "100"],
            "range": [0, y_range_max],
        },
        font={"size": 12},
        autosize=True,
        margin={"r": 0, "t": margin_top, "b": 120, "l": 0},
        legend={
            "yanchor": "top",
            "y": 1.0,
            "xanchor": "left",
            "x": 1.01,
            "font": {"size": 12},
            "title": "<b>Lineage</b><br>",
            "traceorder": legend_traceorder,
        },
        hovermode="x unified",
        xaxis={
            "title": "<b>Date</b>",
            "tickangle": 0,
            "hoverformat": "%b %d, %Y (week %W)",
        },
    )
    fig.update_traces(hovertemplate="%{y:.2f}%")
    for trace in fig.data:
        if hasattr(trace, "line") and trace.line is not None:
            trace.line.width = 0

    updatemenus: list[dict[str, Any]] = [_select_deselect_menu()]
    if window_full_label is not None:
        dates = df.get_column("date").to_list()
        percentages = df.get_column(percentage_col).to_list()
        updatemenus.append(
            _window_menu(
                full_label=window_full_label,
                dates=dates,
                percentages=percentages,
            )
        )
    fig.update_layout(updatemenus=updatemenus)
    return fig


def _lineage_six_recent_fig(df: pl.DataFrame) -> go.Figure:
    """Area chart for lineage_groups06 since October 2023."""
    prepared = _prepare_lineage_frame(
        df,
        lineage_col="lineage_groups06",
        percentage_col="percentage_lineage6",
        sort_map=SORT_SIX,
        sort_ascending=True,
        after_date=date(2023, 10, 1),
    )
    return _area_figure(
        prepared,
        lineage_col="lineage_groups06",
        percentage_col="percentage_lineage6",
        colours=COLOURS_SIX,
        margin_top=180,
        y_range_max=100.1,
        legend_traceorder="normal",
        window_full_label="Data since Oct 2023",
    )


def _lineage_four_recent_fig(df: pl.DataFrame) -> go.Figure:
    """Area chart for lineage_groups04 since January 2023."""
    prepared = _prepare_lineage_frame(
        df,
        lineage_col="lineage_groups04",
        percentage_col="percentage_lineage4",
        sort_map=SORT_FOUR,
        sort_ascending=True,
        after_date=date(2023, 1, 1),
    )
    return _area_figure(
        prepared,
        lineage_col="lineage_groups04",
        percentage_col="percentage_lineage4",
        colours=COLOURS_FOUR,
        margin_top=100,
        y_range_max=100,
        legend_traceorder="normal",
        window_full_label="Data since Jan 2023",
    )


def _lineage_wholetime_fig(df: pl.DataFrame) -> go.Figure:
    """Area chart for lineage_groups01 over the full timeline."""
    prepared = _prepare_lineage_frame(
        df,
        lineage_col="lineage_groups01",
        percentage_col="percentage_lineage1",
        sort_map=None,
        sort_ascending=False,
        after_date=None,
    )
    return _area_figure(
        prepared,
        lineage_col="lineage_groups01",
        percentage_col="percentage_lineage1",
        colours=COLOURS_ONE,
        margin_top=100,
        y_range_max=100,
        legend_traceorder="reversed",
        window_full_label=None,
    )


def validate_source_columns(columns: list[str]) -> str | None:
    """Validate that the uploaded cleaned CSV has the expected columns."""
    missing_columns = REQUIRED_COLUMNS - set(columns)
    if missing_columns:
        return f"Missing columns: {', '.join(sorted(missing_columns))}"
    return None


def generate_figures(source_file: SourceFile) -> dict[str, Any]:
    """Generate Plotly figures for the Region Uppsala variants dashboard."""
    lineage_df = read_csv_dataframe(source_file)
    return {
        "lineage_six_recent": figure_to_json(_lineage_six_recent_fig(lineage_df)),
        "lineage_four_recent": figure_to_json(_lineage_four_recent_fig(lineage_df)),
        "lineage_wholetime": figure_to_json(_lineage_wholetime_fig(lineage_df)),
    }
