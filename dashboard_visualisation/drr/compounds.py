"""Build the CBCS compound index by joining feature cbkids to metadata.

The feature table and the CBCS metadata TSV do not key ``cbkid`` identically:
the feature table encodes salt/form variants with a trailing letter suffix
(e.g. ``CBK008271G``) while the metadata keys on the bare stem (``CBK008271``).
The join therefore happens on a normalised stem so a variant inherits its base
compound's annotation, while the original ``cbkid`` is kept as the compound
identity (profile counts and per-``cbkid`` downloads are unchanged). Non-CBCS
tokens (control placeholders like ``[stau]`` or foreign ids like ``DO8167002``)
have no stem, never join, and are classified as controls (FREYA-2557).
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

# Compound index column order (annotation columns appended when available).
_INDEX_COLUMNS = [
    "cbkid",
    "cbkid_normalized",
    "kind",
    "n_profiles",
    "name",
    "broad_moa",
    "broad_target",
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


def build_compound_index(table: FeatureTable, metadata: pl.DataFrame) -> pl.DataFrame:
    """Build a per-compound index for the dataset.

    Groups the feature table by its original ``cbkid`` (the compound identity),
    derives a normalised stem, classifies each id as ``compound`` or ``control``,
    and left-joins the CBCS ``name`` / ``broad_moa`` / ``broad_target``
    annotations on the stem so salt/form variants inherit their base compound's
    annotation.

    Args:
        table: The loaded feature table.
        metadata: The loaded compound metadata (see ``load_metadata``).

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

    ordered = [column for column in _INDEX_COLUMNS if column in index.columns]
    return index.select(ordered).sort("cbkid")


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
