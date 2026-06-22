"""Load bundled DINA Liver Resource reference data."""

from __future__ import annotations

import csv
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from django.conf import settings

EXPECTED_LEAF_COUNT = 105
EXPECTED_MODULE_COUNT = 105
EXPECTED_VERTEX_COUNT = 209


def get_data_root() -> Path:
    """Return the configured liver resource data directory."""
    return Path(settings.LIVER_RESOURCE_DATA_ROOT).expanduser().resolve()


@lru_cache(maxsize=1)
def load_tln_graph() -> dict[str, Any]:
    """Load the TLN graph exported from ``TLNgraph.RDS`` as JSON."""
    path = get_data_root() / "tln_graph.json"
    with path.open(encoding="utf-8") as handle:
        graph: dict[str, Any] = json.load(handle)
    _validate_tln_graph(graph)
    return graph


@lru_cache(maxsize=1)
def load_cyjs_layout() -> dict[str, tuple[float, float]]:
    """Load node x/y positions from the Cytoscape layout file."""
    path = get_data_root() / "TLN.EdgeList.csv.cyjs"
    with path.open(encoding="utf-8") as handle:
        cyjs: dict[str, Any] = json.load(handle)

    positions: dict[str, tuple[float, float]] = {}
    for node in cyjs["elements"]["nodes"]:
        name = node["data"]["shared_name"]
        x = float(node["position"]["x"])
        y = float(node["position"]["y"])
        positions[name] = (x, y)
    return positions


@lru_cache(maxsize=1)
def load_modules() -> dict[int, list[str]]:
    """Load Ensembl gene IDs per module from ``modules/Module.N.txt`` files."""
    modules_dir = get_data_root() / "modules"
    modules: dict[int, list[str]] = {}
    for module_id in range(1, EXPECTED_MODULE_COUNT + 1):
        path = modules_dir / f"Module.{module_id}.txt"
        with path.open(encoding="utf-8") as handle:
            genes = [line.strip() for line in handle if line.strip()]
        modules[module_id] = genes
    return modules


@lru_cache(maxsize=1)
def load_symbol_map() -> dict[str, str]:
    """Load Ensembl ID to gene symbol mapping."""
    path = get_data_root() / "hsapiens.SYMBOL.txt"
    symbol_map: dict[str, str] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t")
        for row in reader:
            if len(row) >= 2:
                symbol_map[row[0]] = row[1]
    return symbol_map


@lru_cache(maxsize=1)
def load_module_labels() -> dict[str, str]:
    """Load module number to display label mapping."""
    path = get_data_root() / "ITA.Liver.ModNames.2025.txt"
    labels: dict[str, str] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t")
        for row in reader:
            if len(row) >= 2:
                labels[row[0]] = row[1]
    return labels


def list_example_files() -> list[Path]:
    """Return bundled example DE files available for the Load example action."""
    examples_dir = get_data_root() / "examples"
    return sorted(examples_dir.glob("*.txt"))


def get_template_path() -> Path:
    """Return the path to the downloadable DE upload template."""
    return get_data_root() / "DE_upload_template.txt"


def clear_reference_data_cache() -> None:
    """Clear cached reference data (for tests)."""
    load_tln_graph.cache_clear()
    load_cyjs_layout.cache_clear()
    load_modules.cache_clear()
    load_symbol_map.cache_clear()
    load_module_labels.cache_clear()


def _validate_tln_graph(graph: dict[str, Any]) -> None:
    """Validate graph structure matches the expected TLN reference model."""
    meta = graph["meta"]
    vertices = graph["vertices"]
    edges = graph["edges"]

    if len(vertices) != meta["vertex_count"] != EXPECTED_VERTEX_COUNT:
        msg = f"Expected {EXPECTED_VERTEX_COUNT} vertices, got {len(vertices)}"
        raise ValueError(msg)

    degree: dict[str, int] = {vertex["name"]: 0 for vertex in vertices}
    for edge in edges:
        degree[edge["source"]] = degree.get(edge["source"], 0) + 1
        degree[edge["target"]] = degree.get(edge["target"], 0) + 1

    leaf_count = sum(1 for value in degree.values() if value == 1)
    if leaf_count != EXPECTED_LEAF_COUNT:
        msg = f"Expected {EXPECTED_LEAF_COUNT} leaf modules, got {leaf_count}"
        raise ValueError(msg)
