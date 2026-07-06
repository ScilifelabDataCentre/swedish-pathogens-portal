"""Build Plotly figures for the DINA Liver Tree-Leaf Network."""

from __future__ import annotations

import math
from functools import lru_cache
from typing import Any

import plotly.graph_objects as go

from dashboard_visualisation.liver_resource.computation import R_PALETTE, map_ratios_to_colours
from dashboard_visualisation.liver_resource.reference_data import (
    load_cyjs_layout,
    load_tln_graph,
)
from dashboard_visualisation.utils.plotly import figure_to_json

ComparisonRow = tuple[str, dict[int, float | None], dict[int, str]]

BASE_LEAF_COLOUR = "lightskyblue"
DEFAULT_FIGURE_HEIGHT = 800
DEFAULT_FIGURE_WIDTH = 900
DEFAULT_PLOT_HEIGHT_PX = 700


@lru_cache(maxsize=1)
def get_normalised_layout() -> dict[str, tuple[float, float]]:
    """Return cyjs node positions normalised to [-1, 1] with R y-axis convention."""
    return _normalise_layout(load_cyjs_layout())


def build_base_figure() -> go.Figure:
    """Build the neutral TLN shown before a visitor uploads DE data."""
    graph = load_tln_graph()
    layout = get_normalised_layout()
    return _build_figure(
        graph=graph,
        layout=layout,
        leaf_colours={},
        leaf_ratios={},
        title="DINA Liver TLN — Upload a DE file to colour modules",
        show_colorbar=False,
    )


def build_coloured_figure(
    ratios: dict[int, float | None],
    *,
    title: str = "DINA Liver TLN",
    cutoff: str = "standard",
    max_abs: float | None = None,
) -> go.Figure:
    """Build a TLN figure with module leaves coloured by DE ratios."""
    graph = load_tln_graph()
    layout = get_normalised_layout()
    colours = map_ratios_to_colours(ratios, max_abs=max_abs)
    leaf_colours = {str(module_id): colour for module_id, colour in colours.items()}
    leaf_ratios = {
        str(module_id): (ratio if ratio is not None else 0.0)
        for module_id, ratio in ratios.items()
    }
    display_title = f"{title} ({cutoff} cutoff)" if cutoff else title
    if max_abs is None:
        valid_ratios = [value for value in ratios.values() if value is not None]
        max_abs = max((abs(value) for value in valid_ratios), default=1.0)
    return _build_figure(
        graph=graph,
        layout=layout,
        leaf_colours=leaf_colours,
        leaf_ratios=leaf_ratios,
        title=display_title,
        show_colorbar=True,
        max_abs=max_abs,
    )


def build_multi_coloured_figure(
    comparisons: list[ComparisonRow],
    *,
    title: str = "DINA Liver TLN",
    cutoff: str = "standard",
    max_abs: float | None = None,
) -> go.Figure:
    """Build a TLN figure with pie-chart leaves for multiple DE comparisons."""
    graph = load_tln_graph()
    layout = get_normalised_layout()
    display_title = f"{title} ({cutoff} cutoff)" if cutoff else title
    if max_abs is None:
        max_abs = _max_abs_from_comparisons(comparisons)
    return _build_multi_figure(
        graph=graph,
        layout=layout,
        comparisons=comparisons,
        title=display_title,
        max_abs=max_abs,
    )


def build_base_figure_json() -> dict[str, Any]:
    """Return JSON-safe Plotly figure for the base TLN view."""
    return figure_to_json(build_base_figure())


def build_coloured_figure_json(
    ratios: dict[int, float | None],
    *,
    title: str = "DINA Liver TLN",
    cutoff: str = "standard",
    max_abs: float | None = None,
) -> dict[str, Any]:
    """Return JSON-safe Plotly figure for a coloured TLN view."""
    return figure_to_json(
        build_coloured_figure(ratios, title=title, cutoff=cutoff, max_abs=max_abs)
    )


def build_multi_coloured_figure_json(
    comparisons: list[ComparisonRow],
    *,
    title: str = "DINA Liver TLN",
    cutoff: str = "standard",
    max_abs: float | None = None,
) -> dict[str, Any]:
    """Return JSON-safe Plotly figure for a multi-comparison pie TLN view."""
    return figure_to_json(
        build_multi_coloured_figure(
            comparisons,
            title=title,
            cutoff=cutoff,
            max_abs=max_abs,
        )
    )


