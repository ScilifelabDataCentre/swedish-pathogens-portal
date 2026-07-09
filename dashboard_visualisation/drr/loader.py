"""Load and split the DRR Cell Painting feature table and compound metadata."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import polars as pl
import polars.selectors as cs

# Non-feature metadata columns in the feature table, verified against the
# S-BIAD2580 Vero E6 export header. Every other numeric column is a feature.
METADATA_COLUMNS: list[str] = [
    "Metadata_Barcode",
    "Metadata_Well",
    "comp_conc",
    "pert_type",
    "batch_id",
    "cmpd_conc",
    "cbkid",
]

# Scan enough rows to infer column dtypes correctly for the full inputs
# (feature table ~8.3k rows, metadata files up to ~21k rows).
_SCHEMA_SCAN_ROWS = 100_000

# Missing values in the metadata TSV are encoded as the literal string "null".
_METADATA_NULL_VALUE = "null"


@dataclass(frozen=True)
class FeatureTable:
    """A loaded Cell Painting feature table split into metadata and features.

    Attributes:
        frame: The full table (metadata columns + numeric feature columns),
            with the upstream unnamed row-index column removed.
        metadata_columns: Names of the non-feature metadata columns present.
        feature_columns: Names of the numeric morphological feature columns.
    """

    frame: pl.DataFrame
    metadata_columns: list[str]
    feature_columns: list[str]

    def numeric_matrix(self) -> np.ndarray:
        """Return the feature columns as a float64 matrix (rows = profiles)."""
        return self.frame.select(self.feature_columns).to_numpy().astype(np.float64)


def load_feature_table(path: str | Path) -> FeatureTable:
    """Load the semicolon-delimited feature table and split its columns.

    The upstream export carries an unnamed leading integer index column, which
    is dropped. Metadata columns are matched against ``METADATA_COLUMNS``; all
    remaining numeric columns are treated as morphological features.

    Args:
        path: Path to the ``;``-delimited feature CSV.

    Returns:
        A ``FeatureTable`` with the cleaned frame and column split.

    Raises:
        ValueError: If the ``cbkid`` join key is missing from the table.
    """
    frame = pl.read_csv(path, separator=";", infer_schema_length=_SCHEMA_SCAN_ROWS)
    if frame.width and frame.columns[0] == "":
        frame = frame.drop(frame.columns[0])

    if "cbkid" not in frame.columns:
        raise ValueError("Feature table is missing the required 'cbkid' column.")

    metadata_columns = [column for column in METADATA_COLUMNS if column in frame.columns]
    numeric_columns = frame.select(cs.numeric()).columns
    feature_columns = [column for column in numeric_columns if column not in METADATA_COLUMNS]

    return FeatureTable(
        frame=frame,
        metadata_columns=metadata_columns,
        feature_columns=feature_columns,
    )


def load_metadata(path: str | Path) -> pl.DataFrame:
    """Load the tab-delimited CBCS compound metadata.

    Args:
        path: Path to the tab-delimited metadata TSV (BIA S-BIAD2580).

    Returns:
        The metadata as a DataFrame, with literal ``"null"`` tokens parsed as
        nulls.
    """
    return pl.read_csv(
        path,
        separator="\t",
        null_values=_METADATA_NULL_VALUE,
        infer_schema_length=_SCHEMA_SCAN_ROWS,
    )
