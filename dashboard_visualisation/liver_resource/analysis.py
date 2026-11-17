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
from dashboard_visualisation.liver_resource.plot_metric import (
    DEFAULT_PLOT_METRIC,
    PlotMetric,
    plot_metric_label,
)
from dashboard_visualisation.liver_resource.plotly_tln import (
    build_coloured_figure_json,
    build_multi_coloured_figure_json,
)
from dashboard_visualisation.liver_resource.thresholds import (
    DEFAULT_ADJ_P,
    DEFAULT_LOGFC_FOLD,
    format_threshold_label,
    threshold_key,
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
    """Computed liver projection for one or more DE files and Option B thresholds."""

    adj_p: float
    logfc_fold: float
    comparisons: tuple[ComparisonStats, ...]
    plot_mode: PlotMode
    figure_json: dict[str, Any]
    plot_metric: PlotMetric = DEFAULT_PLOT_METRIC
    leaf_trace_index: int = LEAF_TRACE_INDEX

    @property
    def cutoff(self) -> str:
        """Human-readable threshold label (plot titles / stats)."""
        return format_threshold_label(self.adj_p, self.logfc_fold)

    @property
    def plot_metric_label(self) -> str:
        """Human-readable Plot dropdown label for stats chrome."""
        return plot_metric_label(self.plot_metric)

    @property
    def threshold_key(self) -> str:
        """Stable key for DashboardData example lookup."""
        return threshold_key(self.adj_p, self.logfc_fold)

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
    adj_p: float = DEFAULT_ADJ_P,
    logfc_fold: float = DEFAULT_LOGFC_FOLD,
    plot_metric: PlotMetric = DEFAULT_PLOT_METRIC,
    cutoff: str | None = None,
) -> LiverAnalysisResult:
    """Classify genes, compute module ratios, and build a coloured TLN figure."""
    del cutoff
    return analyse_de_uploads(
        [(filename, de_data)],
        adj_p=adj_p,
        logfc_fold=logfc_fold,
        plot_metric=plot_metric,
    )


def analyse_de_uploads(
    uploads: list[tuple[str, dict[str, Any]]],
    *,
    adj_p: float = DEFAULT_ADJ_P,
    logfc_fold: float = DEFAULT_LOGFC_FOLD,
    plot_metric: PlotMetric = DEFAULT_PLOT_METRIC,
    cutoff: str | None = None,
) -> LiverAnalysisResult:
    """Analyse one or more DE files and build solid or pie TLN output."""
    del cutoff
    if not uploads:
        msg = "At least one DE file is required."
        raise ValueError(msg)

    modules = get_module_gene_sets()
    comparisons: list[ComparisonStats] = []
    ratio_rows: list[dict[int, float | None]] = []

    for filename, de_data in uploads:
        classified = classify_genes(de_data, adj_p=adj_p, logfc_fold=logfc_fold)
        ratios = compute_module_ratios(
            de_data["genes"],
            classified,
            modules,
            plot_metric=plot_metric,
        )
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

    max_abs = _shared_scale(ratio_rows, plot_metric=plot_metric)
    comparisons = tuple(
        ComparisonStats(
            filename=comparison.filename,
            gene_count=comparison.gene_count,
            up_count=comparison.up_count,
            down_count=comparison.down_count,
            ratios=comparison.ratios,
            colours=map_ratios_to_colours(
                comparison.ratios,
                max_abs=max_abs,
                plot_metric=plot_metric,
            ),
        )
        for comparison in comparisons
    )

    plot_mode: PlotMode = "pie" if len(comparisons) > 1 else "solid"
    title = _build_title(comparisons)
    label = format_threshold_label(adj_p, logfc_fold)
    if plot_mode == "pie":
        figure_json = build_multi_coloured_figure_json(
            [
                (comparison.filename, comparison.ratios, comparison.colours)
                for comparison in comparisons
            ],
            title=title,
            cutoff=label,
            max_abs=max_abs,
            plot_metric=plot_metric,
        )
    else:
        figure_json = build_coloured_figure_json(
            comparisons[0].ratios,
            title=title,
            cutoff=label,
            max_abs=max_abs,
            plot_metric=plot_metric,
        )

    return LiverAnalysisResult(
        adj_p=adj_p,
        logfc_fold=logfc_fold,
        comparisons=comparisons,
        plot_mode=plot_mode,
        figure_json=figure_json,
        plot_metric=plot_metric,
    )


def colours_for_plotly_restyle(colours: dict[int, str]) -> list[str]:
    """Return leaf marker colours ordered by module id for Plotly.restyle()."""
    return [colours[module_id] for module_id in sorted(colours)]


def _shared_scale(
    ratio_rows: list[dict[int, float | None]],
    *,
    plot_metric: PlotMetric,
) -> float:
    valid = [value for ratios in ratio_rows for value in ratios.values() if value is not None]
    if not valid:
        return 1.0
    if plot_metric == "total":
        return max(valid) or 1.0
    return max(abs(value) for value in valid) or 1.0


def _build_title(comparisons: tuple[ComparisonStats, ...]) -> str:
    if len(comparisons) == 1:
        return f"HepaGeNIE TLN — {comparisons[0].filename}"
    return f"HepaGeNIE TLN — {len(comparisons)} comparisons"
