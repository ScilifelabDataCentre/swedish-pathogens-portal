"""Generate interactive map with SLU wastewater treatment plants using Plotly."""

import json
from pathlib import Path

import plotly.graph_objects as go
import polars as pl

from ..utils.plotly import figure_to_json
from .constants import plotly_to_html_settings

# Colours and font for the map
map_colour = "#e4fae4"
map_border_colour = "#98eb98"
ww_plant_colour = "#37ae94"
hover_bg_colour = "#ffffff"
hover_border_colour = "#000000"
font_family = "IBM Plex Sans"

# Combined Stockholm sites for hover text
combined_stockholm_text = "Stockholm (Bromma, Grödinge, Hendriksdal and Käppala)"

# File paths for the map data
script_dir = Path(__file__).resolve().parent
ww_plant_info_file = script_dir / "map_data" / "ww_plants_locations.csv"
sweden_geojson_file = script_dir / "map_data" / "sweden-counties.geojson"


def get_ww_plants_map_plot(
    data: pl.DataFrame | dict, as_fig: bool = False, as_html: bool = False
) -> str | go.Figure:
    """Generate interactive map with SLU wastewater treatment plants using Plotly."""

    # check if data is a dict, if so convert it to dataframe
    if isinstance(data, dict):
        data = pl.DataFrame(data)

    # Read map data and wastewater treatment plant locations
    ww_plant_info = pl.read_csv(ww_plant_info_file, separator=",", has_header=True)
    with sweden_geojson_file.open("r") as j:
        sweden_geo_data = json.load(j)

    # Get population and site name for each wastewater treatment plant
    data = data.select(["city", "inhabitants"]).unique().sort("city")
    population_data = (
        data.with_columns(
            pl.when(pl.col("city").str.starts_with("Stockholm-"))
            .then(pl.lit("Stockholm"))
            .otherwise(pl.col("city"))
            .alias("plant")
        )
        .group_by("plant")
        .agg(pl.col("inhabitants").sum())
        .with_columns(
            pl.when(pl.col("plant") == "Stockholm")
            .then(pl.lit(combined_stockholm_text))
            .otherwise(pl.col("plant"))
            .alias("hover_name")
        )
    )
    ww_plant_info = ww_plant_info.join(population_data, on="plant", how="left")

    loc_ids = []
    for feature in sweden_geo_data["features"]:
        feature["id"] = feature["properties"]["cartodb_id"]
        loc_ids.append(feature["id"])

    # Draw the Sweden map with the counties
    fig = go.Figure(
        go.Choropleth(
            geojson=sweden_geo_data,
            locations=loc_ids,
            z=[1] * len(loc_ids),
            featureidkey="id",
            marker={"line": {"color": map_border_colour, "width": 0.5}},
            colorscale=[[0, map_colour], [1, map_colour]],
            showscale=False,
            hoverinfo="skip",
        )
    )

    # Add the wastewater treatment plants as scatter points on the map
    fig.add_traces(
        data=go.Scattergeo(
            lon=ww_plant_info["longitude"],
            lat=ww_plant_info["latitude"],
            mode="markers",
            marker={
                "color": ww_plant_colour,
                "size": 10,
                "line": {"color": ww_plant_colour, "width": 2},
            },
            customdata=ww_plant_info,
            hovertemplate=(
                "<b>Site:</b> %{customdata[4]}<br>"
                "<b>Inhabitants:</b> %{customdata[3]}<extra></extra>"
            ),
            hoverlabel={
                "bgcolor": hover_bg_colour,
                "bordercolor": hover_border_colour,
                "font": {"color": "black", "size": 14, "family": font_family},
            },
        )
    )

    # Update the layout of the map
    fig.update_layout(
        title={
            "text": "<span style='font-weight: 500;'>Sample collection sites</span>",
            "x": 0.5,
            "xanchor": "center",
            "font": {"size": 16, "family": font_family},
        },
        geo={
            "lonaxis_range": [20, 90],
            "lataxis_range": [48, 100],
            "projection_scale": 4.3,
            "center": {"lat": 62, "lon": 18},
            "visible": False,
            "scope": "europe",
        },
        margin={"r": 0, "t": 60, "l": 0, "b": 0},
        font={"size": 16, "family": font_family},
        dragmode=False,
        autosize=True,
    )

    if as_fig:
        return fig

    if as_html:
        return fig.to_html(**plotly_to_html_settings)

    return figure_to_json(fig)
