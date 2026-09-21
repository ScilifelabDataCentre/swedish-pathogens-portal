"""Figure 3C's radar axis ring and its populations (spec section 6, FREYA-2636).

The published radar groups the feature table's columns into one ordered ring of
axes and plots, per axis, how far a condition sits from the plate's DMSO
baseline. Both halves are settled measurements rather than choices of ours: the
ring comes from the author's own ``radarplots.ipynb``
(``plans/DRR/reference/data-sources.md`` DS-8), and the statistic is that
notebook's — the mean per feature within the condition, then the absolute value,
then the mean within each axis group, with **no subtraction of a control mean**,
because the input arrives MAD-normalised against each plate's DMSO wells and the
absolute mean therefore already *is* the deviation from control.

The ring is structural: which stain groups it carries follows from the screen's
own channel map, so this module consumes ``channels`` rather than restating which
token images which stain. For the A549-ACE2 validation screen's four morphology
channels that yields **24 axes** — ``Children`` 1, area/shape by compartment 3,
four stain groups x intensity/granularity/radial distribution 12, neighbours 2,
and the six correlation pairs of those stains.

``Location``, ``Parent_*`` and ``Count_nuclei`` carry no axis. The notebook has
no branch for them, so they fall to its ``"Uncategorized"`` bucket and are
dropped; ``Count_nuclei`` never reaches here at all, being metadata rather than a
feature (``loader.METADATA_COLUMNS``).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import combinations

import numpy as np

from .channels import Channel

# The perturbation labels the two radars contrast. ``negcon`` is the infected
# DMSO population the input is normalised against — its own absolute mean is
# therefore ~0 by construction (measured: 0.0871 against non-inf's 1.2661) — so
# it is the baseline the radars are read against and never a plotted condition.
BASELINE_POPULATION = "negcon"
INFECTED_POPULATION = "non-inf"
TREATMENT_POPULATION = "trt"

# Compartments carrying their own area/shape and neighbours axes, in ring order,
# with the notebook's own short labels (``C``, ``CY``, ``N``).
_AREA_SHAPE_COMPARTMENTS: tuple[tuple[str, str], ...] = (
    ("cells", "C"),
    ("cytoplasm", "CY"),
    ("nuclei", "N"),
)
_NEIGHBORS_COMPARTMENTS: tuple[tuple[str, str], ...] = (("cells", "C"), ("nuclei", "N"))

# The three per-stain measurement modules, with the notebook's own short labels.
_STAIN_MODULES: tuple[tuple[str, str], ...] = (
    ("Intensity", "I"),
    ("Granularity", "G"),
    ("RadialDistribution", "RD"),
)

# Column-name families that carry no axis at all (DS-8 item 1).
UNPLOTTED_PREFIXES: tuple[str, ...] = ("Location", "Parent")

# Everything outside this set is replaced in an artefact key; a key that had to
# be rewritten also carries a digest of the raw id, so two ids cannot collide on
# one file (``[stau]`` and ``stau`` would otherwise share it).
_UNSAFE_KEY_CHARS = re.compile(r"[^A-Za-z0-9_-]+")
_KEY_DIGEST_LENGTH = 8


@dataclass(frozen=True)
class RadarAxis:
    """One spoke of the radar ring.

    Attributes:
        label: The axis label as plotted, in the notebook's vocabulary
            (``DNA I``, ``Area/shape C``, ``DNA-RNA``).
        columns: The figure-basis columns averaged into this axis, which is
            empty when the table carries none of them.
        indices: The same columns as positions in the figure basis, so a builder
            can slice the feature matrix without a second name lookup.
    """

    label: str
    columns: tuple[str, ...]
    indices: tuple[int, ...]


def _stain_groups(channels: tuple[Channel, ...]) -> list[Channel]:
    """Return the channels carrying a stain group, in the map's display order."""
    return [channel for channel in channels if channel.in_figures]


def _axis(
    label: str,
    feature_columns: list[str],
    predicate: object,
) -> RadarAxis:
    """Bind one axis to the figure-basis columns that belong to it."""
    matched = [
        (index, column)
        for index, column in enumerate(feature_columns)
        if predicate(column)  # type: ignore[operator]
    ]
    return RadarAxis(
        label=label,
        columns=tuple(column for _, column in matched),
        indices=tuple(index for index, _ in matched),
    )


def _is_module(column: str, module: str) -> bool:
    """Return whether a column belongs to a CellProfiler measurement module."""
    return column.split("_", 1)[0] == module


def _names_channel(column: str, channel: Channel) -> bool:
    """Return whether a column names one channel's token as a whole segment."""
    return f"_{channel.column_tag}_" in column


