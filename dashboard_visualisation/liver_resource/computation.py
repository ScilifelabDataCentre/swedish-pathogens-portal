"""DINA Liver TLN computation pipeline — port of run_tln_analysis.R."""

from __future__ import annotations

import csv
import math
from io import StringIO
from pathlib import Path
from typing import BinaryIO

from dashboard_visualisation.liver_resource.reference_data import load_modules as _load_module_lists

type DeFileSource = str | Path | BinaryIO

VALID_CUTOFFS = (
    "standard",
    "sensitive",
    "stringent",
    "stringent_2",
    "max",
    "Ponly",
    "unadj",
    "top3",
    "top50",
    "top100",
    "top200",
    "top500",
    "top1000",
)

LOG2_1_5 = math.log2(1.5)
LOG2_0_5 = math.log2(0.5)
LOG2_2 = math.log2(2)
LOG2_5 = math.log2(5)

# Researcher default (TLN_Analyses_DataCenter.R f.TLNplot)
R_PALETTE = (
    "#00008b",  # darkblue
    "#0000cd",  # mediumblue
    "#1e90ff",  # dodgerblue
    "#ffffff",
    "#ffa500",  # orange
    "#ff0000",  # red
    "#8b0000",  # darkred
)
# Legacy 2025 hex palette:
# R_PALETTE = ("#2066a8", "#8ec1da", "#cde1ec", "#ffffff", "#f6d6c2", "#d47264", "#ae282c")

_COLOR_SCALE = None


def parse_de_file(source: DeFileSource) -> dict:
    """Parse a tab- or comma-separated DE results file."""
    if isinstance(source, (str, Path)):
        with Path(source).open(encoding="utf-8") as handle:
            return _parse_de_lines(handle.readlines())
    if hasattr(source, "read"):
        text = source.read()
        if isinstance(text, bytes):
            text = text.decode("utf-8")
        return _parse_de_lines(text.splitlines(keepends=True))
    msg = f"Unsupported DE file source type: {type(source)!r}"
    raise TypeError(msg)


def _detect_delimiter(line: str) -> str:
    """Return tab or comma delimiter based on the header row."""
    tab_count = line.count("\t")
    comma_count = line.count(",")
    if tab_count > comma_count:
        return "\t"
    if comma_count > 0:
        return ","
    return "\t"


def _parse_de_rows(lines: list[str]) -> list[list[str]]:
    """Split DE file lines into rows, supporting tab- or comma-separated values."""
    non_empty = [line for line in lines if line.strip()]
    if not non_empty:
        return []

    delimiter = _detect_delimiter(non_empty[0])
    reader = csv.reader(StringIO("".join(non_empty)), delimiter=delimiter)
    return [row for row in reader if row and any(cell.strip() for cell in row)]


def _parse_de_lines(lines: list[str]) -> dict:
    parts = _parse_de_rows(lines)
    if not parts:
        return {"header": [], "genes": [], "data": {}}

    header = parts[0]
    genes: list[str] = []
    data: dict[str, dict[str, float | None]] = {}

    for row in parts[1:]:
        gene_id = row[0]
        genes.append(gene_id)
        values: dict[str, float | None] = {}
        for index, column in enumerate(header):
            try:
                values[column] = float(row[index + 1])
            except (ValueError, IndexError):
                values[column] = None
        data[gene_id] = values

    return {"header": header, "genes": genes, "data": data}


def classify_genes(de_data: dict, cutoff: str) -> dict[str, set[str]]:
    """Classify genes as up-regulated or down-regulated for a DEcutoff mode."""
    if cutoff not in VALID_CUTOFFS:
        msg = f"Invalid cutoff '{cutoff}'. Must be one of: {list(VALID_CUTOFFS)}"
        raise ValueError(msg)

    genes = de_data["genes"]
    data = de_data["data"]
    up: set[str] = set()
    down: set[str] = set()

    if cutoff == "standard":
        for gene_id in genes:
            row = data[gene_id]
            if row["adj.P.Val"] is not None and row["logFC"] is not None:
                if row["adj.P.Val"] < 0.05 and row["logFC"] > LOG2_1_5:
                    up.add(gene_id)
                elif row["adj.P.Val"] < 0.05 and row["logFC"] < -LOG2_1_5:
                    down.add(gene_id)

    elif cutoff == "sensitive":
        for gene_id in genes:
            row = data[gene_id]
            if row["adj.P.Val"] is not None and row["logFC"] is not None:
                if row["adj.P.Val"] < 0.05 and row["logFC"] > LOG2_0_5:
                    up.add(gene_id)
                elif row["adj.P.Val"] < 0.05 and row["logFC"] < -LOG2_0_5:
                    down.add(gene_id)

    elif cutoff == "stringent":
        for gene_id in genes:
            row = data[gene_id]
            if row["adj.P.Val"] is not None and row["logFC"] is not None:
                if row["adj.P.Val"] < 0.0001 and row["logFC"] > LOG2_1_5:
                    up.add(gene_id)
                elif row["adj.P.Val"] < 0.0001 and row["logFC"] < -LOG2_1_5:
                    down.add(gene_id)

    elif cutoff == "stringent_2":
        for gene_id in genes:
            row = data[gene_id]
            if row["adj.P.Val"] is not None and row["logFC"] is not None:
                if row["adj.P.Val"] < 0.0001 and row["logFC"] > LOG2_2:
                    up.add(gene_id)
                elif row["adj.P.Val"] < 0.0001 and row["logFC"] < -LOG2_2:
                    down.add(gene_id)

    elif cutoff == "max":
        for gene_id in genes:
            row = data[gene_id]
            if row["adj.P.Val"] is not None and row["logFC"] is not None:
                if row["adj.P.Val"] < 0.0001 and row["logFC"] > LOG2_5:
                    up.add(gene_id)
                elif row["adj.P.Val"] < 0.0001 and row["logFC"] < -LOG2_5:
                    down.add(gene_id)

    elif cutoff == "Ponly":
        for gene_id in genes:
            row = data[gene_id]
            if row["adj.P.Val"] is not None and row["logFC"] is not None:
                if row["adj.P.Val"] < 0.05 and row["logFC"] > 0:
                    up.add(gene_id)
                elif row["adj.P.Val"] < 0.05 and row["logFC"] < 0:
                    down.add(gene_id)

    elif cutoff == "unadj":
        for gene_id in genes:
            row = data[gene_id]
            if row["P.Value"] is not None and row["logFC"] is not None:
                if row["P.Value"] < 0.05 and row["logFC"] > LOG2_1_5:
                    up.add(gene_id)
                elif row["P.Value"] < 0.05 and row["logFC"] < -LOG2_1_5:
                    down.add(gene_id)

    elif cutoff.startswith("top"):
        top_n = int(cutoff[3:])
        valid = [
            (gene_id, data[gene_id]["t"])
            for gene_id in genes
            if data[gene_id].get("t") is not None
        ]
        sorted_desc = sorted(valid, key=lambda item: item[1], reverse=True)
        up = {gene_id for gene_id, _ in sorted_desc[:top_n]}
        sorted_asc = sorted(valid, key=lambda item: item[1])
        down = {gene_id for gene_id, _ in sorted_asc[:top_n]}

    return {"up": up, "down": down}


