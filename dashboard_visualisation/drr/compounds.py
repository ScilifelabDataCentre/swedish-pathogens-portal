"""Build the CBCS compound index by joining feature cbkids to metadata.

The feature table and the CBCS metadata TSV do not key ``cbkid`` identically:
the feature table encodes salt/form variants with a trailing letter suffix
(e.g. ``CBK008271G``) while the metadata keys on the bare stem (``CBK008271``).
The join therefore happens on a normalised stem so a variant inherits its base
compound's annotation, while the original ``cbkid`` is kept as the compound
identity (profile counts and per-``cbkid`` downloads are unchanged). Non-CBCS
tokens (control placeholders like ``[stau]`` or foreign ids like ``DO8167002``)
have no stem and never join (FREYA-2557).

Whether an id is a compound or a control is read from its wells' ``pert_type``,
never from the shape of the id (FREYA-3126): DMSO's vehicle id ``CBK281357`` is
CBCS-shaped but holds only control wells, and Nirmatrelvir's ``DO8167002`` is
prefixless but treated.

The index can carry a second, independent naming system: ``pert_iname``, the
authors' own compound name, read from the companion repository's Arrow file as a
lookup over its hit set (FREYA-2628). It is never merged into ``name`` — that is
the CBCS annotation dictionary's name, and only ``pert_iname`` is expected to
join the paper's Table S8. Because the lookup keys on the same ids the feature
table uses, it joins on the raw ``cbkid`` rather than on the stem. Only what a
reader is shown falls back to it, through one rule (``compound_name``): a
compound's display label (``compound_label``) and the compound table's Name.
"""

from __future__ import annotations

import re
from typing import Any

import polars as pl
import structlog

from .loader import FeatureTable

LOGGER = structlog.get_logger(__name__)

# Compound-level annotation columns pulled from the BIA metadata TSV.
_METADATA_FIELDS = ["cbkid", "name", "broad_moa", "broad_target"]

# A CBCS cbkid is "CBK" + digits, optionally followed by a salt/form letter
# suffix in the feature table (e.g. CBK008271G). The bare stem is the join key.
_CBKID_STEM_PATTERN = r"^(CBK\d+)"
_CBKID_STEM = re.compile(_CBKID_STEM_PATTERN)

# The authors' own compound-name column, carried by the name lookup only.
COMPOUND_NAME_COLUMN = "pert_iname"

# Perturbation types whose rows name a condition rather than a compound. On
# ``CBK281357`` — the negative-control id, absent from the CBCS metadata and
# holding 2,049 of our wells — ``pert_iname`` mirrors ``pert_type`` and reads
# ``DMSO`` or ``non-inf``. Dropping these rows before reducing to one name per
# id is what makes the mapping a strict function (324 ids, 324 names); keeping
# them would stamp 640 non-infected wells ``DMSO`` (FREYA-2628).
_CONDITION_PERT_TYPES = ["negcon", "non-inf"]

# An id is a compound when any of its wells is treated, and a control when every
# one of its wells is one of the control types.
_TREATMENT_PERT_TYPE = "trt"
_CONTROL_PERT_TYPES = [*_CONDITION_PERT_TYPES, "poscon"]

# Compound index column order (annotation columns appended when available).
_INDEX_COLUMNS = [
    "cbkid",
    "cbkid_normalized",
    "kind",
    "n_profiles",
    "name",
    "broad_moa",
    "broad_target",
    COMPOUND_NAME_COLUMN,
]


def normalize_cbkid(value: str | None) -> str | None:
    """Return the canonical CBCS stem of a ``cbkid``, or ``None`` if it has none.

    Strips a trailing salt/form suffix so a variant (``CBK008271G``) reconciles
    with its base compound (``CBK008271``). Non-CBCS tokens (control
    placeholders like ``[stau]``, foreign ids like ``DO8167002``) and empty
    values return ``None`` so they never join.

    Args:
        value: A raw ``cbkid`` from the feature table or the metadata.

    Returns:
        The ``CBK`` + digits stem, or ``None`` for non-CBCS / empty values.
    """
    if not value:
        return None
    match = _CBKID_STEM.match(value)
    return match.group(1) if match else None


