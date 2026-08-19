"""Helper functions for the SLU WW dashboard visualisation."""

from datetime import timedelta

import polars as pl


def get_range_date(all_dates: pl.Series, year: int | str, format: str = "%Y-%m-%d") -> list:
    """Return min and max date from the series for a given year in the required format.

    Args:
        all_dates: Series-like of date strings in the provided `format`.
        year: Year value (int or str) for which to compute the range.
        format: Date string format used to parse dates in all_dates.

    Returns:
        Two-element list with min and max dates as strings in `format`.

    """

    if all_dates.dtype == pl.String:
        all_dates = all_dates.str.to_datetime()
    filtered_dates = all_dates.filter(all_dates.dt.year() == int(year))
    min_date = filtered_dates.min() - timedelta(days=3)
    max_date = filtered_dates.max() + timedelta(days=3)

    return [min_date.strftime(format), max_date.strftime(format)]


def get_timeline_annotation_updatemenus(
    timeline: pl.Series,
    years: list,
    x: float = 0.53,
    y: float = -0.2,
    resize_yaxis: bool = False,
    ydata: pl.Series = None,
) -> tuple:
    """Create annotations and updatemenus for a Plotly timeline selector.

    Args:
        timeline: Series of sampling_date strings.
        years: List with year values to create buttons for.
        x: X position for the annotation/updatemenu in paper coordinates.
        y: Y position for the annotation/updatemenu in paper coordinates.
        resize_yaxis: If True, the y-axis will be resized for each button.
        ydata: Optional series used to compute y-axis range when resize_yaxis is True.

    Returns:
        A tuple (annotations, updatemenus) where each element is a list for Plotly layout.

    """
    if timeline.dtype == pl.String:
        timeline = timeline.str.to_datetime()

    annotations = []

    updatemenus = [
        {
            "type": "buttons",
            "direction": "left",
            "active": len(years),
            "x": x,
            "xanchor": "center",
            "y": y,
            "yanchor": "bottom",
            "pad": {"b": 5},
            "buttons": [
                {"label": "All", "method": "relayout", "args": [{"xaxis.autorange": True}]}
            ],
        }
    ]

    if resize_yaxis:
        updatemenus[0]["buttons"][0]["args"][0]["yaxis.autorange"] = True

    for y in years:
        button = {
            "label": y,
            "method": "relayout",
            "args": [{"xaxis.range": get_range_date(timeline, y)}],
        }
        if resize_yaxis and ydata is not None:
            ymax = ydata.filter(timeline.dt.year() == y).max()
            button["args"][0]["yaxis.range"] = [round(ymax * -0.07, 2), ymax * 1.2]
        updatemenus[0]["buttons"].append(button)

    return (annotations, updatemenus)