def get_module_gene_sets() -> dict[int, set[str]]:
    """Return module gene membership as sets keyed by module id."""
    return {module_id: set(genes) for module_id, genes in _load_module_lists().items()}


def compute_module_ratios(
    de_genes: list[str],
    classified: dict[str, set[str]],
    modules: dict[int, set[str]],
) -> dict[int, float | None]:
    """Compute per-module DE ratio aligned with f.CalculateModRatios2."""
    all_genes = set(de_genes)
    up = classified["up"]
    down = classified["down"]
    ratios: dict[int, float | None] = {}

    for module_id, module_genes in modules.items():
        overlap = all_genes & module_genes
        genes_in_module = len(overlap)
        if genes_in_module == 0:
            ratios[module_id] = None
            continue
        up_count = len(up & module_genes)
        down_count = len(down & module_genes)
        ratios[module_id] = (up_count - down_count) / genes_in_module

    return ratios


def map_ratios_to_colours(
    ratios: dict[int, float | None],
    max_abs: float | None = None,
) -> dict[int, str]:
    """Map module ratios to hex colour strings."""
    valid_ratios = [value for value in ratios.values() if value is not None]
    if not valid_ratios:
        return dict.fromkeys(ratios, "#ffffff")

    if max_abs is None:
        max_abs = max(abs(value) for value in valid_ratios)
    if max_abs == 0:
        return dict.fromkeys(ratios, "#ffffff")

    colour_scale = _get_color_scale()
    half_bins = (len(colour_scale) - 1) // 2
    colours: dict[int, str] = {}
    for module_id, ratio in ratios.items():
        if ratio is None:
            colours[module_id] = "#ffffff"
            continue
        index = int(round(ratio * half_bins / max_abs)) + half_bins
        index = max(0, min(len(colour_scale) - 1, index))
        red, green, blue = colour_scale[index]
        colours[module_id] = f"#{red:02x}{green:02x}{blue:02x}"

    return colours


def _get_color_scale() -> list[tuple[int, int, int]]:
    global _COLOR_SCALE
    if _COLOR_SCALE is None:
        _COLOR_SCALE = _build_color_ramp(list(R_PALETTE))
    return _COLOR_SCALE


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def _interpolate(
    start: tuple[int, int, int],
    end: tuple[int, int, int],
    t: float,
) -> tuple[int, int, int]:
    return tuple(int(start[index] + (end[index] - start[index]) * t) for index in range(3))


def _build_color_ramp(
    palette: list[str],
    bins_per_segment: int = 100,
) -> list[tuple[int, int, int]]:
    midpoint = len(palette) // 2
    negative_colours = list(reversed(palette[: midpoint + 1]))
    positive_colours = palette[midpoint:]
    negative_rgb = [_hex_to_rgb(colour) for colour in negative_colours]
    positive_rgb = [_hex_to_rgb(colour) for colour in positive_colours]

    negative_ramp: list[tuple[int, int, int]] = []
    for index in range(len(negative_rgb) - 1):
        start_rgb = negative_rgb[index]
        end_rgb = negative_rgb[index + 1]
        for step in range(bins_per_segment):
            fraction = step / bins_per_segment
            negative_ramp.append(_interpolate(start_rgb, end_rgb, fraction))

    positive_ramp: list[tuple[int, int, int]] = []
    for index in range(len(positive_rgb) - 1):
        start_rgb = positive_rgb[index]
        end_rgb = positive_rgb[index + 1]
        for step in range(bins_per_segment):
            fraction = step / bins_per_segment
            positive_ramp.append(_interpolate(start_rgb, end_rgb, fraction))
    positive_ramp.append(_hex_to_rgb(positive_colours[-1]))

    return list(reversed(negative_ramp)) + positive_ramp
