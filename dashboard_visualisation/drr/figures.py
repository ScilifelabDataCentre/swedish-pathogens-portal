"""Server-side Plotly figures for a DRR dataset (spec section 6, ADR-0004).

All figures are computed offline from the feature matrix and serialised to Plotly
JSON. The input arrives MAD-normalised per plate against that plate's DMSO wells,
which is the only normalisation applied to it; values are therefore in the
authors' MAD units throughout (spec section 5). They are computed on the **figure
basis** — the morphology columns, with the screen's infection-readout channel
excluded (``channels``, FREYA-2923), clipped to ``FIGURE_CLIP_BOUND`` as the
published pipeline does (FREYA-2968) — while the downloads carry every column
exactly as delivered. Trace
``uid``s (randomly assigned by Plotly) are stripped so the serialised output is
byte-stable across identical runs, which the ``drr_precompute`` idempotency
contract depends on.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import numpy as np
import plotly.graph_objects as go

from dashboard_visualisation.utils.plotly import figure_to_json

from .channels import Channel
from .loader import FeatureTable
from .radar import (
    INFECTED_POPULATION,
    TREATMENT_POPULATION,
    RadarAxis,
    axis_values,
    build_ring,
    unplotted_columns,
)

# The figures computed from the feature matrix, and therefore from the figure
# basis rather than the download set. ``summary.json`` reads this list, so the
# figure basis is recorded where it is used.
FEATURE_BASIS_FIGURE_IDS: tuple[str, ...] = (
    "pca",
    "radar_compound",
    "radar_infected",
)

# The authors' pipeline clips every feature value to this bound immediately after
# MAD normalisation and before any modelling, and our input predates that step
# (``plans/DRR/reference/data-sources.md`` DS-3). The figure path therefore clips
# to it; the downloads publish the table as delivered (spec section 5). It belongs
# to the upstream pipeline rather than to one screen, so it is stated here and not
# in the per-screen ``channels`` map.
FIGURE_CLIP_BOUND = 50.0

# How many of the worst-affected columns ``clip_report`` names.
_CLIP_REPORT_COLUMNS = 5

# What one figure may weigh in ``DrrDatasetData.data``. The snippet is a single
# ``JSONField``, so every figure on it is deserialised to render any one of
# them, and each precompute run snapshots the lot into a revision. The bound is
# generous against what the page actually carries and exists to catch the other
# end: the clustered compound-by-feature panel that measured 33.9 MB and forced
# the move to an on-disk set. A figure past it is refused rather than published
# (a set belongs under ``figures/radar/``, not here).
SNIPPET_FIGURE_BYTE_CEILING = 1024 * 1024


@dataclass
class _Prepared:
    """Precomputed inputs shared by every figure builder.

    Attributes:
        matrix: Figure-basis feature matrix, clipped (rows = profiles,
            cols = the figure basis's features).
        feature_columns: The figure basis's column names, aligned with
            ``matrix`` columns.
        pert_types: Per-row ``pert_type`` label.
        cbkids: Per-row ``cbkid`` label.
        n_download_features: How many features the downloads carry, which the
            radar caveat states beside the narrower figure basis.
    """

    matrix: np.ndarray
    feature_columns: list[str]
    pert_types: np.ndarray
    cbkids: np.ndarray
    n_download_features: int


def _column_values(table: FeatureTable, name: str) -> np.ndarray:
    """Return a string array of a metadata column, or empty strings if absent."""
    if name in table.frame.columns:
        return np.array([str(value) for value in table.frame[name].to_list()])
    return np.array([""] * table.frame.height)


def clip_figure_values(matrix: np.ndarray) -> np.ndarray:
    """Return the feature matrix clipped to the figure range.

    Args:
        matrix: Figure-basis feature values as delivered.

    Returns:
        The same values with anything beyond ``±FIGURE_CLIP_BOUND`` brought to
        the bound, which is where the authors' pipeline puts this step. The
        caller's array is left alone, so the frame the downloads are written
        from never sees the clip (spec section 5, FREYA-2968).
    """
    return np.clip(matrix, -FIGURE_CLIP_BOUND, FIGURE_CLIP_BOUND)


def clip_report(table: FeatureTable, feature_columns: list[str]) -> dict[str, Any]:
    """Describe what clipping the figure basis changed, for ``summary.json``.

    Args:
        table: The loaded feature table.
        feature_columns: The figure basis's column names.

    Returns:
        The bound, how many values it moved out of how many, and the
        worst-affected columns — so the page can state the figure basis rather
        than implying that it and the download set agree (spec section 7).
        Columns are ordered by descending count, then by name, so a re-run on
        the same input reports them identically.
    """
    matrix = table.numeric_matrix(feature_columns)
    outside = np.abs(matrix) > FIGURE_CLIP_BOUND
    per_column = outside.sum(axis=0)
    affected = sorted(
        (
            {"column": column, "n_clipped": int(count)}
            for column, count in zip(feature_columns, per_column, strict=True)
            if count
        ),
        key=lambda entry: (-entry["n_clipped"], entry["column"]),
    )
    return {
        "lower": -FIGURE_CLIP_BOUND,
        "upper": FIGURE_CLIP_BOUND,
        "n_values": int(matrix.size),
        "n_values_clipped": int(outside.sum()),
        "n_columns_clipped": len(affected),
        "most_affected_columns": affected[:_CLIP_REPORT_COLUMNS],
    }


def figure_basis_token(feature_columns: list[str]) -> str:
    """Return a token naming how the figures were computed, for the digest.

    The ``PlotlyFigureBlock`` render cache is keyed on the *inputs*, so a change
    to the computation — the channel exclusion, the clip bound — would otherwise
    leave the key identical while the figures move, and the page would serve the
    previous render for a day (spec section 5 step 6).

    Args:
        feature_columns: The figure basis's column names.

    Returns:
        The figure column count and the clip bound, in that fixed order.
    """
    return f"figure-basis:{len(feature_columns)}:{FIGURE_CLIP_BOUND}"


def _prepare(table: FeatureTable, feature_columns: list[str]) -> _Prepared:
    """Clip the figure feature matrix and gather the per-row labels.

    Neither standardisation nor imputation is applied: the values arrive
    MAD-normalised per plate and carry no missing entries (spec section 5).
    ``numeric_matrix`` rejects an incomplete matrix, so no gap reaches a figure.
    The clip is the one transform applied here, and it happens after load and
    before any figure is computed — where the paper's methods put it.

    ``feature_columns`` is the figure basis, which is narrower than the table's
    own feature set: the infection-readout channel is excluded, so a morphology
    figure cannot be computed partly from the assay's own answer (FREYA-2923).
    The downloads keep every column, unclipped.
    """
    return _Prepared(
        matrix=clip_figure_values(table.numeric_matrix(feature_columns)),
        feature_columns=feature_columns,
        pert_types=_column_values(table, "pert_type"),
        cbkids=_column_values(table, "cbkid"),
        n_download_features=len(table.feature_columns),
    )


def build_pca(prep: _Prepared) -> go.Figure:
    """Build a PC1/PC2 scatter of well-level profiles coloured by ``pert_type``.

    PCA is computed via numpy SVD on the clipped figure basis (no sklearn). Only
    the column means are removed, which is what makes the decomposition a PCA
    and what the percent-variance annotation is measured against; the per-column
    scaling is not reapplied, matching the authors' ``PLSRegression(scale=False)``
    (spec section 5). Each component's sign is fixed (largest-magnitude loading
    forced positive) so the scores, and therefore the serialised figure, are
    reproducible.
    """
    data = prep.matrix
    centred = data - data.mean(axis=0) if data.size else data
    left, singular, right = np.linalg.svd(centred, full_matrices=False)
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


def _radar_caveat(prep: _Prepared) -> str:
    """State which basis a radar was computed on, so it cannot be misread.

    The figure basis and the download set differ in both width and range, and
    neither is the basis the published radar uses, so every visible radar says
    so in its own payload — which means it keeps saying so after an htmx swap
    (FREYA-2636 criterion 9).

    It is carried in ``layout.meta`` rather than as a Plotly annotation, and
    the page renders it as text beneath the chart: annotation text does not
    wrap, so a sentence this long is clipped at the plot's edge on a narrow
    viewport, and a caveat a reader cannot finish is not a caveat.
    """
    return (
        f"Approximation: computed on this portal's figure basis of "
        f"{len(prep.feature_columns):,} morphology features, clipped to "
        f"±{FIGURE_CLIP_BOUND:g}, not on the published consensus profiles. "
        f"The downloads carry all {prep.n_download_features:,} features, unclipped."
    )


def build_radar(
    prep: _Prepared,
    axes: list[RadarAxis],
    *,
    row_mask: np.ndarray,
    title: str,
    trace_name: str,
) -> go.Figure:
    """Build one radar over Figure 3C's axis ring.

    Args:
        prep: The prepared figure inputs.
        axes: The ring, from ``radar.build_ring``.
        row_mask: The condition's rows.
        title: The figure title.
        trace_name: The trace's legend name.

    Returns:
        A ``Scatterpolar`` closed on its first axis, carrying the basis caveat.

    Raises:
        ValueError: If the condition selects no profile (``radar.axis_values``).
    """
    values = axis_values(prep.matrix, axes, row_mask)
    labels = [axis.label for axis in axes]

    figure = go.Figure(
        go.Scatterpolar(
            r=[*values, values[0]],
            theta=[*labels, labels[0]],
            fill="toself",
            name=trace_name,
            connectgaps=False,
        )
    )
    figure.update_layout(
        title=title,
        showlegend=True,
        meta={"caveat": _radar_caveat(prep)},
    )
    return figure


def build_infected_radar(prep: _Prepared, axes: list[RadarAxis]) -> go.Figure:
    """Build Figure 3C itself: how far infection moves the profile.

    The plotted condition is the **uninfected** population. The input is
    MAD-normalised against each plate's infected DMSO wells, whose own absolute
    mean is ~0 by construction, so those wells are the baseline the ring is read
    against and the uninfected profiles carry the infection contrast (DS-8 item
    4; measured 0.0871 against 1.2661 on the real table).
    """
    return build_radar(
        prep,
        axes,
        row_mask=prep.pert_types == INFECTED_POPULATION,
        title="Radar: feature groups most changed by infection",
        trace_name="Uninfected wells vs infected DMSO baseline",
    )


def build_compound_radar(
    prep: _Prepared,
    axes: list[RadarAxis],
    *,
    cbkid: str | None = None,
    label: str | None = None,
) -> go.Figure:
    """Build the treatment radar, for one compound or for all of them.

    Args:
        prep: The prepared figure inputs.
        axes: The ring, from ``radar.build_ring``.
        cbkid: One compound's id, whose treated wells are plotted with their
            doses pooled into a single profile. ``None`` builds the default view
            the page holds before a reader picks anything: every treated well,
            so precompute chooses no compound (spec section 6).
        label: Display name for the compound, defaulting to its id.

    Returns:
        A radar on the same ring and the same statistic as ``radar_infected``.
    """
    treated = prep.pert_types == TREATMENT_POPULATION
    if cbkid is None:
        return build_radar(
            prep,
            axes,
            row_mask=treated,
            title="Radar: treated wells vs infected DMSO baseline",
            trace_name="All treated compounds (doses pooled)",
        )

    name = label or cbkid
    return build_radar(
        prep,
        axes,
        row_mask=treated & (prep.cbkids == cbkid),
        title=f"Radar: {name} vs infected DMSO baseline",
        trace_name=f"{name} (doses pooled)",
    )


def oversized_figures(figures: dict[str, Any]) -> dict[str, int]:
    """Return the serialised size of each figure too large for the snippet.

    Args:
        figures: The snippet payload, keyed by ``figure_id``.

    Returns:
        ``figure_id`` to byte size, for those over ``SNIPPET_FIGURE_BYTE_CEILING``
        — empty when every figure fits. Size is checked rather than assumed:
        the 33.9 MB panel satisfied every value-level assertion made about it.
    """
    return {
        figure_id: size
        for figure_id, payload in figures.items()
        if (size := len(json.dumps(payload).encode("utf-8"))) > SNIPPET_FIGURE_BYTE_CEILING
    }


def _to_json(figure: go.Figure) -> dict[str, Any]:
    """Serialise a figure to PostgreSQL-safe JSON with trace uids stripped."""
    payload = figure_to_json(figure)
    for trace in payload.get("data", []):
        trace.pop("uid", None)
    return payload


@dataclass(frozen=True)
class FigureBundle:
    """Everything one precompute run renders.

    Attributes:
        figures: The snippet payload, keyed by ``figure_id``. One figure per id,
            and never a set — the per-compound radars are far too many for a
            single ``JSONField`` that is deserialised whole to render one figure
            (spec section 4).
        radars: One radar per compound with treated wells, keyed by ``cbkid``.
            These go to disk and are served by the section 8.3 route.
        axes: The radar ring this run plotted, for the run's own report.
        unplotted_columns: Figure-basis columns no axis averages.
    """

    figures: dict[str, Any]
    radars: dict[str, Any]
    axes: list[RadarAxis]
    unplotted_columns: list[str]


def build_figure_bundle(
    table: FeatureTable,
    *,
    feature_columns: list[str],
    channels: tuple[Channel, ...],
    compound_labels: dict[str, str] | None = None,
) -> FigureBundle:
    """Build the snippet's figures and the per-compound radar set in one pass.

    Args:
        table: The loaded feature table.
        feature_columns: The figure basis — the morphology feature columns, from
            ``channels.figure_feature_columns``, whose values are clipped to
            ``FIGURE_CLIP_BOUND`` before any figure sees them. Required rather
            than defaulted: silently falling back to every column is the defect
            FREYA-2923 removed, so a caller has to state the basis it means.
        channels: This screen's channel map, which the radar ring's stain groups
            come from.
        compound_labels: Optional ``cbkid`` to display-name map, used for each
            per-compound radar's title.

    Returns:
        The bundle. Its ``figures`` always contain ``FEATURE_BASIS_FIGURE_IDS``.

    Raises:
        ValueError: If a radar population is empty (``radar.axis_values``).
    """
    prep = _prepare(table, feature_columns)
    axes = build_ring(feature_columns, channels)
    labels = compound_labels or {}

    figures: dict[str, Any] = {
        "pca": _to_json(build_pca(prep)),
        "radar_compound": _to_json(build_compound_radar(prep, axes)),
        "radar_infected": _to_json(build_infected_radar(prep, axes)),
    }

    treated = sorted(set(prep.cbkids[prep.pert_types == TREATMENT_POPULATION].tolist()))
    radars = {
        cbkid: _to_json(build_compound_radar(prep, axes, cbkid=cbkid, label=labels.get(cbkid)))
        for cbkid in treated
    }
    return FigureBundle(
        figures=figures,
        radars=radars,
        axes=axes,
        unplotted_columns=unplotted_columns(feature_columns, axes),
    )


def build_all_figures(
    table: FeatureTable,
    *,
    feature_columns: list[str],
    channels: tuple[Channel, ...],
) -> dict[str, Any]:
    """Build the snippet's figures, keyed by ``figure_id``.

    A thin view of ``build_figure_bundle`` for callers that want only what the
    snippet holds.
    """
    return build_figure_bundle(
        table,
        feature_columns=feature_columns,
        channels=channels,
    ).figures
