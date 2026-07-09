"""Build the CBCS compound index by joining feature cbkids to metadata."""

from __future__ import annotations

import polars as pl
import structlog

from .loader import FeatureTable

LOGGER = structlog.get_logger(__name__)

# Compound-level annotation columns pulled from the BIA metadata TSV.
_METADATA_FIELDS = ["cbkid", "name", "broad_moa", "broad_target"]


def build_compound_index(table: FeatureTable, metadata: pl.DataFrame) -> pl.DataFrame:
    """Build a per-compound index for the dataset.

    Joins each unique ``cbkid`` in the feature table (with its profile count) to
    the CBCS ``name`` / ``broad_moa`` / ``broad_target`` annotations. The join is
    an exact ``cbkid`` match; format reconciliation (zero-padding, prefixes) is
    deferred to FREYA-2557.

    Args:
        table: The loaded feature table.
        metadata: The loaded compound metadata (see ``load_metadata``).

    Returns:
        A DataFrame with one row per ``cbkid`` (``cbkid``, ``n_profiles``, and
        the available annotation columns), sorted by ``cbkid``.
    """
    counts = table.frame.group_by("cbkid").agg(pl.len().alias("n_profiles"))

    available = [column for column in _METADATA_FIELDS if column in metadata.columns]
    if "cbkid" in available:
        annotations = metadata.select(available).unique(subset=["cbkid"], keep="first")
        index = counts.join(annotations, on="cbkid", how="left")
    else:
        index = counts

    _log_unmatched(index)
    return index.sort("cbkid")


def _log_unmatched(index: pl.DataFrame) -> None:
    """Log how many compounds had no metadata annotation (informs FREYA-2557)."""
    total = index.height
    unmatched = index.filter(pl.col("name").is_null()).height if "name" in index.columns else total
    if unmatched:
        LOGGER.warning("drr.compounds.unmatched_cbkids", unmatched=unmatched, total=total)
