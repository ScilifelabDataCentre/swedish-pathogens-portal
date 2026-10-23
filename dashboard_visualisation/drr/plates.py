"""Per-screen plate basis for a DRR dataset: which plates a page publishes (FREYA-3008).

Not every plate a screen imaged was deposited upstream. On the A549-ACE2 validation
screen, four of the 22 plates — two analog plates and two DMSO control plates — were
never deposited and never will be, so no row measured on them can be linked to an
image. The decision is to publish only the deposited plates, and to apply that
everywhere: the downloads shrink with the figures and the counts. That makes it
unlike the channel exclusion and the clip, which only touch the figures.

The excluded plates are declared here per dataset slug, not passed at run time. The
basis is permanent for a screen imaged in 2023, and a run that forgot a flag would
silently republish every plate. An unregistered slug raises, exactly as the channel
map does, so a second screen must answer the question for itself; an empty tuple is
a valid answer and a visible one.

The deposit's own image metadata is then read as a check: every published row
should resolve to one deposited image on (plate, well), and the count that does not
is recorded rather than assumed to be zero.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import polars as pl

from .loader import FeatureTable

# One entry per screen, keyed by dataset slug: the plate stems whose rows are not
# published. A slug that is not here stops a precompute run.
EXCLUDED_PLATES: dict[str, tuple[str, ...]] = {
    "sars-cov2-a549-ace2-validation": ("P103572", "P103573", "P103587", "P103588"),
}

# The columns read from the deposit's image-metadata TSV: the archive path, the
# plate barcode it was imaged under, and the well.
PLATE_METADATA_COLUMNS: list[str] = ["Files", "barcode", "well_id"]

# The feature table's plate and well columns.
_PLATE_COLUMN = "Metadata_Barcode"
_WELL_COLUMN = "Metadata_Well"


def excluded_plates(dataset_slug: str) -> tuple[str, ...]:
    """Return the plate stems one dataset leaves out.

    Args:
        dataset_slug: The dataset slug, matching both the page slug and
            ``DrrDatasetData.dataset_slug``.

    Returns:
        The excluded plate stems, possibly empty.

    Raises:
        ValueError: If no basis is registered for the slug. Defaulting to "every
            plate" is exactly the failure this registry exists to prevent.
    """
    try:
        return EXCLUDED_PLATES[dataset_slug]
    except KeyError as error:
        raise ValueError(
            f"No plate basis is registered for dataset slug '{dataset_slug}'. Declare which "
            "plates this screen leaves out in EXCLUDED_PLATES — an empty tuple if none — "
            f"rather than publishing every plate by default. Registered: {sorted(EXCLUDED_PLATES)}."
        ) from error


def _plate_stem(column: str) -> pl.Expr:
    """Return the plate stem of a barcode column: everything before the first ``_``.

    The deposit names a plate ``P103554_SSS-val_A549-ACE2_2023-11-24_21.09.22``, while
    the feature table carries the bare ``P103554``; the stem is what both share.
    """
    return pl.col(column).cast(pl.String).str.split("_").list.first()


def exclude_plates(table: FeatureTable, stems: tuple[str, ...]) -> tuple[FeatureTable, int]:
    """Drop every row measured on an excluded plate.

    Args:
        table: The loaded feature table.
        stems: The plate stems to leave out.

    Returns:
        The table without those rows, with its column split unchanged, and the
        number of rows removed.
    """
    kept = table.frame.filter(~_plate_stem(_PLATE_COLUMN).is_in(list(stems)))
    return dataclasses.replace(table, frame=kept), table.frame.height - kept.height


def load_plate_metadata(path: str | Path) -> pl.DataFrame:
    """Load the deposit's image metadata as unique (plate stem, well) keys.

    Args:
        path: Path to the tab-delimited image-metadata TSV for this screen.

    Returns:
        One row per deposited (plate stem, well), with its archive path.

    Raises:
        ValueError: If a required column is missing.
    """
    header = pl.read_csv(path, separator="\t", n_rows=0).columns
    missing = [column for column in PLATE_METADATA_COLUMNS if column not in header]
    if missing:
        raise ValueError(
            f"Plate metadata is missing the required column(s) {missing}. Found: {header[:8]}."
        )
    metadata = pl.read_csv(
        path,
        separator="\t",
        columns=PLATE_METADATA_COLUMNS,
        schema_overrides=dict.fromkeys(PLATE_METADATA_COLUMNS, pl.String),
    )
    return metadata.select(
        _plate_stem("barcode").alias("plate_stem"),
        pl.col("well_id"),
        pl.col("Files").alias("archive_path"),
    ).unique(subset=["plate_stem", "well_id"], keep="first", maintain_order=True)


def unresolved_rows(table: FeatureTable, plate_metadata: pl.DataFrame) -> int:
    """Count the rows that resolve to no deposited image on (plate stem, well).

    On a correct basis this is zero; any other value means the run was given the
    wrong inputs or the wrong plate basis.

    Args:
        table: The feature table as published, after the exclusion.
        plate_metadata: The deposit's keys, from ``load_plate_metadata``.

    Returns:
        The number of unresolved rows.
    """
    keys = table.frame.select(
        _plate_stem(_PLATE_COLUMN).alias("plate_stem"),
        pl.col(_WELL_COLUMN).cast(pl.String).alias("well_id"),
    )
    return keys.join(
        plate_metadata.select("plate_stem", "well_id"),
        on=["plate_stem", "well_id"],
        how="anti",
    ).height


def plate_basis_report(
    *,
    stems: tuple[str, ...],
    n_rows_excluded: int,
    n_unresolved_rows: int,
    source_filename: str,
) -> dict[str, Any]:
    """Describe the plate basis a run used, for ``summary.json``.

    The excluded stems are counted, not named: no row measured on them is
    published, and the stems themselves stay out of every artefact too
    (FREYA-3008 criterion 4). The run's own console report names them.

    Args:
        stems: The plate stems the run left out.
        n_rows_excluded: How many rows that removed.
        n_unresolved_rows: How many published rows resolve to no deposited image.
        source_filename: Base name of the image-metadata file, for provenance.

    Returns:
        A JSON-serialisable dict.
    """
    return {
        "n_plates_excluded": len(stems),
        "n_rows_excluded": n_rows_excluded,
        "n_unresolved_rows": n_unresolved_rows,
        "plate_metadata": source_filename,
    }
