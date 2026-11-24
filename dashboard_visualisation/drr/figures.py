"""Server-side Plotly figures for a DRR dataset (ADR-0004).

All figures are computed offline from the feature matrix and serialised to Plotly
JSON. The input arrives MAD-normalised per plate against that plate's DMSO wells,
which is the only normalisation applied to it; values are therefore in the
authors' MAD units throughout. They are computed on the **figure
basis** — the morphology columns, with the screen's infection-readout channel
excluded (``channels``, FREYA-2923), clipped to ``FIGURE_CLIP_BOUND`` as the
published pipeline does (FREYA-2968) — while the downloads carry every column
exactly as delivered. The PCA alone also leaves out the near-empty wells
(``NEAR_EMPTY_NUCLEI_THRESHOLD``, FREYA-3200); the radars keep every well. Trace
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

    Every row is kept here, near-empty wells included: only ``build_pca`` leaves
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


def build_pca(prep: _Prepared) -> go.Figure:
    """Build a PC1/PC2 scatter of the fitted well-level profiles.

    PCA is computed via numpy SVD on the clipped figure basis (no sklearn), over
    the wells with at least ``NEAR_EMPTY_NUCLEI_THRESHOLD`` nuclei. Near-empty
    wells are neither fitted nor drawn, and the axes autorange over what is
    drawn, so each axis's share is of the fitted wells' variation (FREYA-3200).

    Traces run bottom to top in ``PCA_POPULATION_ORDER``, then the three
    ``PCA_ANTIVIRALS``, each in its fixed colour. Populations are named by
    ``radar.population_label`` rather than by their raw ``pert_type`` token
    (FREYA-3009); an antiviral's wells leave their population at every dose. A
    treated or antiviral well's marker grows with its dose, the controls keep
    one size, and the subtitle says so.

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

    figure = go.Figure()
    for token in PCA_POPULATION_ORDER:
        mask = (pert_types == token) & ~antiviral
        if not mask.any():
            continue
        figure.add_scatter(
            x=scores[mask, 0],
            y=scores[mask, 1],
            mode="markers",
            name=population_label(token),
            marker={
                "color": PCA_POPULATION_COLOURS[token],
                "size": sizes[mask] if token == TREATMENT_POPULATION else PCA_CONTROL_MARKER_SIZE,
                "opacity": _PCA_MARKER_OPACITY,
            },
        )
    for cbkid, name in PCA_ANTIVIRALS:
        mask = cbkids == cbkid
        if not mask.any():
            continue
        figure.add_scatter(
            x=scores[mask, 0],
            y=scores[mask, 1],
            mode="markers",
            name=name,
            marker={
                "color": PCA_ANTIVIRAL_COLOUR,
                "size": sizes[mask],
                "opacity": _PCA_ANTIVIRAL_OPACITY,
                "line": {"color": PCA_ANTIVIRAL_OUTLINE, "width": 1},
            },
        )

    title: dict[str, Any] = {"text": "PCA of well-level morphological profiles"}
    if dosed.any():
        title["subtitle"] = {
            "text": (
                f"Marker size shows dose: larger is higher, from {doses[dosed].min():g} "
                f"to {doses[dosed].max():g} {DOSE_UNIT}"
            )
        }
    figure.update_layout(
        title=title,
        xaxis_title=f"PC1 ({explained[0] * 100:.1f}% of the fitted wells' variance)",
        yaxis_title=f"PC2 ({explained[1] * 100:.1f}% of the fitted wells' variance)",
        legend_title=POPULATION_LEGEND_TITLE,
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
