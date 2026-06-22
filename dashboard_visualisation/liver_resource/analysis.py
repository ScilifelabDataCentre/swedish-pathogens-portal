"""Run liver DE analysis and build Plotly output."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dashboard_visualisation.liver_resource.computation import (
    classify_genes,
    compute_module_ratios,
    get_module_gene_sets,
    map_ratios_to_colours,
)
from dashboard_visualisation.liver_resource.plotly_tln import build_coloured_figure_json

LEAF_TRACE_INDEX = 2


@dataclass(frozen=True)
class LiverAnalysisResult:
    """Computed liver projection for one DE file and cutoff."""

    filename: str
    cutoff: str
    gene_count: int
    up_count: int
    down_count: int
    ratios: dict[int, float | None]
    colours: dict[int, str]
    figure_json: dict[str, Any]
    leaf_trace_index: int = LEAF_TRACE_INDEX


def analyse_de_data(
    de_data: dict[str, Any],
    *,
    filename: str,
    cutoff: str,
) -> LiverAnalysisResult:
    """Classify genes, compute module ratios, and build a coloured TLN figure."""
    classified = classify_genes(de_data, cutoff)
    modules = get_module_gene_sets()
    ratios = compute_module_ratios(de_data["genes"], classified, modules)
    colours = map_ratios_to_colours(ratios)
    figure_json = build_coloured_figure_json(
        ratios,
        title=f"DINA Liver TLN — {filename}",
        cutoff=cutoff,
    )

    return LiverAnalysisResult(
        filename=filename,
        cutoff=cutoff,
        gene_count=len(de_data["genes"]),
        up_count=len(classified["up"]),
        down_count=len(classified["down"]),
        ratios=ratios,
        colours=colours,
        figure_json=figure_json,
    )


def colours_for_plotly_restyle(colours: dict[int, str]) -> list[str]:
    """Return leaf marker colours ordered by module id for Plotly.restyle()."""
    return [colours[module_id] for module_id in sorted(colours)]
