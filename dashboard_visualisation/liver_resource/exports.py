"""CSV export builders for liver DE analysis results."""

from __future__ import annotations

import csv
import io
from typing import Any

from dashboard_visualisation.liver_resource.computation import classify_genes, compute_module_ratios
from dashboard_visualisation.liver_resource.plot_metric import (
    DEFAULT_PLOT_METRIC,
    PlotMetric,
)
from dashboard_visualisation.liver_resource.reference_data import (
    EXPECTED_MODULE_COUNT,
    load_modules,
    load_symbol_map,
)
from dashboard_visualisation.liver_resource.thresholds import (
    DEFAULT_ADJ_P,
    DEFAULT_LOGFC_FOLD,
    format_threshold_label,
)


def build_module_scores_csv(
    de_data: dict[str, Any],
    *,
    adj_p: float = DEFAULT_ADJ_P,
    logfc_fold: float = DEFAULT_LOGFC_FOLD,
    plot_metric: PlotMetric = DEFAULT_PLOT_METRIC,
    cutoff: str | None = None,
) -> str:
    """Build module scores CSV matching R ``*_module_scores.csv`` format."""
    del cutoff
    classified = classify_genes(de_data, adj_p=adj_p, logfc_fold=logfc_fold)
    modules = {module_id: set(genes) for module_id, genes in load_modules().items()}
    ratios = compute_module_ratios(
        de_data["genes"],
        classified,
        modules,
        plot_metric=plot_metric,
    )
    module_gene_counts = load_modules()
    label = format_threshold_label(adj_p, logfc_fold)

    buffer = io.StringIO()
    writer = csv.writer(buffer, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(["Module", "GeneCount", "DERatio", "DEcutoff"])

    for module_id in range(1, EXPECTED_MODULE_COUNT + 1):
        ratio = ratios.get(module_id)
        ratio_value = 0.0 if ratio is None else round(ratio, 6)
        writer.writerow(
            [
                module_id,
                len(module_gene_counts[module_id]),
                ratio_value,
                label,
            ]
        )

    return buffer.getvalue()


def build_genes_csv(
    de_data: dict[str, Any],
    *,
    adj_p: float = DEFAULT_ADJ_P,
    logfc_fold: float = DEFAULT_LOGFC_FOLD,
    cutoff: str | None = None,
) -> str:
    """Build gene classification CSV (R ``*_genes.csv`` format)."""
    del cutoff
    classified = classify_genes(de_data, adj_p=adj_p, logfc_fold=logfc_fold)
    symbol_map = load_symbol_map()
    gene_module_map = _build_gene_module_map(de_data["genes"])

    buffer = io.StringIO()
    writer = csv.writer(buffer, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(["EnsemblID", "Symbol", "Module", "logFC", "adj.P.Val", "Direction"])

    for gene_id in de_data["genes"]:
        row = de_data["data"].get(gene_id, {})
        if gene_id in classified["up"]:
            direction = "up"
        elif gene_id in classified["down"]:
            direction = "down"
        else:
            direction = "ns"

        log_fc = row.get("logFC")
        adj_pval = row.get("adj.P.Val")
        module_id = gene_module_map.get(gene_id)

        writer.writerow(
            [
                gene_id,
                symbol_map.get(gene_id, ""),
                "" if module_id is None else module_id,
                "" if log_fc is None else round(log_fc, 6),
                "" if adj_pval is None else adj_pval,
                direction,
            ]
        )

    return buffer.getvalue()


def export_basename(filename: str) -> str:
    """Return a filesystem-safe basename without extension for export filenames."""
    stem = filename.rsplit(".", maxsplit=1)[0]
    return stem.replace(" ", "_")


def _build_gene_module_map(genes: list[str]) -> dict[str, int | None]:
    """Map each gene to its module, matching R's last-assignment behaviour."""
    modules = load_modules()
    gene_set = set(genes)
    assignment: dict[str, int | None] = dict.fromkeys(genes, None)

    for module_id in range(1, EXPECTED_MODULE_COUNT + 1):
        for gene_id in modules[module_id]:
            if gene_id in gene_set:
                assignment[gene_id] = module_id

    return assignment