def build_ring(feature_columns: list[str], channels: tuple[Channel, ...]) -> list[RadarAxis]:
    """Build Figure 3C's ordered axis ring over the figure basis.

    Args:
        feature_columns: The figure basis — the morphology columns the figures
            compute on, aligned with the feature matrix's columns.
        channels: This screen's channel map. The stain groups are its in-figure
            channels, in its own display order, so the ring cannot disagree with
            the vocabulary the page publishes.

    Returns:
        The ring, in plotting order: ``Children``, area/shape by compartment,
        each stain group's three modules, neighbours by compartment, then the
        stain-pair correlations. An axis whose columns are absent from this table
        is kept in the ring and carries none, so the ring's shape describes the
        screen rather than the rows that happened to be loaded.
    """
    stains = _stain_groups(channels)
    axes = [
        _axis("Children N", feature_columns, lambda column: _is_module(column, "Children")),
        *(
            _axis(
                f"Area/shape {short}",
                feature_columns,
                lambda column, compartment=compartment: (
                    _is_module(column, "AreaShape") and column.endswith(f"_{compartment}")
                ),
            )
            for compartment, short in _AREA_SHAPE_COMPARTMENTS
        ),
        *(
            _axis(
                f"{stain.stain_group} {short}",
                feature_columns,
                lambda column, module=module, stain=stain: (
                    _is_module(column, module) and _names_channel(column, stain)
                ),
            )
            for stain in stains
            for module, short in _STAIN_MODULES
        ),
        *(
            _axis(
                f"Neighbors {short}",
                feature_columns,
                lambda column, compartment=compartment: (
                    _is_module(column, "Neighbors") and column.endswith(f"_{compartment}")
                ),
            )
            for compartment, short in _NEIGHBORS_COMPARTMENTS
        ),
        *(
            _axis(
                f"{first.stain_group}-{second.stain_group}",
                feature_columns,
                lambda column, first=first, second=second: (
                    _is_module(column, "Correlation")
                    and _names_channel(column, first)
                    and _names_channel(column, second)
                ),
            )
            for first, second in combinations(stains, 2)
        ),
    ]
    return axes


def unplotted_columns(feature_columns: list[str], axes: list[RadarAxis]) -> list[str]:
    """Return the figure-basis columns the ring leaves out.

    Args:
        feature_columns: The figure basis.
        axes: The ring built over it.

    Returns:
        The columns no axis averages — the ``Location`` and ``Parent_*``
        families the notebook drops, and anything a future export adds that this
        ring does not yet describe. Reported rather than silently ignored, so a
        grown input shows up as a number instead of as a quietly thinner figure.
    """
    plotted = {column for axis in axes for column in axis.columns}
    return [column for column in feature_columns if column not in plotted]


def axis_values(
    matrix: np.ndarray,
    axes: list[RadarAxis],
    row_mask: np.ndarray,
) -> list[float | None]:
    """Compute the published radar statistic for one condition.

    The mean per feature within the condition's rows, then the absolute value,
    then the mean within each axis group (DS-8 item 4). No control mean is
    subtracted: the values arrive MAD-normalised against each plate's DMSO, so
    the absolute mean is already the deviation from that baseline.

    Args:
        matrix: The clipped figure-basis feature matrix.
        axes: The ring, whose indices address ``matrix``'s columns.
        row_mask: Which rows belong to the condition.

    Returns:
        One value per axis, and ``None`` for an axis this table gives no column
        — a gap in the ring rather than a measured zero.

    Raises:
        ValueError: If the condition selects no row. A radar of the whole table
            is not the figure that was asked for, so an empty population stops
            the run instead of quietly widening (FREYA-2636 criterion 6).
    """
    if not bool(row_mask.any()):
        raise ValueError("Radar condition selects no profile, so it has no mean to plot.")

    per_feature = np.abs(matrix[row_mask].mean(axis=0))
    return [
        float(per_feature[list(axis.indices)].mean()) if axis.indices else None for axis in axes
    ]


def require_populations(pert_types: Iterable[str]) -> None:
    """Fail the run when a population either radar contrasts is absent.

    Args:
        pert_types: The table's per-row ``pert_type`` labels.

    Raises:
        ValueError: If the baseline, infected or treatment population is
            missing. Falling back to every profile would publish a radar of
            something else under the published figure's name (criterion 6).
    """
    present = {str(value) for value in pert_types}
    missing = [
        population
        for population in (BASELINE_POPULATION, INFECTED_POPULATION, TREATMENT_POPULATION)
        if population not in present
    ]
    if missing:
        raise ValueError(
            f"The feature table has no {', '.join(missing)} profile(s), so the radars of "
            "spec section 6 cannot be computed against the population they contrast. "
            f"Found pert_type value(s): {sorted(present)}."
        )


def artefact_key(cbkid: str) -> str:
    """Return the per-compound radar's on-disk key for one compound id.

    Compound ids are not filename-safe — control placeholders read ``[stau]`` —
    so the key is sanitised here, by precompute, and recorded in the compound
    index. The route looks it up there rather than deriving it from a request
    value (spec section 8.3).

    Args:
        cbkid: The compound id exactly as the feature table carries it.

    Returns:
        The key, which is the id itself when it is already safe, and otherwise a
        rewritten form carrying a digest of the raw id so no two ids can claim
        one file.
    """
    safe = _UNSAFE_KEY_CHARS.sub("_", cbkid).strip("_-")
    if safe == cbkid:
        return safe
    digest = hashlib.sha256(cbkid.encode("utf-8")).hexdigest()[:_KEY_DIGEST_LENGTH]
    return f"{safe}_{digest}" if safe else digest
