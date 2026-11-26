"""Server-side Plotly figures for a DRR dataset (ADR-0004).

All figures are computed offline from the feature matrix and serialised to Plotly
JSON. The input arrives MAD-normalised per plate against that plate's DMSO wells,
which is the only normalisation applied to it; values are therefore in the
authors' MAD units throughout. They are computed on the **figure
basis** — the morphology columns, with the screen's infection-readout channel
excluded (``channels``, FREYA-2923), clipped to ``FIGURE_CLIP_BOUND`` as the
published pipeline does (FREYA-2968) — while the downloads carry every column
exactly as delivered. The PCA alone also leaves out the near-empty wells
(``NEAR_EMPTY_NUCLEI_THRESHOLD``, FREYA-3200); the radars keep every well. The PCA
is fitted once and drawn in each of ``PCA_COLOURINGS``, which recolour the treated
wells only (FREYA-3201), and one compound's wells and dose line can be drawn over
any of them (FREYA-3202), fading the view beneath; every view titles its legend
by its colouring and carries a size key (FREYA-3205). Trace ``uid``s (randomly
assigned by Plotly) are stripped so the serialised output is byte-stable across
identical runs, which the ``drr_precompute`` idempotency contract depends on.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
import plotly.graph_objects as go

from dashboard_visualisation.utils.plotly import figure_to_json

from .channels import Channel
from .loader import FeatureTable
from .radar import (
    BASELINE_POPULATION,
    INFECTED_POPULATION,
    POPULATION_LEGEND_TITLE,
    POSITIVE_CONTROL_POPULATION,
    TREATMENT_POPULATION,
    RadarAxis,
    axis_values,
    build_ring,
    population_label,
    population_labels_token,
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
# MAD normalisation and before any modelling, and our input predates that step.
# The figure path therefore clips to it; the downloads publish the table as
# delivered. It belongs to the upstream pipeline rather than to one screen, so it
# is stated here and not in the per-screen ``channels`` map.
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

# A well with fewer nuclei than this is near-empty: most of its cells died, and
# its profile stretches the PCA's axes rather than describing a morphology. The
# PCA neither fits nor draws it; the radars, the table and the downloads keep it
# (FREYA-3080 acceptance 1, settled by consensus 2026-11-20). A typical well has
# about 240, and one real well sits at exactly 50, which is kept.
NEAR_EMPTY_NUCLEI_THRESHOLD = 50
NUCLEI_COLUMN = "Count_nuclei"
DOSE_COLUMN = "cmpd_conc"
DOSE_UNIT = "µM"

# The PCA's populations, bottom to top: Plotly draws a later trace over an
# earlier one, so the controls are never hidden under the treated wells.
PCA_POPULATION_ORDER: tuple[str, ...] = (
    TREATMENT_POPULATION,
    POSITIVE_CONTROL_POPULATION,
    BASELINE_POPULATION,
    INFECTED_POPULATION,
)

# Fixed hex values, because a precomputed figure cannot read the portal's CSS:
# infected is ``--color-error`` and uninfected ``--color-pp-mid-blue``.
PCA_POPULATION_COLOURS: dict[str, str] = {
    TREATMENT_POPULATION: "#d8d8d8",
    POSITIVE_CONTROL_POPULATION: "#55585a",
    BASELINE_POPULATION: "#a0302c",
    INFECTED_POPULATION: "#4770b1",
}

# The antiviral controls, drawn over every population in this order. Their names
# are fixed here rather than read from the compound index, which still files
# Nirmatrelvir as a control (FREYA-3126).
PCA_ANTIVIRALS: tuple[tuple[str, str], ...] = (
    ("CBK310015", "Remdesivir"),
    ("DO8167002", "Nirmatrelvir"),
    ("CBK310023", "GC376"),
)
# ``--color-warning`` is 1.9:1 against white, under WCAG 1.4.11's 3:1, so the
# antiviral markers carry a dark outline.
PCA_ANTIVIRAL_COLOUR = "#f3b153"
PCA_ANTIVIRAL_OUTLINE = "#1a1c1a"

# Controls are drawn at one size; a treated or antiviral well's size rises with
# its dose's rank among the doses drawn, from the first bound to the second.
PCA_CONTROL_MARKER_SIZE = 6.0
PCA_DOSE_MARKER_SIZES: tuple[float, float] = (4.0, 12.0)
_PCA_MARKER_OPACITY = 0.6
_PCA_ANTIVIRAL_OPACITY = 0.9

# The PCA's colourings, in the picker's order. The default is the view the snippet
# holds; the others are written under ``figures/pca/``, and the page serves only
# these keys, so no request value names a file.
PCA_DEFAULT_COLOURING = "population"
PCA_COLOURINGS: tuple[str, ...] = (PCA_DEFAULT_COLOURING, "morphology", "moa")

# Where a colouring has nothing to colour a treated well by, it says so in words.
PCA_NOT_REPORTED = "Not reported"
PCA_OTHER_MECHANISMS = "Other mechanisms"
PCA_NOT_ANNOTATED = "Not annotated"
_PCA_MISSING_COLOUR = PCA_POPULATION_COLOURS[TREATMENT_POPULATION]
_PCA_OTHER_MECHANISMS_COLOUR = "#a8a8a8"

# The page draws the PCA at this height, and the layout is laid out in pixels
# against it. The margins are pinned so the plot area is the same in every
# colouring, with or without a compound, and a swap does not move the points.
# The legend sits below the plot, where its 7 to 20 entries wrap with the width
# rather than squeezing the plot to a sliver on a narrow screen. Below the plot
# come the axis's room, then the morphology view's colour bar, then the legend,
# capped to what is left and scrolling past it.
PCA_FIGURE_HEIGHT = 880
_PCA_MARGIN_TOP = 100
_PCA_MARGIN_BOTTOM = 380
_PCA_AXIS_ROOM = 60
_PCA_COLOUR_BAR_ROOM = 80
_PCA_PLOT_HEIGHT = PCA_FIGURE_HEIGHT - _PCA_MARGIN_TOP - _PCA_MARGIN_BOTTOM

# Each compound's morphology score as the compound table shows it, on Plotly's
# colour-blind-safe sequential scale.
PCA_MORPHOLOGY_TRACE = "Morphology score"
_PCA_MORPHOLOGY_COLOURSCALE = "Cividis"
# Paper-referenced: a container-referenced bar draws its title over itself.
_PCA_COLOUR_BAR: dict[str, Any] = {
    "title": {"text": PCA_MORPHOLOGY_TRACE, "side": "top"},
    "orientation": "h",
    "x": 0,
    "xanchor": "left",
    "y": -(_PCA_AXIS_ROOM + 10) / _PCA_PLOT_HEIGHT,
    "yanchor": "top",
    "len": 160,
    "lenmode": "pixels",
    "thickness": 12,
}

# What each view's legend is titled by: what colours its treated wells.
PCA_LEGEND_TITLES: dict[str, str] = {
    PCA_DEFAULT_COLOURING: POPULATION_LEGEND_TITLE,
    "morphology": PCA_MORPHOLOGY_TRACE,
    "moa": "Mechanism of action",
}

# Box and lasso select select nothing on this page.
PCA_MODEBAR_REMOVED: tuple[str, ...] = ("select2d", "lasso2d")

# The size key: the smallest and the largest dose marker, hollow so they read as
# a size rather than as a population, last in the legend and drawing no point.
PCA_SIZE_KEY_GROUP = "pca-size-key"
PCA_SIZE_KEY_TITLE = "Dose (marker size)"
_PCA_SIZE_KEY_RANK = 2000

# While a compound is drawn on top, every trace of the view beneath keeps this
# share of its opacity, so the overlay reads first. Plotly draws a legend symbol at
# its trace's opacity, so a much smaller share leaves the legend's swatches unreadable.
PCA_FADED_OPACITY_SHARE = 1 / 2

# The mechanisms with the most compounds drawn take these in rank order: the first
# eight of Paul Tol's colour-blind-safe "muted" scheme, none of them a grey that
# would read as a bucket above or as the positive controls.
PCA_MOA_GROUPS = 8
PCA_MOA_COLOURS: tuple[str, ...] = (
    "#cc6677",
    "#332288",
    "#ddcc77",
    "#117733",
    "#88ccee",
    "#882255",
    "#44aa99",
    "#999933",
)

# One compound's overlay, drawn over every colouring: its wells, then a line
# through its per-dose centroids. The portal's almost-black alone is under 3:1
# against the darkest fills — 1.1:1 on Cividis's dark end — so the markers carry a
# white outline and the line runs over a wider white halo: one of the two always
# contrasts with what lies beneath.
PCA_OVERLAY_COLOUR = "#1a1c1a"
PCA_OVERLAY_HALO_COLOUR = "#ffffff"
_PCA_OVERLAY_LINE_WIDTH = 2
_PCA_OVERLAY_HALO_WIDTH = 6
PCA_OVERLAY_CENTROID_SUFFIX = ": dose centroids"
# The dose line names its lowest and highest dose beside the first and last
# centroid, pushed outward along the line. The layered white shadow keeps the dark
# text legible over the compound's own dark wells.
_PCA_DOSE_LABEL_FONT: dict[str, Any] = {
    "color": PCA_OVERLAY_COLOUR,
    "size": 13,
    "weight": "bold",
    "shadow": "0 0 2px #ffffff, 0 0 3px #ffffff, 0 0 4px #ffffff",
}


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
        nuclei_counts: Per-row ``Count_nuclei``, which decides the PCA's fit.
        doses: Per-row ``cmpd_conc`` in µM, which sizes the PCA's markers.
        n_download_features: How many features the downloads carry, which the
            radar caveat states beside the narrower figure basis.
    """

    matrix: np.ndarray
    feature_columns: list[str]
    pert_types: np.ndarray
    cbkids: np.ndarray
    nuclei_counts: np.ndarray
    doses: np.ndarray
    n_download_features: int


