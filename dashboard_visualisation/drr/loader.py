"""Load the DRR Cell Painting feature table, compound metadata and name lookup."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import polars as pl
import polars.selectors as cs

# Non-feature metadata columns in the feature table, verified against the
# S-BIAD2580 A549-ACE2 validation-screen export header. Every other numeric
# column is a feature. ``Count_nuclei`` is numeric but a QC column, not a
# morphological feature: the authors' own notebook skips it before building
# their feature matrix (spec section 5). It stays in the frame, so downloads
# still carry it.
METADATA_COLUMNS: list[str] = [
    "Metadata_Barcode",
    "Metadata_Well",
    "comp_conc",
    "pert_type",
    "batch_id",
    "cmpd_conc",
    "cbkid",
    "Count_nuclei",
]

# Scan enough rows to infer column dtypes correctly for the full inputs
# (feature table ~8.3k rows, metadata files up to ~21k rows).
_SCHEMA_SCAN_ROWS = 100_000

# The only columns read from the companion repository's Arrow file, out of its
# 1,153: the compound id, the authors' own compound name, and the perturbation
# type that says which rows name a compound at all (FREYA-2628). None of its
# feature values is ever read — that file is a row and column subset of our
# input, so it is a name lookup and not a feature source (spec section 5).
NAME_LOOKUP_COLUMNS: list[str] = ["cbkid", "pert_iname", "pert_type"]

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
        """Return the feature columns as a float64 matrix (rows = profiles).

        Returns:
            The feature values exactly as delivered; nothing is imputed or
            rescaled (spec section 5).

        Raises:
            ValueError: If any feature column carries a missing or non-finite
                value. The screen's export arrives complete, so a gap means the
                input is wrong rather than that a value needs inventing.
        """
        matrix = self.frame.select(self.feature_columns).to_numpy().astype(np.float64)
        if not np.isfinite(matrix).all():
            incomplete = [
                column
                for index, column in enumerate(self.feature_columns)
                if not np.isfinite(matrix[:, index]).all()
            ]
            raise ValueError(
                f"Feature matrix has missing or non-finite values in {len(incomplete)} column(s), "
                f"e.g. {incomplete[:3]}. The input is expected to arrive complete "
                "(spec section 5) and no value is imputed."
            )
        return matrix


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
        ValueError: If the ``cbkid`` join key is missing from the table, or if
            the feature matrix carries missing or non-finite values.
    """
    frame = pl.read_csv(path, separator=";", infer_schema_length=_SCHEMA_SCAN_ROWS)
    if frame.width and frame.columns[0] == "":
        frame = frame.drop(frame.columns[0])

    if "cbkid" not in frame.columns:
        raise ValueError("Feature table is missing the required 'cbkid' column.")

    metadata_columns = [column for column in METADATA_COLUMNS if column in frame.columns]
    numeric_columns = frame.select(cs.numeric()).columns
    feature_columns = [column for column in numeric_columns if column not in METADATA_COLUMNS]

    table = FeatureTable(
        frame=frame,
        metadata_columns=metadata_columns,
        feature_columns=feature_columns,
    )
    # Reject an incomplete matrix here, at load, so a run that cannot produce
    # figures also never overwrites the artefacts a page already serves.
    table.numeric_matrix()
    return table


def load_compound_names(path: str | Path) -> pl.DataFrame:
    """Load the compound-name lookup from the companion repository's Arrow file.

    Only ``NAME_LOOKUP_COLUMNS`` are read. The file is compressed IPC, so polars
    declines to memory-map it and falls back to a normal read, which warns on
    stderr; the read needs no pyarrow.

    Args:
        path: Path to the Arrow/IPC file carrying ``pert_iname``.

    Returns:
        The three lookup columns, one row per source row (unreduced).

    Raises:
        ValueError: If any lookup column is missing from the file.
    """
    available = pl.read_ipc_schema(path)
    missing = [column for column in NAME_LOOKUP_COLUMNS if column not in available]
    if missing:
        raise ValueError(
            f"Compound-name lookup is missing the required column(s) {missing}. "
            f"Found: {sorted(available)[:8]}."
        )
    return pl.read_ipc(path, columns=NAME_LOOKUP_COLUMNS)


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
