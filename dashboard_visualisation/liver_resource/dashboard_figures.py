"""Read and build pre-computed liver TLN figures for ``DashboardData.data``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dashboard_visualisation.liver_resource.analysis import (
    LEAF_TRACE_INDEX,
    ComparisonStats,
    LiverAnalysisResult,
    PlotMode,
)
from dashboard_visualisation.liver_resource.plotly_tln import build_base_figure_json

LIVER_DASHBOARD_SLUG = "liver-resource"


@dataclass(frozen=True)
class StoredExampleFigure:
    """Pre-computed example plot payload from ``DashboardData.data``."""

    figure_json: dict[str, Any]
    plot_mode: PlotMode
    leaf_trace_index: int
    cutoff: str
    comparisons: tuple[ComparisonStats, ...]

    def to_analysis_result(self) -> LiverAnalysisResult:
        """Build a template-friendly analysis result without recomputing the figure."""
        return LiverAnalysisResult(
            cutoff=self.cutoff,
            comparisons=self.comparisons,
            plot_mode=self.plot_mode,
            figure_json=self.figure_json,
            leaf_trace_index=self.leaf_trace_index,
        )


def get_figure_data(dashboard_data: object | None) -> dict[str, Any]:
    """Return the ``data`` JSON dict from a ``DashboardData`` row, or empty."""
    if dashboard_data is None:
        return {}
    data = getattr(dashboard_data, "data", None)
    if not isinstance(data, dict):
        return {}
    return data


def resolve_base_tln_figure(data: dict[str, Any]) -> dict[str, Any]:
    """Return stored base TLN JSON or build from bundled reference data."""
    stored = data.get("base_tln")
    if _is_plotly_figure(stored):
        return stored
    return build_base_figure_json()


def get_stored_example(
    data: dict[str, Any],
    *,
    slug: str,
    cutoff: str,
) -> StoredExampleFigure | None:
    """Return a stored example figure for a sidebar slug and cutoff, if present."""
    examples = data.get("examples")
    if not isinstance(examples, dict):
        return None
    slug_entry = examples.get(slug)
    if not isinstance(slug_entry, dict):
        return None
    cutoff_entry = slug_entry.get(cutoff)
    if not isinstance(cutoff_entry, dict):
        return None
    return _parse_stored_example(cutoff_entry, cutoff=cutoff)


def stored_example_entry_from_analysis(analysis: LiverAnalysisResult) -> dict[str, Any]:
    """Build a JSON-serialisable example entry for ``DashboardData.data``."""
    primary = analysis.comparisons[0]
    return {
        "figure": analysis.figure_json,
        "plot_mode": analysis.plot_mode,
        "leaf_trace_index": analysis.leaf_trace_index,
        "stats": {
            "filename": analysis.filename,
            "gene_count": primary.gene_count,
            "n_up": primary.up_count,
            "n_down": primary.down_count,
            "file_count": len(analysis.comparisons),
            "filenames": [comparison.filename for comparison in analysis.comparisons],
            "cutoff": analysis.cutoff,
        },
    }


def _parse_stored_example(entry: dict[str, Any], *, cutoff: str) -> StoredExampleFigure | None:
    figure = entry.get("figure")
    if not _is_plotly_figure(figure):
        return None

    stats = entry.get("stats")
    if not isinstance(stats, dict):
        return None

    plot_mode = entry.get("plot_mode", "solid")
    if plot_mode not in ("solid", "pie"):
        plot_mode = "solid"

    leaf_trace_index = entry.get("leaf_trace_index", LEAF_TRACE_INDEX)
    filenames = stats.get("filenames")
    if not isinstance(filenames, list) or not filenames:
        filename = stats.get("filename", "uploaded-de.txt")
        filenames = [filename] if filename else ["uploaded-de.txt"]

    file_count = stats.get("file_count", len(filenames))
    display_filenames = filenames[:file_count] if file_count else filenames
    gene_count = stats.get("gene_count", 0)
    up_count = stats.get("n_up", 0)
    down_count = stats.get("n_down", 0)

    if len(display_filenames) == 1:
        comparisons = (
            ComparisonStats(
                filename=display_filenames[0],
                gene_count=gene_count,
                up_count=up_count,
                down_count=down_count,
                ratios={},
                colours={},
            ),
        )
    else:
        comparisons = tuple(
            ComparisonStats(
                filename=filename,
                gene_count=gene_count,
                up_count=up_count,
                down_count=down_count,
                ratios={},
                colours={},
            )
            for filename in display_filenames
        )

    return StoredExampleFigure(
        figure_json=figure,
        plot_mode=plot_mode,
        leaf_trace_index=int(leaf_trace_index),
        cutoff=cutoff,
        comparisons=comparisons,
    )


def _is_plotly_figure(value: object) -> bool:
    return isinstance(value, dict) and "data" in value and "layout" in value
