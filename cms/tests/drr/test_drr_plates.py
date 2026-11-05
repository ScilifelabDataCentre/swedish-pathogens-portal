"""Tests for the DRR per-screen plate basis (FREYA-3008)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import polars as pl
from django.test import SimpleTestCase

from dashboard_visualisation.drr.loader import FeatureTable
from dashboard_visualisation.drr.plates import (
    EXCLUDED_PLATES,
    exclude_plates,
    excluded_plates,
    load_plate_metadata,
    unresolved_rows,
)

SLUG = "sars-cov2-a549-ace2-validation"

# The four A549-ACE2 validation plates that were imaged but never deposited.
NEVER_DEPOSITED = ("P103572", "P103573", "P103587", "P103588")


def _table(barcodes: list[str], wells: list[str] | None = None) -> FeatureTable:
    """Build a minimal feature table with one row per barcode."""
    frame = pl.DataFrame(
        {
            "Metadata_Barcode": barcodes,
            "Metadata_Well": wells or [f"A{index:02d}" for index in range(1, len(barcodes) + 1)],
            "cbkid": [f"CBK{index}" for index in range(len(barcodes))],
            "AreaShape_Area_nuclei": [float(index) for index in range(len(barcodes))],
        }
    )
    return FeatureTable(
        frame=frame,
        metadata_columns=["Metadata_Barcode", "Metadata_Well", "cbkid"],
        feature_columns=["AreaShape_Area_nuclei"],
    )


class ExcludedPlatesTests(SimpleTestCase):
    """The registry answers per screen, and refuses a screen it does not know."""

    def test_the_validation_screen_leaves_out_its_four_never_deposited_plates(self) -> None:
        """The registered basis is exactly the four stems, in a stable order."""
        self.assertEqual(excluded_plates(SLUG), NEVER_DEPOSITED)

    def test_an_unregistered_slug_raises(self) -> None:
        """No default: a new screen must declare its own basis, even an empty one."""
        with self.assertRaisesMessage(ValueError, "no-such-screen"):
            excluded_plates("no-such-screen")

    def test_every_registered_basis_is_a_tuple_of_bare_stems(self) -> None:
        """A stem with a suffix would never match the feature table's bare barcodes."""
        for slug, stems in EXCLUDED_PLATES.items():
            self.assertIsInstance(stems, tuple, slug)
            for stem in stems:
                self.assertNotIn("_", stem, slug)


class ExcludePlatesTests(SimpleTestCase):
    """The filter drops exactly the excluded stems and nothing else."""

    def test_drops_exactly_the_four_stems(self) -> None:
        """Rows on the excluded plates go; rows on every other plate stay, in order."""
        kept_barcodes = ["P103554", "P103571", "P103574", "P1035720"]
        table = _table(["P103554", *NEVER_DEPOSITED, "P103571", "P103574", "P1035720"])

        filtered, n_removed = exclude_plates(table, NEVER_DEPOSITED)

        self.assertEqual(n_removed, 4)
        self.assertEqual(filtered.frame["Metadata_Barcode"].to_list(), kept_barcodes)
        self.assertEqual(filtered.feature_columns, table.feature_columns)
        self.assertEqual(filtered.metadata_columns, table.metadata_columns)

    def test_matches_on_the_stem_of_a_suffixed_barcode(self) -> None:
        """A barcode carrying the deposit's experiment suffix still resolves to its plate."""
        table = _table(["P103572_SSS-val_A549-ACE2_2023-10-24_05.33.40", "P103554"])

        filtered, n_removed = exclude_plates(table, NEVER_DEPOSITED)

        self.assertEqual(n_removed, 1)
        self.assertEqual(filtered.frame["Metadata_Barcode"].to_list(), ["P103554"])

    def test_an_empty_basis_keeps_every_row(self) -> None:
        """An empty tuple is a valid answer: publish every plate."""
        table = _table(list(NEVER_DEPOSITED))

        filtered, n_removed = exclude_plates(table, ())

        self.assertEqual(n_removed, 0)
        self.assertTrue(filtered.frame.equals(table.frame))


class UnresolvedRowsTests(SimpleTestCase):
    """The guard counts rows the deposit cannot name, on (plate stem, well)."""

    def setUp(self) -> None:
        """Write a two-plate image-metadata file with suffixed barcodes."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "plates.tsv"
        self.path.write_text(
            "Files\tbarcode\twell_id\tname\n"
            "a.zip\tP1_SSS-val_2023-11-24\tA01\tx\n"
            "a.zip\tP1_SSS-val_2023-11-24\tA02\tnull\n"
            "b.zip\tP2_SSS-val_2023-11-25\tB01\tx\n",
            encoding="utf-8",
        )

    def test_loads_unique_stem_and_well_keys(self) -> None:
        """Barcodes are reduced to their stems, and each key carries its archive."""
        metadata = load_plate_metadata(self.path)

        self.assertEqual(metadata.columns, ["plate_stem", "well_id", "archive_path"])
        self.assertEqual(
            metadata.rows(),
            [("P1", "A01", "a.zip"), ("P1", "A02", "a.zip"), ("P2", "B01", "b.zip")],
        )

    def test_counts_zero_when_every_row_has_an_image(self) -> None:
        """Every (plate, well) present in the deposit resolves."""
        table = _table(["P1", "P1", "P2"], ["A01", "A02", "B01"])

        self.assertEqual(unresolved_rows(table, load_plate_metadata(self.path)), 0)

    def test_counts_a_row_on_the_wrong_well_or_an_undeposited_plate(self) -> None:
        """A known plate on an unknown well and an unknown plate both count."""
        table = _table(["P1", "P1", "P3"], ["A01", "B09", "A01"])

        self.assertEqual(unresolved_rows(table, load_plate_metadata(self.path)), 2)

    def test_a_missing_column_raises(self) -> None:
        """A file without well ids cannot answer the question, so it is refused."""
        self.path.write_text("Files\tbarcode\na.zip\tP1\n", encoding="utf-8")

        with self.assertRaisesMessage(ValueError, "well_id"):
            load_plate_metadata(self.path)