def clear_plotly_layout_cache() -> None:
    """Clear cached layout data (for tests)."""
    get_normalised_layout.cache_clear()


def _normalise_layout(
    positions: dict[str, tuple[float, float]],
) -> dict[str, tuple[float, float]]:
    """Normalise x/y to [-1, 1] with aspect ratio correction. Negate y (R convention)."""
    xs = [point[0] for point in positions.values()]
    ys = [point[1] for point in positions.values()]
    x_range = max(xs) - min(xs)
    y_range = max(ys) - min(ys)

    scale_x, scale_y = 1.0, 1.0
    if x_range > y_range:
        scale_y = y_range / x_range

    normalised: dict[str, tuple[float, float]] = {}
    for name, (x_value, y_value) in positions.items():
        nx = ((x_value - min(xs)) / x_range * 2 - 1) * scale_x
        ny = -((y_value - min(ys)) / y_range * 2 - 1) * scale_y
        normalised[name] = (nx, ny)
    return normalised


def _build_figure(
    *,
    graph: dict[str, Any],
    layout: dict[str, tuple[float, float]],
    leaf_colours: dict[str, str],
    leaf_ratios: dict[str, float],
    title: str,
    show_colorbar: bool,
    max_abs: float = 1.0,
) -> go.Figure:
    vertices = graph["vertices"]
    edges = graph["edges"]
    vertex_by_name = {vertex["name"]: vertex for vertex in vertices}

    degree = {vertex["name"]: 0 for vertex in vertices}
    for edge in edges:
        degree[edge["source"]] += 1
        degree[edge["target"]] += 1

    leaves = {name for name, value in degree.items() if value == 1}
    internal = {name for name, value in degree.items() if value > 1}

    edge_trace = _build_edge_trace(edges, layout)
    internal_trace = _build_internal_trace(internal, layout)
    leaf_trace = _build_leaf_trace(
        leaves=leaves,
        layout=layout,
        vertex_by_name=vertex_by_name,
        leaf_colours=leaf_colours,
        leaf_ratios=leaf_ratios,
        base_view=not show_colorbar,
    )

    traces: list[go.Scatter] = [edge_trace, internal_trace, leaf_trace]
    if show_colorbar:
        traces.append(_build_colorbar_trace(max_abs))

    figure = go.Figure(
        data=traces,
        layout=go.Layout(
            title={"text": title, "x": 0.5},
            xaxis={
                "showgrid": False,
                "zeroline": False,
                "showticklabels": False,
                "scaleanchor": "y",
            },
            yaxis={"showgrid": False, "zeroline": False, "showticklabels": False},
            plot_bgcolor="white",
            hovermode="closest",
            dragmode="pan",
            clickmode="event",
            width=DEFAULT_FIGURE_WIDTH,
            height=DEFAULT_FIGURE_HEIGHT,
            margin={"l": 20, "r": 20, "t": 50, "b": 20},
        ),
    )
    return figure


def _build_multi_figure(
    *,
    graph: dict[str, Any],
    layout: dict[str, tuple[float, float]],
    comparisons: list[ComparisonRow],
    title: str,
    max_abs: float,
) -> go.Figure:
    vertices = graph["vertices"]
    edges = graph["edges"]
    vertex_by_name = {vertex["name"]: vertex for vertex in vertices}

    degree = {vertex["name"]: 0 for vertex in vertices}
    for edge in edges:
        degree[edge["source"]] += 1
        degree[edge["target"]] += 1

    leaves = {name for name, value in degree.items() if value == 1}
    internal = {name for name, value in degree.items() if value > 1}

    edge_trace = _build_edge_trace(edges, layout)
    internal_trace = _build_internal_trace(internal, layout)
    leaf_trace, label_trace, pie_shapes = _build_pie_leaf_layers(
        leaves=leaves,
        layout=layout,
        vertex_by_name=vertex_by_name,
        comparisons=comparisons,
    )

    traces: list[go.Scatter] = [edge_trace, internal_trace, leaf_trace, label_trace]
    traces.append(_build_colorbar_trace(max_abs))

    figure = go.Figure(
        data=traces,
        layout=go.Layout(
            title={"text": title, "x": 0.5},
            xaxis={
                "showgrid": False,
                "zeroline": False,
                "showticklabels": False,
                "scaleanchor": "y",
            },
            yaxis={"showgrid": False, "zeroline": False, "showticklabels": False},
            plot_bgcolor="white",
            hovermode="closest",
            dragmode="pan",
            clickmode="event",
            width=DEFAULT_FIGURE_WIDTH,
            height=DEFAULT_FIGURE_HEIGHT,
            margin={"l": 20, "r": 20, "t": 50, "b": 20},
            shapes=pie_shapes,
        ),
    )
    return figure