def _column_values(table: FeatureTable, name: str) -> np.ndarray:
    """Return a string array of a metadata column, or empty strings if absent."""
    if name in table.frame.columns:
        return np.array([str(value) for value in table.frame[name].to_list()])
    return np.array([""] * table.frame.height)


def _numeric_column(table: FeatureTable, name: str) -> np.ndarray:
    """Return a numeric metadata column as float64, refusing an absent or incomplete one.

    Raises:
        ValueError: If the column is absent or carries a missing or non-finite
            value. The PCA reads which wells it fits and how large it draws
            them from these columns, so a gap cannot be guessed either way.
    """
    if name not in table.frame.columns:
        raise ValueError(
            f"The feature table has no {name!r} column, which the PCA needs to decide "
            "which wells it fits and how it draws them."
        )
    values = table.frame[name].to_numpy().astype(np.float64)
    if not np.isfinite(values).all():
        raise ValueError(
            f"The feature table's {name!r} column has missing or non-finite values, "
            "and the PCA does not guess them."
        )
    return values


def _fitted_wells(nuclei_counts: np.ndarray) -> np.ndarray:
    """Return which wells the PCA fits: every well that is not near-empty."""
    return nuclei_counts >= NEAR_EMPTY_NUCLEI_THRESHOLD


def pca_fit_report(table: FeatureTable) -> dict[str, Any]:
    """Describe which wells the PCA fits, for ``summary.json`` and the summary panel.

    Args:
        table: The loaded feature table, after the plate exclusion.

    Returns:
        The column and threshold that decide the fit, and how many wells it
        keeps and leaves out. The downloads keep every one of them.

    Raises:
        ValueError: If ``Count_nuclei`` is absent or incomplete.
    """
    fitted = _fitted_wells(_numeric_column(table, NUCLEI_COLUMN))
    return {
        "column": NUCLEI_COLUMN,
        "min_nuclei": NEAR_EMPTY_NUCLEI_THRESHOLD,
        "n_wells_fitted": int(fitted.sum()),
        "n_near_empty_wells": int((~fitted).sum()),
    }


