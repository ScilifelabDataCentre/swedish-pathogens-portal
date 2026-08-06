"""Server-side Plotly figures for a DRR dataset (spec section 6, ADR-0004).

All figures are computed offline from the standardized feature matrix and
serialised to Plotly JSON. Trace ``uid``s (randomly assigned by Plotly) are
stripped so the serialised output is byte-stable across identical runs, which
the ``drr_precompute`` idempotency contract depends on.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import plotly.graph_objects as go
import polars as pl

from dashboard_visualisation.utils.plotly import figure_to_json

from .loader import FeatureTable

# Radar / heatmap feature categories (CellProfiler measurement groups).
FEATURE_CATEGORIES: list[str] = [
    "AreaShape",
    "Intensity",
    "Granularity",
    "Correlation",
    "RadialDistribution",
    "Neighbors",
]

# Treatment perturbation label; anything else is treated as a control/reference.
_TREATMENT_LABEL = "trt"

# Cap heatmap rows so the serialised figure stays small; compounds are ranked by
# overall absolute morphological signal. The second axis is Open Item 2.
_HEATMAP_MAX_COMPOUNDS = 50


@dataclass
class _Prepared:
    """Precomputed inputs shared by every figure builder.

    Attributes:
        matrix: Standardized feature matrix (rows = profiles, cols = features).
        feature_columns: Feature column names, aligned with ``matrix`` columns.
        categories: Feature category per column (``None`` if uncategorised).
        pert_types: Per-row ``pert_type`` label.
        cbkids: Per-row ``cbkid`` label.
    """

    matrix: np.ndarray
    feature_columns: list[str]
    categories: list[str | None]
    pert_types: np.ndarray
    cbkids: np.ndarray


def _feature_category(column: str) -> str | None:
    """Return the CellProfiler category prefix of a feature column, if known."""
    prefix = column.split("_", 1)[0]
    return prefix if prefix in FEATURE_CATEGORIES else None


def _column_values(table: FeatureTable, name: str) -> np.ndarray:
    """Return a string array of a metadata column, or empty strings if absent."""
    if name in table.frame.columns:
        return np.array([str(value) for value in table.frame[name].to_list()])
    return np.array([""] * table.frame.height)


def _prepare(table: FeatureTable) -> _Prepared:
    """Impute and z-score the feature matrix and gather per-row labels."""
    matrix = table.numeric_matrix()
    column_mean = np.nanmean(matrix, axis=0) if matrix.size else np.zeros(matrix.shape[1])
    column_mean = np.where(np.isnan(column_mean), 0.0, column_mean)
    matrix = np.where(np.isnan(matrix), column_mean, matrix)

    mean = matrix.mean(axis=0) if matrix.size else np.zeros(matrix.shape[1])
    std = matrix.std(axis=0) if matrix.size else np.ones(matrix.shape[1])
    std = np.where(std == 0.0, 1.0, std)
    standardized = (matrix - mean) / std

    categories = [_feature_category(column) for column in table.feature_columns]
    return _Prepared(
        matrix=standardized,
        feature_columns=table.feature_columns,
        categories=categories,
        pert_types=_column_values(table, "pert_type"),
        cbkids=_column_values(table, "cbkid"),
    )


def _category_indices(prep: _Prepared) -> dict[str, list[int]]:
    """Map each feature category to the column indices that belong to it."""
    return {
        category: [i for i, value in enumerate(prep.categories) if value == category]
        for category in FEATURE_CATEGORIES
    }


def build_pca(prep: _Prepared) -> go.Figure:
    """Build a PC1/PC2 scatter of well-level profiles coloured by ``pert_type``.

    PCA is computed via numpy SVD on the standardized matrix (no sklearn). Each
    component's sign is fixed (largest-magnitude loading forced positive) so the
    scores, and therefore the serialised figure, are reproducible.
    """
    data = prep.matrix
    left, singular, right = np.linalg.svd(data, full_matrices=False)
    components = min(2, singular.shape[0])
    scores = left[:, :components] * singular[:components]
    for i in range(components):
        loading = right[i]
        pivot = int(np.argmax(np.abs(loading)))
        if loading[pivot] < 0:
            scores[:, i] = -scores[:, i]

    total_variance = float(np.sum(singular**2)) or 1.0
    explained = (singular**2) / total_variance
    if scores.shape[1] < 2:
        scores = np.column_stack([scores, np.zeros(scores.shape[0])])
        explained = np.append(explained, 0.0)

    figure = go.Figure()
    for level in sorted(set(prep.pert_types.tolist())):
        mask = prep.pert_types == level
        figure.add_scatter(
            x=scores[mask, 0],
            y=scores[mask, 1],
            mode="markers",
            name=level or "unknown",
            marker={"size": 5, "opacity": 0.6},
        )
    figure.update_layout(
        title="PCA of well-level morphological profiles",
        xaxis_title=f"PC1 ({explained[0] * 100:.1f}% variance)",
        yaxis_title=f"PC2 ({explained[1] * 100:.1f}% variance)",
        legend_title="pert_type",
        plot_bgcolor="white",
    )
    return figure


def _compound_category_matrix(prep: _Prepared) -> tuple[list[str], np.ndarray]:
    """Return sorted cbkids and their per-category mean standardized signal."""
    category_indices = _category_indices(prep)
    cbkids = sorted(set(prep.cbkids.tolist()))
    rows = []
    for cbkid in cbkids:
        row_mask = prep.cbkids == cbkid
        subset = prep.matrix[row_mask]
        rows.append(
            [
                float(subset[:, indices].mean()) if indices and subset.size else 0.0
                for indices in (category_indices[category] for category in FEATURE_CATEGORIES)
            ]
        )
    matrix = np.array(rows) if rows else np.zeros((0, len(FEATURE_CATEGORIES)))
    return cbkids, matrix


def build_heatmap(prep: _Prepared) -> go.Figure:
    """Build a compound x feature-category heatmap of mean standardized signal."""
    cbkids, matrix = _compound_category_matrix(prep)
    if matrix.shape[0] > _HEATMAP_MAX_COMPOUNDS:
        ranked = np.argsort(-np.abs(matrix).sum(axis=1))[:_HEATMAP_MAX_COMPOUNDS]
        ranked = np.sort(ranked)
        matrix = matrix[ranked]
        cbkids = [cbkids[i] for i in ranked]

    figure = go.Figure(
        go.Heatmap(
            z=matrix,
            x=FEATURE_CATEGORIES,
            y=cbkids,
            colorscale="RdBu",
            zmid=0,
            colorbar={"title": "mean z-score"},
        )
    )
    figure.update_layout(
        title="Compound x feature-category morphological signal",
        xaxis_title="Feature category",
        yaxis_title="Compound (cbkid)",
    )
    return figure


def _category_means(prep: _Prepared, row_mask: np.ndarray) -> list[float]:
    """Return the mean standardized value per feature category for the rows."""
    category_indices = _category_indices(prep)
    means = []
    for category in FEATURE_CATEGORIES:
        indices = category_indices[category]
        if indices and bool(row_mask.any()):
            means.append(float(prep.matrix[row_mask][:, indices].mean()))
        else:
            means.append(0.0)
    return means


def build_radar(prep: _Prepared, *, mode: str) -> go.Figure:
    """Build a radar of per-category means for treatment or reference rows.

    Args:
        prep: The prepared figure inputs.
        mode: ``"compound"`` for treatment profiles, ``"infected"`` for the
            non-treatment (control / infected) reference.
    """
    if mode == "compound":
        mask = prep.pert_types == _TREATMENT_LABEL
        label = "Treatment (mean)"
        title = "Radar: mean treatment morphology by feature category"
    else:
        mask = prep.pert_types != _TREATMENT_LABEL
        label = "Infected / control (mean)"
        title = "Radar: infected-cell reference by feature category"
    if not bool(mask.any()):
        mask = np.ones(prep.matrix.shape[0], dtype=bool)

    means = _category_means(prep, mask)
    figure = go.Figure(
        go.Scatterpolar(
            r=[*means, means[0]],
            theta=[*FEATURE_CATEGORIES, FEATURE_CATEGORIES[0]],
            fill="toself",
            name=label,
        )
    )
    figure.update_layout(title=title, showlegend=True)
    return figure


def _read_coords(path: Path) -> pl.DataFrame:
    """Read a precomputed UMAP coordinates file (parquet or CSV)."""
    if path.suffix == ".parquet":
        return pl.read_parquet(path)
    return pl.read_csv(path)


def build_umap(coords_path: str | Path | None) -> go.Figure | None:
    """Build a UMAP scatter from precomputed coordinates, or ``None`` if absent.

    Phase 1 sources UMAP coordinates offline (no ``umap-learn`` dependency; see
    FREYA-2560). When no coordinates file is supplied the figure is skipped.

    Args:
        coords_path: Path to a parquet/CSV with ``umap_x``, ``umap_y`` and an
            optional ``pert_type`` column, or ``None`` to skip.

    Returns:
        A Plotly figure, or ``None`` when no coordinates are provided.

    Raises:
        ValueError: If the coordinates file lacks the required columns.
    """
    if coords_path is None:
        return None

    frame = _read_coords(Path(coords_path))
    missing = {"umap_x", "umap_y"} - set(frame.columns)
    if missing:
        raise ValueError(f"UMAP coords missing columns: {sorted(missing)}")

    x = frame["umap_x"].to_numpy().astype(np.float64)
    y = frame["umap_y"].to_numpy().astype(np.float64)
    if "pert_type" in frame.columns:
        pert_types = np.array([str(value) for value in frame["pert_type"].to_list()])
    else:
        pert_types = np.array(["all"] * len(x))

    figure = go.Figure()
    for level in sorted(set(pert_types.tolist())):
        mask = pert_types == level
        figure.add_scatter(
            x=x[mask],
            y=y[mask],
            mode="markers",
            name=level or "unknown",
            marker={"size": 5, "opacity": 0.6},
        )
    figure.update_layout(
        title="UMAP embedding (precomputed)",
        xaxis_title="UMAP-1",
        yaxis_title="UMAP-2",
        legend_title="pert_type",
        plot_bgcolor="white",
    )
    return figure


def _to_json(figure: go.Figure) -> dict[str, Any]:
    """Serialise a figure to PostgreSQL-safe JSON with trace uids stripped."""
    payload = figure_to_json(figure)
    for trace in payload.get("data", []):
        trace.pop("uid", None)
    return payload


def build_all_figures(
    table: FeatureTable,
    *,
    umap_coords: str | Path | None = None,
) -> dict[str, Any]:
    """Build every DRR figure and return them keyed by ``figure_id``.

    Args:
        table: The loaded feature table.
        umap_coords: Optional precomputed UMAP coordinates path; when omitted the
            ``umap`` figure is skipped.

    Returns:
        A dict mapping ``figure_id`` to serialised Plotly JSON. Always contains
        ``pca``, ``heatmap``, ``radar_compound`` and ``radar_infected``; adds
        ``umap`` only when coordinates are supplied.
    """
    prep = _prepare(table)
    figures: dict[str, Any] = {
        "pca": _to_json(build_pca(prep)),
        "heatmap": _to_json(build_heatmap(prep)),
        "radar_compound": _to_json(build_radar(prep, mode="compound")),
        "radar_infected": _to_json(build_radar(prep, mode="infected")),
    }
    umap_figure = build_umap(umap_coords)
    if umap_figure is not None:
        figures["umap"] = _to_json(umap_figure)
    return figures
