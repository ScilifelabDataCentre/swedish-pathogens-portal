"""Build the DRR summary-statistics payload (spec section 7)."""

from __future__ import annotations

from typing import Any

from .channels import Channel, present_channels
from .figures import FEATURE_BASIS_FIGURE_IDS
from .loader import FeatureTable

# Canonical display order for CellProfiler segmentation compartments.
COMPARTMENTS: list[str] = ["nuclei", "cells", "cytoplasm"]


def _present_compartments(feature_columns: list[str]) -> list[str]:
    """Return the compartments that appear as ``_<compartment>`` suffixes."""
    return [
        compartment
        for compartment in COMPARTMENTS
        if any(column.endswith(f"_{compartment}") for column in feature_columns)
    ]


def _pert_type_counts(table: FeatureTable) -> dict[str, int]:
    """Return per-``pert_type`` profile counts, key-sorted for determinism."""
    if "pert_type" not in table.frame.columns:
        return {}
    counts = {
        str(value): int(count)
        for value, count in table.frame["pert_type"].value_counts().iter_rows()
    }
    return dict(sorted(counts.items()))


def _feature_sets(
    table: FeatureTable,
    figure_feature_columns: list[str],
    channels: tuple[Channel, ...],
) -> dict[str, Any]:
    """Report both feature sets, so a reader cannot confuse one for the other.

    The download set is every numeric feature column; the figure set excludes the
    infection-readout channel. Recording both counts, and which figures used the
    figure set, is what keeps a later session from re-deriving the wrong basis
    (spec section 5, FREYA-2923 criterion 5).
    """
    excluded = [channel.column_tag for channel in channels if not channel.in_figures]
    return {
        "download": {
            "n_features": len(table.feature_columns),
            "used_by": ["features.csv", "features.parquet"],
        },
        "figures": {
            "n_features": len(figure_feature_columns),
            "excluded_channels": excluded,
            "used_by": list(FEATURE_BASIS_FIGURE_IDS),
        },
    }


def build_summary(
    table: FeatureTable,
    *,
    channels: tuple[Channel, ...],
    figure_feature_columns: list[str],
    source_filename: str,
    source_hash: str,
    generated_at: str,
) -> dict[str, Any]:
    """Build the summary-statistics panel payload for a DRR dataset.

    Args:
        table: The loaded feature table.
        channels: This screen's channel map, which decides both the stain names
            the page publishes and which channel the figures exclude.
        figure_feature_columns: The feature columns the figures computed on.
        source_filename: Base name of the source feature file, for provenance.
        source_hash: SHA-256 hex digest of the source feature file.
        generated_at: ISO-8601 timestamp of the precompute run.

    Returns:
        A JSON-serialisable dict matching the spec section 7 shape.
    """
    frame = table.frame
    n_wells = 0
    if {"Metadata_Barcode", "Metadata_Well"}.issubset(frame.columns):
        n_wells = frame.select(["Metadata_Barcode", "Metadata_Well"]).unique().height

    return {
        "n_compounds": frame["cbkid"].n_unique() if "cbkid" in frame.columns else 0,
        "n_plates": frame["Metadata_Barcode"].n_unique()
        if "Metadata_Barcode" in frame.columns
        else 0,
        "n_wells": n_wells,
        "n_profiles": frame.height,
        "n_features": len(table.feature_columns),
        "pert_type_counts": _pert_type_counts(table),
        "compartments": _present_compartments(table.feature_columns),
        "channels": present_channels(table.feature_columns, channels),
        "feature_sets": _feature_sets(table, figure_feature_columns, channels),
        "source": {
            "filename": source_filename,
            "sha256": source_hash,
            "generated_at": generated_at,
        },
    }