def clip_figure_values(matrix: np.ndarray) -> np.ndarray:
    """Return the feature matrix clipped to the figure range.

    Args:
        matrix: Figure-basis feature values as delivered.

    Returns:
        The same values with anything beyond ``±FIGURE_CLIP_BOUND`` brought to
        the bound, which is where the authors' pipeline puts this step. The
        caller's array is left alone, so the frame the downloads are written
        from never sees the clip (FREYA-2968).
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
        than implying that it and the download set agree.
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
    to the computation — the channel exclusion, the clip bound, the PCA's
    near-empty threshold, the population names — would otherwise leave the key
    identical while the figures move, and the page would serve the previous
    render for a day (FREYA-3009, FREYA-3200).

    Args:
        feature_columns: The figure basis's column names.

    Returns:
        The figure column count, the clip bound, the near-empty threshold and
        the population-label digest, in that fixed order.
    """
    return (
        f"figure-basis:{len(feature_columns)}:{FIGURE_CLIP_BOUND}"
        f":min-nuclei-{NEAR_EMPTY_NUCLEI_THRESHOLD}"
        f":labels-{population_labels_token()}"
    )


def _prepare(table: FeatureTable, feature_columns: list[str]) -> _Prepared:
    """Clip the figure feature matrix and gather the per-row labels.

    Neither standardisation nor imputation is applied: the values arrive
    MAD-normalised per plate and carry no missing entries.
    ``numeric_matrix`` rejects an incomplete matrix, so no gap reaches a figure.
    The clip is the one transform applied here, and it happens after load and
    before any figure is computed — where the paper's methods put it.

    ``feature_columns`` is the figure basis, which is narrower than the table's
    own feature set: the infection-readout channel is excluded, so a morphology
    figure cannot be computed partly from the assay's own answer (FREYA-2923).
    The downloads keep every column, unclipped.

    Every row is kept here, near-empty wells included: only the PCA's fit leaves
    them out, so the radars average every well as before (FREYA-3200).

    Raises:
        ValueError: If ``Count_nuclei`` or ``cmpd_conc`` is absent or incomplete.
    """
    return _Prepared(
        matrix=clip_figure_values(table.numeric_matrix(feature_columns)),
        feature_columns=feature_columns,
        pert_types=_column_values(table, "pert_type"),
        cbkids=_column_values(table, "cbkid"),
        nuclei_counts=_numeric_column(table, NUCLEI_COLUMN),
        doses=_numeric_column(table, DOSE_COLUMN),
        n_download_features=len(table.feature_columns),
    )


