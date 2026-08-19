"""CSV export builders for liver DE analysis results."""

from __future__ import annotations

import csv
import io
from typing import Any

from dashboard_visualisation.liver_resource.computation import classify_genes, compute_module_ratios
from dashboard_visualisation.liver_resource.reference_data import (
    EXPECTED_MODULE_COUNT,
    load_modules,
    load_symbol_map,
)


def build_module_scores_csv(de_data: dict[str, Any], cutoff: str) -> str:
    """Build module scores CSV matching R ``*_module_scores.csv`` format."""
    classified = classify_genes(de_data, cutoff)
    modules = {module_id: set(genes) for module_id, genes in load_modules().items()}
    ratios = compute_module_ratios(de_data["genes"], classified, modules)
    module_gene_counts = load_modules()

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
                cutoff,
            ]
        )

    return buffer.getvalue()


def build_genes_csv(de_data: dict[str, Any], cutoff: str) -> str:
    """Build gene classification CSV matching R ``*_genes.csv`` format."""
    classified = classify_genes(de_data, cutoff)
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
