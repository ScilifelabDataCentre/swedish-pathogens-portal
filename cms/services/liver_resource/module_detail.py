"""Build module detail panels for the liver dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from cms.services.liver_resource.computation import classify_genes, compute_module_ratios
from cms.services.liver_resource.reference_data import load_modules, load_symbol_map

MAX_GENES_DISPLAY = 50
Direction = Literal["up", "down", "ns"]


@dataclass(frozen=True)
class ModuleGeneRow:
    """One gene row in a module detail table."""

    ensembl: str
    symbol: str
    log_fc: str
    adj_pval: str
    direction: Direction


@dataclass(frozen=True)
class ModuleDetailResult:
    """Summary and gene table for one TLN module."""

    module_id: int
    cutoff: str
    module_gene_count: int
    overlap_count: int
    up_count: int
    down_count: int
    de_ratio: float
    genes: tuple[ModuleGeneRow, ...]
    hidden_gene_count: int


def build_module_detail(
    de_data: dict[str, Any],
    *,
    module_id: int,
    cutoff: str,
) -> ModuleDetailResult | None:
    """Return module detail for a valid module id, or None when module is unknown."""
    modules = load_modules()
    module_genes = modules.get(module_id)
    if module_genes is None:
        return None

    module_gene_set = set(module_genes)
    classified = classify_genes(de_data, cutoff)
    genes_in_file = set(de_data["genes"]) & module_gene_set

    symbol_map = load_symbol_map()
    gene_rows: list[ModuleGeneRow] = []
    for gene_id in sorted(genes_in_file):
        row = de_data["data"].get(gene_id, {})
        if gene_id in classified["up"]:
            direction: Direction = "up"
        elif gene_id in classified["down"]:
            direction = "down"
        else:
            direction = "ns"

        log_fc_value = row.get("logFC")
        adj_pval_value = row.get("adj.P.Val")
        gene_rows.append(
            ModuleGeneRow(
                ensembl=gene_id,
                symbol=symbol_map.get(gene_id, "—"),
                log_fc=f"{log_fc_value:.4f}" if log_fc_value is not None else "—",
                adj_pval=f"{adj_pval_value:.4e}" if adj_pval_value is not None else "—",
                direction=direction,
            )
        )

    ratios = compute_module_ratios(
        de_data["genes"],
        classified,
        {module_id: module_gene_set},
    )
    ratio_value = ratios.get(module_id)
    if ratio_value is None:
        ratio_value = 0.0

    visible_rows = tuple(gene_rows[:MAX_GENES_DISPLAY])
    hidden_count = max(len(gene_rows) - len(visible_rows), 0)

    return ModuleDetailResult(
        module_id=module_id,
        cutoff=cutoff,
        module_gene_count=len(module_genes),
        overlap_count=len(genes_in_file),
        up_count=sum(1 for row in gene_rows if row.direction == "up"),
        down_count=sum(1 for row in gene_rows if row.direction == "down"),
        de_ratio=ratio_value,
        genes=visible_rows,
        hidden_gene_count=hidden_count,
    )