def _pca_scores(data: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return the first two PC scores of ``data`` and each component's variance share.

    Only the column means are removed, which is what makes the decomposition a
    PCA and what the variance shares are measured against; the per-column
    scaling is not reapplied, matching the authors' ``PLSRegression(scale=False)``.
    Each component's sign is fixed (largest-magnitude loading forced positive) so
    the scores, and therefore the serialised figure, are reproducible.
    """
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
    return scores, explained


def _dose_marker_sizes(doses: np.ndarray) -> np.ndarray:
    """Return one marker size per dose, rising strictly with the dose's rank.

    Rank rather than value: the screen's doses are log-spaced from 0.1 to 30 µM,
    so a linear size would leave every dose below 10 µM indistinguishable.
    """
    levels = np.unique(doses)
    smallest, largest = PCA_DOSE_MARKER_SIZES
    steps = (
        np.linspace(smallest, largest, levels.size)
        if levels.size > 1
        else np.full(levels.size, (smallest + largest) / 2)
    )
    return steps[np.searchsorted(levels, doses)]


def _check_populations(pert_types: np.ndarray) -> None:
    """Fail when a population has no name or no place in the PCA's drawing order.

    Raises:
        ValueError: If a ``pert_type`` has no plain-language name
            (``radar.population_label``), or is named but not placed in
            ``PCA_POPULATION_ORDER`` — its wells would otherwise go undrawn.
    """
    unplaced = sorted(set(pert_types.tolist()) - set(PCA_POPULATION_ORDER))
    for token in unplaced:
        population_label(token)
    if unplaced:
        raise ValueError(
            f"pert_type value(s) {unplaced} have no place in the PCA's drawing order, "
            f"so their wells would go undrawn. Placed: {list(PCA_POPULATION_ORDER)}."
        )


@dataclass(frozen=True)
class _PcaFit:
    """One PCA fit, which every colouring draws.

    Attributes:
        scores: PC1 and PC2 of each fitted well.
        explained: Each component's share of the fitted wells' variance.
        pert_types: The fitted wells' ``pert_type``.
        cbkids: The fitted wells' ``cbkid``.
        doses: The fitted wells' ``cmpd_conc``.
        sizes: Each fitted well's marker size, by dose rank for a dosed well.
        antiviral: Which fitted wells are one of ``PCA_ANTIVIRALS``.
        dosed: Which fitted wells are sized by dose: treated and antiviral.
    """

    scores: np.ndarray
    explained: np.ndarray
    pert_types: np.ndarray
    cbkids: np.ndarray
    doses: np.ndarray
    sizes: np.ndarray
    antiviral: np.ndarray
    dosed: np.ndarray

    @property
    def treated(self) -> np.ndarray:
        """Return which fitted wells a colouring recolours: treated, not antiviral."""
        return (self.pert_types == TREATMENT_POPULATION) & ~self.antiviral


def _fit_pca(prep: _Prepared) -> _PcaFit:
    """Fit the PCA over the wells with at least ``NEAR_EMPTY_NUCLEI_THRESHOLD`` nuclei.

    PCA is computed via numpy SVD on the clipped figure basis (no sklearn).
    Near-empty wells are neither fitted nor drawn, and the axes autorange over
    what is drawn, so each axis's share is of the fitted wells' variation
    (FREYA-3200).

    Raises:
        ValueError: If a population has no plain-language name or no place in
            the drawing order, or if no well reaches the threshold.
    """
    _check_populations(prep.pert_types)
    fitted = _fitted_wells(prep.nuclei_counts)
    if not fitted.any():
        raise ValueError(
            f"No well has {NEAR_EMPTY_NUCLEI_THRESHOLD} or more nuclei, so the PCA has "
            "nothing to fit."
        )
    scores, explained = _pca_scores(prep.matrix[fitted])
    pert_types = prep.pert_types[fitted]
    cbkids = prep.cbkids[fitted]
    doses = prep.doses[fitted]

    antiviral = np.isin(cbkids, [cbkid for cbkid, _ in PCA_ANTIVIRALS])
    dosed = antiviral | (pert_types == TREATMENT_POPULATION)
    sizes = np.full(pert_types.shape[0], PCA_CONTROL_MARKER_SIZE)
    if dosed.any():
        sizes[dosed] = _dose_marker_sizes(doses[dosed])
    return _PcaFit(
        scores=scores,
        explained=explained,
        pert_types=pert_types,
        cbkids=cbkids,
        doses=doses,
        sizes=sizes,
        antiviral=antiviral,
        dosed=dosed,
    )


def _pca_trace(fit: _PcaFit, mask: np.ndarray, name: str, marker: dict[str, Any]) -> dict[str, Any]:
    """Return one PCA trace's ``add_scatter`` arguments: the masked wells, as markers."""
    return {
        "x": fit.scores[mask, 0],
        "y": fit.scores[mask, 1],
        "mode": "markers",
        "name": name,
        "marker": marker,
    }


def _treated_marker(fit: _PcaFit, mask: np.ndarray, colour: object) -> dict[str, Any]:
    """Return a treated trace's marker: its colour, sized by dose like every treated well."""
    return {"color": colour, "size": fit.sizes[mask], "opacity": _PCA_MARKER_OPACITY}


def _population_traces(fit: _PcaFit) -> list[dict[str, Any]]:
    """Return the default view's treated trace: every treated well in one pale grey."""
    mask = fit.treated
    if not mask.any():
        return []
    colour = PCA_POPULATION_COLOURS[TREATMENT_POPULATION]
    return [
        _pca_trace(
            fit, mask, population_label(TREATMENT_POPULATION), _treated_marker(fit, mask, colour)
        )
    ]


def _finite_score(value: float | None) -> float:
    """Return a score, or NaN when it is missing or not a finite number."""
    if value is None or not math.isfinite(value):
        return math.nan
    return float(value)


def _morphology_traces(
    fit: _PcaFit, scores: Mapping[str, float | None]
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Return the morphology view's treated traces and how many compounds it scored.

    Each treated well takes its compound's score as the compound table shows it.
    A compound with no score is one grey "Not reported" trace at the bottom, never
    a zero on the scale.
    """
    values = np.array([_finite_score(scores.get(cbkid)) for cbkid in fit.cbkids])
    scored = fit.treated & np.isfinite(values)
    unscored = fit.treated & ~np.isfinite(values)

    traces = []
    if unscored.any():
        marker = _treated_marker(fit, unscored, _PCA_MISSING_COLOUR)
        traces.append(_pca_trace(fit, unscored, PCA_NOT_REPORTED, marker))
    if scored.any():
        marker = {
            **_treated_marker(fit, scored, values[scored]),
            "colorscale": _PCA_MORPHOLOGY_COLOURSCALE,
            "showscale": True,
            "colorbar": _PCA_COLOUR_BAR,
        }
        traces.append(_pca_trace(fit, scored, PCA_MORPHOLOGY_TRACE, marker))
    report = {
        "n_compounds_scored": len(set(fit.cbkids[scored].tolist())),
        "n_compounds_not_reported": len(set(fit.cbkids[unscored].tolist())),
    }
    return traces, report


def _mechanism(value: object) -> str | None:
    """Return a ``broad_moa`` as written, or ``None`` when it names nothing."""
    return value if isinstance(value, str) and value.strip() else None


def _moa_traces(
    fit: _PcaFit, mechanisms: Mapping[str, str | None]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return the mechanism view's treated traces and the groups it coloured.

    A pipe-joined ``broad_moa`` is a group of its own. Groups rank by how many of
    the drawn compounds they hold, ties by name; the top ``PCA_MOA_GROUPS`` take
    ``PCA_MOA_COLOURS`` in that order, every other group is "Other mechanisms",
    and a compound with none is "Not annotated". Both buckets are drawn first, so
    no coloured group hides under them.
    """
    group_of = {
        cbkid: _mechanism(mechanisms.get(cbkid)) for cbkid in set(fit.cbkids[fit.treated].tolist())
    }
    counts = Counter(group for group in group_of.values() if group is not None)
    ranked = sorted(counts, key=lambda group: (-counts[group], group))[:PCA_MOA_GROUPS]

    def bucket(cbkid: str) -> str:
        group = group_of.get(cbkid)
        if group is None:
            return PCA_NOT_ANNOTATED
        return group if group in ranked else PCA_OTHER_MECHANISMS

    labels = np.array([bucket(cbkid) if cbkid in group_of else "" for cbkid in fit.cbkids])
    traces = []
    for name, colour in (
        (PCA_NOT_ANNOTATED, _PCA_MISSING_COLOUR),
        (PCA_OTHER_MECHANISMS, _PCA_OTHER_MECHANISMS_COLOUR),
        *zip(ranked, PCA_MOA_COLOURS, strict=False),
    ):
        mask = fit.treated & (labels == name)
        if mask.any():
            traces.append(_pca_trace(fit, mask, name, _treated_marker(fit, mask, colour)))
    return traces, ranked


def _dose_label(dose: float) -> str:
    """Return a dose as the figures write it, for example "0.1 µM"."""
    return f"{dose:g} {DOSE_UNIT}"


def _size_key_traces(fit: _PcaFit) -> list[dict[str, Any]]:
    """Return the size key: the smallest and the largest dose marker, each named by its dose.

    Each is a trace with no point, so it adds a legend entry and nothing to the
    plot. A fit drawn at one dose has one entry, and one with no dosed well none.
    """
    if not fit.dosed.any():
        return []
    doses = fit.doses[fit.dosed]
    sizes = fit.sizes[fit.dosed]
    ends = sorted({float(doses.min()), float(doses.max())})
    return [
        {
            "x": [None],
            "y": [None],
            "mode": "markers",
            "name": _dose_label(dose),
            "legendgroup": PCA_SIZE_KEY_GROUP,
            "legendgrouptitle": {"text": PCA_SIZE_KEY_TITLE},
            "legendrank": _PCA_SIZE_KEY_RANK,
            "hoverinfo": "skip",
            "marker": {
                "symbol": "circle-open",
                "color": PCA_OVERLAY_COLOUR,
                "size": float(sizes[doses == dose][0]),
                "line": {"width": 1},
            },
        }
        for dose in ends
    ]


def _pca_legend(colouring: str, *, below_colour_bar: bool) -> dict[str, Any]:
    """Return a view's legend: titled by its colouring, below the plot, in the pinned margin."""
    top = _PCA_MARGIN_BOTTOM - _PCA_AXIS_ROOM
    if below_colour_bar:
        top -= _PCA_COLOUR_BAR_ROOM
    return {
        "title": {"text": PCA_LEGEND_TITLES[colouring], "side": "top"},
        "orientation": "h",
        "x": 0,
        "xanchor": "left",
        "xref": "container",
        "y": top / PCA_FIGURE_HEIGHT,
        "yanchor": "top",
        "yref": "container",
        "maxheight": top,
    }


def _draw_pca(fit: _PcaFit, treated_traces: list[dict[str, Any]], colouring: str) -> go.Figure:
    """Draw one view of the fit: its treated traces, then the controls and antivirals on top.

    Traces run bottom to top: the view's own treated traces, then the rest of
    ``PCA_POPULATION_ORDER``, then the three ``PCA_ANTIVIRALS``, each control and
    antiviral in its fixed colour, so they are identical in every view.
    Populations are named by ``radar.population_label`` rather than by their raw
    ``pert_type`` token (FREYA-3009); an antiviral's wells leave their population
    at every dose. A treated or antiviral well's marker grows with its dose, the
    controls keep one size, and the subtitle and the size key say so. The legend
    is titled by the colouring (``PCA_LEGEND_TITLES``), and the toolbar offers no
    selection tool.
    """
    figure = go.Figure()
    for trace in treated_traces:
        figure.add_scatter(**trace)
    for token in PCA_POPULATION_ORDER:
        mask = (fit.pert_types == token) & ~fit.antiviral
        if token == TREATMENT_POPULATION or not mask.any():
            continue
        marker = {
            "color": PCA_POPULATION_COLOURS[token],
            "size": PCA_CONTROL_MARKER_SIZE,
            "opacity": _PCA_MARKER_OPACITY,
        }
        figure.add_scatter(**_pca_trace(fit, mask, population_label(token), marker))
    for cbkid, name in PCA_ANTIVIRALS:
        mask = fit.cbkids == cbkid
        if not mask.any():
            continue
        marker = {
            "color": PCA_ANTIVIRAL_COLOUR,
            "size": fit.sizes[mask],
            "opacity": _PCA_ANTIVIRAL_OPACITY,
            "line": {"color": PCA_ANTIVIRAL_OUTLINE, "width": 1},
        }
        figure.add_scatter(**_pca_trace(fit, mask, name, marker))
    for trace in _size_key_traces(fit):
        figure.add_scatter(**trace)

    title: dict[str, Any] = {"text": "PCA of well-level morphological profiles"}
    if fit.dosed.any():
        doses = fit.doses[fit.dosed]
        title["subtitle"] = {
            "text": (
                f"Marker size shows dose: larger is higher, from {doses.min():g} "
                f"to {doses.max():g} {DOSE_UNIT}"
            )
        }
    figure.update_layout(
        title=title,
        xaxis_title=f"PC1 ({fit.explained[0] * 100:.1f}% of the fitted wells' variance)",
        yaxis_title=f"PC2 ({fit.explained[1] * 100:.1f}% of the fitted wells' variance)",
        legend=_pca_legend(
            colouring,
            below_colour_bar=any(trace["marker"].get("showscale") for trace in treated_traces),
        ),
        margin={"t": _PCA_MARGIN_TOP, "b": _PCA_MARGIN_BOTTOM},
        modebar={"remove": list(PCA_MODEBAR_REMOVED)},
        plot_bgcolor="white",
    )
    return figure


def build_pca_views(
    prep: _Prepared,
    *,
    morphology_scores: Mapping[str, float | None] | None = None,
    mechanisms: Mapping[str, str | None] | None = None,
) -> tuple[dict[str, go.Figure], dict[str, Any]]:
    """Fit the PCA once and draw it in every colouring there is something to draw by.

    Args:
        prep: The prepared figure inputs.
        morphology_scores: ``cbkid`` to the compound table's morphology score.
            ``None`` when precompute built no table, which leaves the morphology
            view unbuilt rather than every well "Not reported".
        mechanisms: ``cbkid`` to the compound index's ``broad_moa``.

    Returns:
        The views keyed by colouring, in ``PCA_COLOURINGS`` order, and a report
        for ``summary.json``: the colourings written, how many drawn compounds
        the morphology view scored, and the mechanism groups it coloured.

    Raises:
        ValueError: As ``_fit_pca``.
    """
    return _pca_views(_fit_pca(prep), morphology_scores=morphology_scores, mechanisms=mechanisms)


def _pca_views(
    fit: _PcaFit,
    *,
    morphology_scores: Mapping[str, float | None] | None,
    mechanisms: Mapping[str, str | None] | None,
) -> tuple[dict[str, go.Figure], dict[str, Any]]:
    """Draw one fit in every colouring there is something to draw by (``build_pca_views``)."""
    views = {PCA_DEFAULT_COLOURING: _draw_pca(fit, _population_traces(fit), PCA_DEFAULT_COLOURING)}
    report: dict[str, Any] = {}
    if morphology_scores is not None:
        traces, report["morphology"] = _morphology_traces(fit, morphology_scores)
        views["morphology"] = _draw_pca(fit, traces, "morphology")
    traces, report["moa_groups"] = _moa_traces(fit, mechanisms or {})
    views["moa"] = _draw_pca(fit, traces, "moa")

    ordered = {colouring: views[colouring] for colouring in PCA_COLOURINGS if colouring in views}
    return ordered, {"written": list(ordered), **report}


def _pca_overlay(fit: _PcaFit, cbkid: str, name: str) -> go.Figure:
    """Draw one compound's overlay: its fitted wells, then a line through its dose centroids.

    The wells keep the size every view gives them, and each centroid takes its
    dose's size, so the line reads from low dose to high. A centroid is the mean
    PC1 and PC2 of the compound's fitted wells at one dose; the line joins them in
    ascending dose, over a white halo that keeps it visible on dark points, and
    names its lowest and highest dose beside the first and last centroid. The
    halo is no legend entry of its own: it shares the line's legend group, so
    hiding the line hides it too. No trace depends on a colouring, so the overlay
    can be drawn over any view of the same fit.

    Args:
        fit: The PCA fit every view draws.
        cbkid: The compound, which has at least one fitted dosed well.
        name: The compound's name in the legend.

    Returns:
        A figure holding three traces: the wells, the halo, then the line.
    """
    mask = fit.dosed & (fit.cbkids == cbkid)
    doses = fit.doses[mask]
    scores = fit.scores[mask]
    sizes = fit.sizes[mask]
    levels = np.unique(doses)
    centroids = np.array([scores[doses == level].mean(axis=0) for level in levels])
    outline = {"color": PCA_OVERLAY_HALO_COLOUR, "width": 1}
    line_name = f"{name}{PCA_OVERLAY_CENTROID_SUFFIX}"
    line_group = f"pca-overlay-{cbkid}"

    figure = go.Figure()
    figure.add_scatter(
        **_pca_trace(fit, mask, name, {"color": PCA_OVERLAY_COLOUR, "size": sizes, "line": outline})
    )
    figure.add_scatter(
        x=centroids[:, 0],
        y=centroids[:, 1],
        mode="lines",
        name=line_name,
        legendgroup=line_group,
        showlegend=False,
        hoverinfo="skip",
        line={"color": PCA_OVERLAY_HALO_COLOUR, "width": _PCA_OVERLAY_HALO_WIDTH},
    )
    dose_labels = [""] * levels.size
    dose_labels[0] = _dose_label(levels[0])
    dose_labels[-1] = _dose_label(levels[-1])
    label_positions = ["top center"] * levels.size
    if levels.size > 1:
        across, up = centroids[-1] - centroids[0]
        label_positions[0] = f"{'bottom' if up > 0 else 'top'} {'left' if across > 0 else 'right'}"
        label_positions[-1] = f"{'top' if up > 0 else 'bottom'} {'right' if across > 0 else 'left'}"
    figure.add_scatter(
        x=centroids[:, 0],
        y=centroids[:, 1],
        mode="lines+markers+text",
        name=line_name,
        legendgroup=line_group,
        text=dose_labels,
        textposition=label_positions,
        textfont=_PCA_DOSE_LABEL_FONT,
        cliponaxis=False,
        line={"color": PCA_OVERLAY_COLOUR, "width": _PCA_OVERLAY_LINE_WIDTH},
        marker={
            "symbol": "diamond",
            "color": PCA_OVERLAY_COLOUR,
            "size": np.array([sizes[doses == level][0] for level in levels]),
            "line": outline,
        },
    )
    return figure


def _pca_overlays(fit: _PcaFit, labels: Mapping[str, str]) -> dict[str, go.Figure]:
    """Draw an overlay for every compound with at least one fitted treated or antiviral well.

    A compound whose wells are all near-empty is not fitted, so it gets none, and
    neither do the controls, whose wells are not dosed. The antivirals keep the
    fixed names their own traces carry (``PCA_ANTIVIRALS``); every other compound
    is named as the page's picker names it.
    """
    antiviral_names = dict(PCA_ANTIVIRALS)
    return {
        cbkid: _pca_overlay(fit, cbkid, antiviral_names.get(cbkid) or labels.get(cbkid) or cbkid)
        for cbkid in sorted(set(fit.cbkids[fit.dosed].tolist()))
    }


def _faded(trace: dict[str, Any]) -> dict[str, Any]:
    """Return a view's trace drawn at ``PCA_FADED_OPACITY_SHARE`` of its opacity.

    The size key is a key, not a colouring, so it keeps its opacity.
    """
    marker = trace.get("marker")
    if not isinstance(marker, dict) or trace.get("legendgroup") == PCA_SIZE_KEY_GROUP:
        return trace
    opacity = round(marker.get("opacity", 1) * PCA_FADED_OPACITY_SHARE, 6)
    return {**trace, "marker": {**marker, "opacity": opacity}}


def combine_pca_overlay(view: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Return a PCA view with one compound's overlay drawn above every trace it has.

    Args:
        view: One colouring's precomputed figure JSON.
        overlay: One compound's precomputed overlay, which carries ``data`` only.

    Returns:
        The view with its layout unchanged, its own traces fainter so the overlay
        reads first, and the overlay's traces appended last, since Plotly draws a
        later trace over an earlier one. With no compound the view is served as
        it is, so this is never applied to it.
    """
    return {
        **view,
        "data": [*map(_faded, view.get("data", [])), *overlay.get("data", [])],
    }


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
    against and the uninfected profiles carry the infection contrast (measured
    0.0871 against 1.2661 on the real table).
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
            so precompute chooses no compound.
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
            single ``JSONField`` that is deserialised whole to render one figure.
        radars: One radar per compound with treated wells, keyed by ``cbkid``.
            These go to disk and are served by the figure-swap route.
        axes: The radar ring this run plotted, for the run's own report.
        unplotted_columns: Figure-basis columns no axis averages.
        pca_colourings: The PCA's colourings other than the default, keyed by
            colouring. These go to disk under ``figures/pca/`` and are served by
            the PCA's swap route; the default is ``figures["pca"]``.
        pca_report: What the colourings wrote, for ``summary.json``
            (``build_pca_views``).
        pca_overlays: One overlay per compound with a fitted treated or
            antiviral well, keyed by ``cbkid``: its wells and its dose line,
            ``data`` only. These go to disk under ``figures/pca/compound/``, and
            the PCA's swap route draws one over the colouring shown
            (``combine_pca_overlay``).
    """

    figures: dict[str, Any]
    radars: dict[str, Any]
    axes: list[RadarAxis]
    unplotted_columns: list[str]
    pca_colourings: dict[str, Any]
    pca_report: dict[str, Any]
    pca_overlays: dict[str, Any]


def build_figure_bundle(
    table: FeatureTable,
    *,
    feature_columns: list[str],
    channels: tuple[Channel, ...],
    compound_labels: dict[str, str] | None = None,
    morphology_scores: Mapping[str, float | None] | None = None,
    mechanisms: Mapping[str, str | None] | None = None,
) -> FigureBundle:
    """Build the snippet's figures and the per-compound radar and PCA overlay sets in one pass.

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
            per-compound radar's title and each PCA overlay's legend.
        morphology_scores: Optional ``cbkid`` to the compound table's morphology
            score; the morphology colouring is built only when it is given.
        mechanisms: Optional ``cbkid`` to ``broad_moa``, for the mechanism
            colouring.

    Returns:
        The bundle. Its ``figures`` always contain ``FEATURE_BASIS_FIGURE_IDS``.

    Raises:
        ValueError: If a radar population is empty (``radar.axis_values``).
    """
    prep = _prepare(table, feature_columns)
    axes = build_ring(feature_columns, channels)
    labels = compound_labels or {}
    fit = _fit_pca(prep)
    pca_views, pca_report = _pca_views(
        fit, morphology_scores=morphology_scores, mechanisms=mechanisms
    )

    figures: dict[str, Any] = {
        "pca": _to_json(pca_views[PCA_DEFAULT_COLOURING]),
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
        pca_colourings={
            colouring: _to_json(view)
            for colouring, view in pca_views.items()
            if colouring != PCA_DEFAULT_COLOURING
        },
        pca_report=pca_report,
        pca_overlays={
            cbkid: {"data": _to_json(overlay)["data"]}
            for cbkid, overlay in _pca_overlays(fit, labels).items()
        },
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
