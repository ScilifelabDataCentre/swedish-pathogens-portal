"""Build the CBCS compound index by joining feature cbkids to metadata.

The feature table and the CBCS metadata TSV do not key ``cbkid`` identically:
the feature table encodes salt/form variants with a trailing letter suffix
(e.g. ``CBK008271G``) while the metadata keys on the bare stem (``CBK008271``).
The join therefore happens on a normalised stem so a variant inherits its base
compound's annotation, while the original ``cbkid`` is kept as the compound
identity (profile counts and per-``cbkid`` downloads are unchanged). Non-CBCS
tokens (control placeholders like ``[stau]`` or foreign ids like ``DO8167002``)
have no stem, never join, and are classified as controls (FREYA-2557).

The index can carry a second, independent naming system: ``pert_iname``, the
authors' own compound name, read from the companion repository's Arrow file as a
lookup over its hit set (FREYA-2628). It is never merged into ``name`` — that is
the CBCS annotation dictionary's name, and only ``pert_iname`` is expected to
join the paper's Table S8. Because the lookup keys on the same ids the feature
table uses, it joins on the raw ``cbkid`` rather than on the stem.
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
    values return ``None`` so they never join and are treated as controls.

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
    derives a normalised stem, classifies each id as ``compound`` or ``control``,
    and left-joins the CBCS ``name`` / ``broad_moa`` / ``broad_target``
    annotations on the stem so salt/form variants inherit their base compound's
    annotation. When a name lookup is supplied its ``pert_iname`` is joined on
    the raw ``cbkid`` and appended last; ids outside the lookup keep an explicit
    null rather than being dropped.

    Args:
        table: The loaded feature table.
        metadata: The loaded compound metadata (see ``load_metadata``).
        names: Optional name lookup (see ``load_compound_names``); omitted, the
            index carries no ``pert_iname`` column at all.

    Returns:
        A DataFrame with one row per original ``cbkid`` (``cbkid``,
        ``cbkid_normalized``, ``kind``, ``n_profiles``, and the available
        annotation columns), sorted by ``cbkid``.
    """
    counts = (
        table.frame.group_by("cbkid")
        .agg(pl.len().alias("n_profiles"))
        .with_columns(pl.col("cbkid").str.extract(_CBKID_STEM_PATTERN, 1).alias("cbkid_normalized"))
        .with_columns(
            pl.when(pl.col("cbkid_normalized").is_null())
            .then(pl.lit("control"))
            .otherwise(pl.lit("compound"))
            .alias("kind")
        )
    )

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


def _drop_condition_rows(names: pl.DataFrame) -> pl.DataFrame:
    """Drop the lookup rows whose ``pert_iname`` names a condition, not a compound."""
    return names.filter(~pl.col("pert_type").is_in(_CONDITION_PERT_TYPES))


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