def _build_edge_trace(
    edges: list[dict[str, Any]],
    layout: dict[str, tuple[float, float]],
) -> go.Scatter:
    edge_x: list[float | None] = []
    edge_y: list[float | None] = []
    for edge in edges:
        source, target = edge["source"], edge["target"]
        if source in layout and target in layout:
            x0, y0 = layout[source]
            x1, y1 = layout[target]
            edge_x.extend([x0, x1, None])
            edge_y.extend([y0, y1, None])

    return go.Scatter(
        x=edge_x,
        y=edge_y,
        mode="lines",
        line={"width": 1.5, "color": "rgba(150,150,150,0.5)"},
        hoverinfo="none",
        showlegend=False,
    )


def _build_internal_trace(
    internal: set[str],
    layout: dict[str, tuple[float, float]],
) -> go.Scatter:
    return go.Scatter(
        x=[layout[name][0] for name in internal if name in layout],
        y=[layout[name][1] for name in internal if name in layout],
        mode="markers",
        marker={"size": 3, "color": "rgba(200,200,200,0.3)"},
        hoverinfo="none",
        showlegend=False,
    )


def _build_leaf_trace(
    *,
    leaves: set[str],
    layout: dict[str, tuple[float, float]],
    vertex_by_name: dict[str, dict[str, Any]],
    leaf_colours: dict[str, str],
    leaf_ratios: dict[str, float],
    base_view: bool,
) -> go.Scatter:
    leaf_x: list[float] = []
    leaf_y: list[float] = []
    marker_colours: list[str] = []
    marker_sizes: list[float] = []
    labels: list[str] = []
    hovers: list[str] = []
    customdata: list[str] = []

    for name in sorted(leaves, key=lambda value: int(value)):
        if name not in layout:
            continue
        vertex = vertex_by_name[name]
        x_value, y_value = layout[name]
        gene_count = vertex["size"]
        ratio = leaf_ratios.get(name, 0.0)
        colour = leaf_colours.get(name, BASE_LEAF_COLOUR)

        leaf_x.append(x_value)
        leaf_y.append(y_value)
        marker_colours.append(colour)
        marker_sizes.append(max(8.0, math.sqrt(gene_count) * 2.5))
        labels.append(str(name))
        customdata.append(name)
        if base_view:
            hovers.append(
                f"<b>Module {name}</b><br>"
                f"Genes: {gene_count}<br>"
                "<i>Upload DE file to see ratios</i>"
            )
        else:
            hovers.append(
                f"<b>Module {name}</b><br>Genes: {gene_count}<br>DE ratio: {ratio:+.4f}"
            )

    return go.Scatter(
        x=leaf_x,
        y=leaf_y,
        mode="markers+text",
        marker={
            "size": marker_sizes,
            "color": marker_colours,
            "line": {"width": 1, "color": "gray"},
            "sizemode": "diameter",
        },
        text=labels,
        textposition="middle center",
        textfont={"size": 7, "color": "black"},
        hovertext=hovers,
        hoverinfo="text",
        customdata=customdata,
        showlegend=False,
    )


def _build_colorbar_trace(max_abs: float) -> go.Scatter:
    return go.Scatter(
        x=[None],
        y=[None],
        mode="markers",
        marker={
            "colorscale": [
                [0, R_PALETTE[0]],
                [0.167, R_PALETTE[1]],
                [0.333, R_PALETTE[2]],
                [0.5, R_PALETTE[3]],
                [0.667, R_PALETTE[4]],
                [0.833, R_PALETTE[5]],
                [1.0, R_PALETTE[6]],
            ],
            "cmin": -max_abs,
            "cmax": max_abs,
            "colorbar": {
                "title": {"text": "DE Ratio", "side": "right"},
                "thickness": 15,
                "len": 0.6,
            },
            "showscale": True,
        },
        hoverinfo="none",
        showlegend=False,
    )