def build_compound_index(
    table: FeatureTable,
    metadata: pl.DataFrame,
    names: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """Build a per-compound index for the dataset.

    Groups the feature table by its original ``cbkid`` (the compound identity),
    derives a normalised stem, classifies each id from its wells' ``pert_type``
    — ``compound`` with at least one ``trt`` well, ``control`` when every well is
    ``negcon``, ``non-inf`` or ``poscon`` — and left-joins the CBCS ``name`` /
    ``broad_moa`` / ``broad_target`` annotations on the stem so salt/form
    variants inherit their base compound's annotation. When a name lookup is
    supplied its ``pert_iname`` is joined on the raw ``cbkid`` and appended
    last; ids outside the lookup keep an explicit null rather than being
    dropped.

    Args:
        table: The loaded feature table; needs ``cbkid`` and ``pert_type``.
        metadata: The loaded compound metadata (see ``load_metadata``).
        names: Optional name lookup (see ``load_compound_names``); omitted, the
            index carries no ``pert_iname`` column at all.

    Returns:
        A DataFrame with one row per original ``cbkid`` (``cbkid``,
        ``cbkid_normalized``, ``kind``, ``n_profiles``, and the available
        annotation columns), sorted by ``cbkid``.

    Raises:
        ValueError: If the table has no ``pert_type`` column, or an id has no
            ``trt`` well and a well whose ``pert_type`` is null or not a control
            type — it is then neither kind, and is named rather than guessed.
    """
    if "pert_type" not in table.frame.columns:
        raise ValueError(
            "The feature table has no 'pert_type' column, which decides whether an id is a "
            "compound or a control."
        )
    counts = (
        table.frame.group_by("cbkid")
        .agg(
            pl.len().alias("n_profiles"),
            (pl.col("pert_type") == _TREATMENT_PERT_TYPE).any().alias("is_treated"),
            pl.col("pert_type")
            .is_in(_CONTROL_PERT_TYPES)
            .fill_null(False)
            .all()
            .alias("is_control"),
        )
        .with_columns(pl.col("cbkid").str.extract(_CBKID_STEM_PATTERN, 1).alias("cbkid_normalized"))
    )
    unclassifiable = sorted(
        counts.filter(~pl.col("is_treated") & ~pl.col("is_control"))["cbkid"].to_list(),
        key=str,
    )
    if unclassifiable:
        raise ValueError(
            f"These ids are neither compound nor control: {unclassifiable}. None has a "
            f"'{_TREATMENT_PERT_TYPE}' well, and each has a well whose 'pert_type' is null or "
            f"not one of {_CONTROL_PERT_TYPES}."
        )
    counts = counts.with_columns(
        pl.when(pl.col("is_treated"))
        .then(pl.lit("compound"))
        .otherwise(pl.lit("control"))
        .alias("kind")
    ).drop("is_treated", "is_control")

    annotations = _annotation_lookup(metadata)
    index = (
        counts
        if annotations is None
        else counts.join(annotations, on="cbkid_normalized", how="left")
    )

    if names is not None:
        index = index.join(build_name_lookup(names), on="cbkid", how="left")

    ordered = [column for column in _INDEX_COLUMNS if column in index.columns]
    return index.select(ordered).sort("cbkid")


def build_name_lookup(names: pl.DataFrame) -> pl.DataFrame:
    """Reduce the raw name lookup to one compound name per ``cbkid``.

    Rows whose ``pert_type`` names a condition rather than a compound are
    dropped first (see ``_CONDITION_PERT_TYPES``), then the remainder is reduced
    to one row per ``cbkid`` by the rule ``_annotation_lookup`` already applies
    to the CBCS metadata, so the result is deterministic whatever the input row
    order.

    Args:
        names: The loaded name lookup (see ``load_compound_names``).

    Returns:
        A ``cbkid`` -> ``pert_iname`` lookup with one row per id.
    """
    return (
        _drop_condition_rows(names)
        .select(["cbkid", COMPOUND_NAME_COLUMN])
        .sort(["cbkid", COMPOUND_NAME_COLUMN])
        .unique(subset="cbkid", keep="first")
    )


def compound_label(
    cbkid: str,
    *,
    name: str | None = None,
    kind: str | None = None,
    pert_iname: str | None = None,
) -> str:
    """Return one compound's display name.

    One rule, used wherever a compound is named to a reader: the on-page picker
    (FREYA-2583), each per-compound radar's title (FREYA-2636) and each PCA
    overlay's legend, so the control and the figure it swaps in cannot name the
    same compound differently. The name inside it is ``compound_name``'s, the
    same rule the compound table's Name uses.

    Args:
        cbkid: The compound id.
        name: The CBCS annotation's name, when the join found one.
        kind: ``"control"`` for an id whose wells are all control wells.
        pert_iname: The name lookup's name, used when the CBCS name is missing
            or blank (FREYA-3126).

    Returns:
        ``<cbkid> (control)`` for a control id; otherwise ``<name> (<cbkid>)``
        once annotated, ``<pert_iname> (<cbkid>)`` when only the lookup names
        it, and the bare id when neither does.
    """
    if kind == "control":
        return f"{cbkid} (control)"
    display_name = compound_name(name, pert_iname)
    return f"{display_name} ({cbkid})" if display_name else cbkid


def compound_name(name: str | None, pert_iname: str | None) -> str | None:
    """Return the name a compound is shown under, or ``None`` if it has none.

    The CBCS name wins; the name lookup's ``pert_iname`` stands in when the CBCS
    name is missing or blank (FREYA-3126). A whitespace-only value is no name.

    Args:
        name: The CBCS annotation's name.
        pert_iname: The name lookup's name.

    Returns:
        The first of the two that is neither missing nor blank, as given.
    """
    for candidate in (name, pert_iname):
        if candidate and str(candidate).strip():
            return candidate
    return None


def _drop_condition_rows(names: pl.DataFrame) -> pl.DataFrame:
    """Drop the lookup rows whose ``pert_iname`` names a condition, not a compound.

    Only the two condition types are dropped. The ``fill_null`` matters: an
    ``is_in`` against a null is null, and ``filter`` discards a null predicate,
    so without it a row with no ``pert_type`` would be dropped as well and
    counted as an excluded condition — losing a name and misreporting why.
    ``load_compound_names`` rejects such a row up front; this keeps the rule
    right for a caller that builds a lookup by hand.
    """
    is_condition = pl.col("pert_type").is_in(_CONDITION_PERT_TYPES).fill_null(False)
    return names.filter(~is_condition)


def _annotation_lookup(metadata: pl.DataFrame) -> pl.DataFrame | None:
    """Build a deduplicated ``cbkid_normalized`` -> annotation lookup.

    The metadata's own ``cbkid`` is dropped after deriving the stem so the join
    keeps the feature table's original ``cbkid`` as the compound identity. When
    several metadata rows share a stem the lexicographically smallest full row
    wins (the rows are sorted on every annotation field before deduplication),
    so the lookup is deterministic regardless of input row order.

    Args:
        metadata: The loaded compound metadata.

    Returns:
        A lookup keyed on ``cbkid_normalized``, or ``None`` if the metadata has
        no ``cbkid`` column to join on.
    """
    if "cbkid" not in metadata.columns:
        return None
    fields = [column for column in _METADATA_FIELDS if column in metadata.columns]
    return (
        metadata.select(fields)
        .with_columns(pl.col("cbkid").str.extract(_CBKID_STEM_PATTERN, 1).alias("cbkid_normalized"))
        .drop_nulls(subset="cbkid_normalized")
        .sort(fields)
        .unique(subset="cbkid_normalized", keep="first")
        .drop("cbkid")
    )


def reconciliation_report(index: pl.DataFrame) -> dict[str, Any]:
    """Summarise how feature cbkids reconciled against the CBCS metadata.

    Args:
        index: The compound index from ``build_compound_index``.

    Returns:
        A JSON-serialisable report: per-kind id counts, how many compounds were
        annotated (``n_recovered`` of them via stem normalisation), and the
        sorted list of compound cbkids left without metadata. The counts are also
        emitted to the structured log.
    """
    compounds = index.filter(pl.col("kind") == "compound")
    n_controls = index.filter(pl.col("kind") == "control").height

    if "name" in index.columns:
        annotated = compounds.filter(pl.col("name").is_not_null())
        unmatched_cbkids = sorted(compounds.filter(pl.col("name").is_null())["cbkid"].to_list())
        n_annotated = annotated.height
        n_recovered = annotated.filter(pl.col("cbkid") != pl.col("cbkid_normalized")).height
    else:
        unmatched_cbkids = sorted(compounds["cbkid"].to_list())
        n_annotated = 0
        n_recovered = 0

    report = {
        "n_compound_ids": compounds.height,
        "n_control_ids": n_controls,
        "n_annotated": n_annotated,
        "n_unannotated": len(unmatched_cbkids),
        "n_recovered": n_recovered,
        "unmatched_cbkids": unmatched_cbkids,
    }
    LOGGER.info(
        "drr.compounds.reconciliation",
        n_compound_ids=report["n_compound_ids"],
        n_control_ids=report["n_control_ids"],
        n_annotated=report["n_annotated"],
        n_unannotated=report["n_unannotated"],
        n_recovered=report["n_recovered"],
    )
    return report


def name_lookup_report(
    index: pl.DataFrame,
    names: pl.DataFrame | None = None,
    *,
    source_filename: str | None = None,
    source_hash: str | None = None,
) -> dict[str, Any]:
    """Summarise how the compound-name lookup joined the index (FREYA-2628).

    With no lookup supplied the block is still written, with a null ``source``
    and zero counts: that is what says no lookup ran, rather than that one ran
    and matched nothing.

    Args:
        index: The compound index from ``build_compound_index``.
        names: The raw name lookup, before condition rows are dropped.
        source_filename: Base name of the lookup file, for provenance.
        source_hash: SHA-256 hex digest of the lookup file.

    Returns:
        A JSON-serialisable report: provenance, how many ids the lookup holds,
        how many index rows it named and left unnamed, how many condition rows
        were excluded, and how many ids carried more than one name. A non-zero
        ``n_conflicting_ids`` means the upstream file has changed shape and
        wants looking at, not silent deduplication. The counts are also emitted
        to the structured log.
    """
    if names is None:
        report = {
            "source": None,
            "sha256": None,
            "n_lookup_ids": 0,
            "n_named": 0,
            "n_unnamed": 0,
            "n_condition_rows_excluded": 0,
            "n_conflicting_ids": 0,
        }
    else:
        named_rows = _drop_condition_rows(names)
        n_named = (
            index.filter(pl.col(COMPOUND_NAME_COLUMN).is_not_null()).height
            if COMPOUND_NAME_COLUMN in index.columns
            else 0
        )
        report = {
            "source": source_filename,
            "sha256": source_hash,
            "n_lookup_ids": named_rows["cbkid"].n_unique() if named_rows.height else 0,
            "n_named": n_named,
            "n_unnamed": index.height - n_named,
            "n_condition_rows_excluded": names.height - named_rows.height,
            "n_conflicting_ids": _conflicting_id_count(named_rows),
        }

    LOGGER.info("drr.compounds.name_lookup", **report)
    return report


def _conflicting_id_count(named_rows: pl.DataFrame) -> int:
    """Count ids carrying more than one distinct name once condition rows are gone."""
    if not named_rows.height:
        return 0
    return (
        named_rows.select(["cbkid", COMPOUND_NAME_COLUMN])
        .unique()
        .group_by("cbkid")
        .agg(pl.len().alias("n_names"))
        .filter(pl.col("n_names") > 1)
        .height
    )
