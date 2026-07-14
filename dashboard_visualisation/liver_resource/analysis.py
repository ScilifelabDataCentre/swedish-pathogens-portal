"""Run liver DE analysis and build Plotly output."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from dashboard_visualisation.liver_resource.computation import (
    classify_genes,
    compute_module_ratios,
    get_module_gene_sets,
    map_ratios_to_colours,
)
from dashboard_visualisation.liver_resource.plotly_tln import (
    build_coloured_figure_json,
    build_multi_coloured_figure_json,
)

LEAF_TRACE_INDEX = 2
PlotMode = Literal["solid", "pie"]


@dataclass(frozen=True)
class ComparisonStats:
    """Computed DE projection for one uploaded file."""

    filename: str
    gene_count: int
    up_count: int
    down_count: int
    ratios: dict[int, float | None]
    colours: dict[int, str]


@dataclass(frozen=True)
class LiverAnalysisResult:
    """Computed liver projection for one or more DE files and a cutoff."""

    cutoff: str
    comparisons: tuple[ComparisonStats, ...]
    plot_mode: PlotMode
    figure_json: dict[str, Any]
    leaf_trace_index: int = LEAF_TRACE_INDEX

    @property
    def filename(self) -> str:
        """Return the primary filename or a comma-separated list for multi-file runs."""
        if len(self.comparisons) == 1:
            return self.comparisons[0].filename
        return ", ".join(comparison.filename for comparison in self.comparisons)

    @property
    def gene_count(self) -> int:
        """Return the gene count from the first comparison."""
        return self.comparisons[0].gene_count

    @property
    def up_count(self) -> int:
        """Return the up-regulated gene count from the first comparison."""
        return self.comparisons[0].up_count

    @property
    def down_count(self) -> int:
        """Return the down-regulated gene count from the first comparison."""
        return self.comparisons[0].down_count

    @property
    def ratios(self) -> dict[int, float | None]:
        """Return module ratios from the first comparison."""
        return self.comparisons[0].ratios

    @property
    def colours(self) -> dict[int, str]:
        """Return module colours from the first comparison."""
        return self.comparisons[0].colours


def analyse_de_data(
    de_data: dict[str, Any],
    *,
    filename: str,
    cutoff: str,
) -> LiverAnalysisResult:
    """Classify genes, compute module ratios, and build a coloured TLN figure."""
    return analyse_de_uploads([(filename, de_data)], cutoff=cutoff)


def analyse_de_uploads(
    uploads: list[tuple[str, dict[str, Any]]],
    *,
    cutoff: str,
) -> LiverAnalysisResult:
    """Analyse one or more DE files and build solid or pie TLN output."""
    if not uploads:
        msg = "At least one DE file is required."
        raise ValueError(msg)

    modules = get_module_gene_sets()
    comparisons: list[ComparisonStats] = []
    ratio_rows: list[dict[int, float | None]] = []

    for filename, de_data in uploads:
        classified = classify_genes(de_data, cutoff)
        ratios = compute_module_ratios(de_data["genes"], classified, modules)
        ratio_rows.append(ratios)
        comparisons.append(
            ComparisonStats(
                filename=filename,
                gene_count=len(de_data["genes"]),
                up_count=len(classified["up"]),
                down_count=len(classified["down"]),
                ratios=ratios,
                colours={},
            )
        )

    max_abs = _shared_max_abs(ratio_rows)
    comparisons = tuple(
        ComparisonStats(
            filename=comparison.filename,
            gene_count=comparison.gene_count,
            up_count=comparison.up_count,
            down_count=comparison.down_count,
            ratios=comparison.ratios,
            colours=map_ratios_to_colours(comparison.ratios, max_abs=max_abs),
        )
        for comparison in comparisons
    )

    plot_mode: PlotMode = "pie" if len(comparisons) > 1 else "solid"
    title = _build_title(comparisons)
    if plot_mode == "pie":
        figure_json = build_multi_coloured_figure_json(
            [
                (comparison.filename, comparison.ratios, comparison.colours)
                for comparison in comparisons
            ],
            title=title,
            cutoff=cutoff,
            max_abs=max_abs,
        )
    else:
        figure_json = build_coloured_figure_json(
            comparisons[0].ratios,
            title=title,
            cutoff=cutoff,
            max_abs=max_abs,
        )

    return LiverAnalysisResult(
        cutoff=cutoff,
        comparisons=comparisons,
        plot_mode=plot_mode,
        figure_json=figure_json,
    )


def colours_for_plotly_restyle(colours: dict[int, str]) -> list[str]:
    """Return leaf marker colours ordered by module id for Plotly.restyle()."""
    return [colours[module_id] for module_id in sorted(colours)]


def _shared_max_abs(ratio_rows: list[dict[int, float | None]]) -> float:
    valid = [
        value
        for ratios in ratio_rows
        for value in ratios.values()
        if value is not None
    ]
    if not valid:
        return 1.0
    return max(abs(value) for value in valid) or 1.0


def _build_title(comparisons: tuple[ComparisonStats, ...]) -> str:
    if len(comparisons) == 1:
        return f"DINA Liver TLN — {comparisons[0].filename}"
    return f"DINA Liver TLN — {len(comparisons)} comparisons"