def _build_pie_leaf_layers(
    *,
    leaves: set[str],
    layout: dict[str, tuple[float, float]],
    vertex_by_name: dict[str, dict[str, Any]],
    comparisons: list[ComparisonRow],
) -> tuple[go.Scatter, go.Scatter, list[dict[str, Any]]]:
    """Build invisible click targets, module labels, and pie wedge shapes."""
    slice_count = len(comparisons)
    leaf_x: list[float] = []
    leaf_y: list[float] = []
    marker_sizes: list[float] = []
    hovers: list[str] = []
    customdata: list[str] = []
    label_x: list[float] = []
    label_y: list[float] = []
    labels: list[str] = []
    shapes: list[dict[str, Any]] = []

    for name in sorted(leaves, key=lambda value: int(value)):
        if name not in layout:
            continue

        vertex = vertex_by_name[name]
        x_value, y_value = layout[name]
        gene_count = vertex["size"]
        module_id = int(name)
        radius = _marker_radius_data(gene_count)

        leaf_x.append(x_value)
        leaf_y.append(y_value)
        marker_sizes.append(max(8.0, math.sqrt(gene_count) * 2.5))
        customdata.append(name)
        label_x.append(x_value)
        label_y.append(y_value)
        labels.append(str(name))

        hover_lines = [f"<b>Module {name}</b>", f"Genes: {gene_count}"]
        for filename, ratios, colours in comparisons:
            ratio = ratios.get(module_id)
            ratio_text = "—" if ratio is None else f"{ratio:+.4f}"
            hover_lines.append(f"{filename}: {ratio_text}")
        hovers.append("<br>".join(hover_lines))

        for slice_index, (_, _, colours) in enumerate(comparisons):
            start_angle = -math.pi / 2 + (2 * math.pi * slice_index / slice_count)
            end_angle = -math.pi / 2 + (2 * math.pi * (slice_index + 1) / slice_count)
            colour = colours.get(module_id, "#ffffff")
            shapes.append(
                {
                    "type": "path",
                    "path": _build_pie_wedge_path(
                        x_value,
                        y_value,
                        radius,
                        start_angle,
                        end_angle,
                    ),
                    "xref": "x",
                    "yref": "y",
                    "fillcolor": colour,
                    "line": {"color": "#333333", "width": 0.5},
                    "layer": "below",
                }
            )

    click_trace = go.Scatter(
        x=leaf_x,
        y=leaf_y,
        mode="markers",
        marker={
            "size": marker_sizes,
            "color": ["rgba(0,0,0,0)"] * len(leaf_x),
            "line": {"width": 0},
            "sizemode": "diameter",
        },
        hovertext=hovers,
        hoverinfo="text",
        customdata=customdata,
        showlegend=False,
    )
    label_trace = go.Scatter(
        x=label_x,
        y=label_y,
        mode="text",
        text=labels,
        textposition="middle center",
        textfont={"size": 7, "color": "black"},
        hoverinfo="none",
        showlegend=False,
    )
    return click_trace, label_trace, shapes


def _build_pie_wedge_path(
    center_x: float,
    center_y: float,
    radius: float,
    start_angle: float,
    end_angle: float,
    segments: int = 24,
) -> str:
    """Return an SVG path for one equal pie slice in data coordinates."""
    path = f"M {center_x},{center_y}"
    for step in range(segments + 1):
        angle = start_angle + (end_angle - start_angle) * step / segments
        x_value = center_x + radius * math.cos(angle)
        y_value = center_y + radius * math.sin(angle)
        path += f" L {x_value},{y_value}"
    path += " Z"
    return path


def _marker_radius_data(gene_count: int, *, x_span: float = 2.0) -> float:
    """Convert leaf marker diameter (px) to data-coordinate radius."""
    diameter_px = max(8.0, math.sqrt(gene_count) * 2.5)
    return (diameter_px / 2) / (DEFAULT_FIGURE_WIDTH / x_span)


def _max_abs_from_comparisons(comparisons: list[ComparisonRow]) -> float:
    valid = [
        value
        for _, ratios, _ in comparisons
        for value in ratios.values()
        if value is not None
    ]
    if not valid:
        return 1.0
    return max(abs(value) for value in valid) or 1.0


def count_leaf_markers(figure_json: dict[str, Any]) -> int:
    """Return the number of leaf markers in a serialised TLN figure."""
    for trace in figure_json.get("data", []):
        customdata = trace.get("customdata")
        if customdata:
            return len(customdata)
    return 0
