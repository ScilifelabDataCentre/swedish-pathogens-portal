"""Unit tests for the DRR cbkid reconciliation + compound index (FREYA-2557)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import polars as pl
from django.test import SimpleTestCase

from dashboard_visualisation.drr import (
    build_compound_index,
    build_name_lookup,
    load_compound_names,
    name_lookup_report,
    normalize_cbkid,
    reconciliation_report,
)
from dashboard_visualisation.drr.loader import NAME_LOOKUP_COLUMNS, FeatureTable

# One metadata row per bare stem; a duplicate stem with a different name is
# included to exercise deterministic deduplication.
METADATA = pl.DataFrame(
    {
        "cbkid": ["CBK008271", "CBK000155", "CBK000155", "CBK011567"],
        "name": ["alpha", "beta", "beta-alt", "gamma"],
        "broad_moa": ["moaA", "moaB", "moaB", "moaC"],
        "broad_target": ["tgtA", "tgtB", "tgtB", "tgtC"],
    }
)

# The name lookup's measured shape in miniature (FREYA-2628): treated compounds,
# the negative-control id carrying its condition as a "name" under both control
# perturbation types, and a bracketed positive control that does carry a real
# compound name.
NAME_LOOKUP = pl.DataFrame(
    {
        "cbkid": ["CBK008271", "CBK000155", "CBK281357", "CBK281357", "[flup]"],
        "pert_iname": ["alpha-iname", "beta-iname", "DMSO", "non-inf", "Fluphenazine"],
        "pert_type": ["trt", "trt", "negcon", "non-inf", "poscon"],
    }
)

# One treated id carrying two names — the shape change the conflict count exists
# to surface, rather than deduplicate away silently.
CONFLICTING_LOOKUP = pl.DataFrame(
    {
        "cbkid": ["CBK000155", "CBK000155"],
        "pert_iname": ["beta-iname", "beta-iname-alt"],
        "pert_type": ["trt", "trt"],
    }
)

EXPECTED_INDEX_COLUMNS = [
    "cbkid",
    "cbkid_normalized",
    "kind",
    "n_profiles",
    "name",
    "broad_moa",
    "broad_target",
]


def _feature_table(cbkids: list[str]) -> FeatureTable:
    """Build a minimal FeatureTable whose only relevant column is ``cbkid``."""
    return FeatureTable(
        frame=pl.DataFrame({"cbkid": cbkids}),
        metadata_columns=["cbkid"],
        feature_columns=[],
    )


def _row(index: pl.DataFrame, cbkid: str) -> dict:
    """Return the index row for a cbkid as a plain dict."""
    return index.filter(pl.col("cbkid") == cbkid).to_dicts()[0]


class NormalizeCbkidTests(SimpleTestCase):
    """The cbkid stem extraction underpinning the reconciliation join."""

    def test_bare_stem_is_unchanged(self) -> None:
        """A bare CBCS id is its own stem."""
        self.assertEqual(normalize_cbkid("CBK008271"), "CBK008271")

    def test_salt_form_suffix_is_stripped(self) -> None:
        """A trailing salt/form letter suffix is stripped to the base stem."""
        self.assertEqual(normalize_cbkid("CBK008271G"), "CBK008271")
        self.assertEqual(normalize_cbkid("CBK011567C"), "CBK011567")

    def test_non_cbcs_tokens_have_no_stem(self) -> None:
        """Control placeholders, foreign ids, and empties have no stem."""
        self.assertIsNone(normalize_cbkid("[stau]"))
        self.assertIsNone(normalize_cbkid("DO8167002"))
        self.assertIsNone(normalize_cbkid(""))
        self.assertIsNone(normalize_cbkid(None))


class BuildCompoundIndexTests(SimpleTestCase):
    """The compound index join, identity, and control classification."""

    def test_column_shape_and_order(self) -> None:
        """The index exposes identity, normalized key, kind, counts, annotations."""
        index = build_compound_index(_feature_table(["CBK008271"]), METADATA)
        self.assertEqual(index.columns, EXPECTED_INDEX_COLUMNS)

    def test_salt_variant_inherits_base_annotation(self) -> None:
        """A salt variant keeps its identity but inherits the base annotation."""
        index = build_compound_index(_feature_table(["CBK008271G"]), METADATA)
        row = _row(index, "CBK008271G")
        self.assertEqual(row["cbkid"], "CBK008271G")
        self.assertEqual(row["cbkid_normalized"], "CBK008271")
        self.assertEqual(row["kind"], "compound")
        self.assertEqual(row["name"], "alpha")

    def test_direct_match_annotated(self) -> None:
        """A bare cbkid matches its metadata row directly."""
        index = build_compound_index(_feature_table(["CBK000155"]), METADATA)
        self.assertEqual(_row(index, "CBK000155")["name"], "beta")

    def test_control_tokens_classified(self) -> None:
        """Non-CBCS tokens are controls with a null stem and no annotation."""
        index = build_compound_index(_feature_table(["[stau]", "DO8167002"]), METADATA)
        for token in ("[stau]", "DO8167002"):
            row = _row(index, token)
            self.assertEqual(row["kind"], "control")
            self.assertIsNone(row["cbkid_normalized"])
            self.assertIsNone(row["name"])

    def test_unannotated_compound_kept_with_null_metadata(self) -> None:
        """A CBCS compound absent from metadata stays a compound with null name."""
        index = build_compound_index(_feature_table(["CBK999999"]), METADATA)
        row = _row(index, "CBK999999")
        self.assertEqual(row["kind"], "compound")
        self.assertEqual(row["cbkid_normalized"], "CBK999999")
        self.assertIsNone(row["name"])

    def test_profile_counts_are_per_original_cbkid(self) -> None:
        """Profiles are counted per original cbkid, not merged across variants."""
        index = build_compound_index(
            _feature_table(["CBK008271", "CBK008271", "CBK008271G"]), METADATA
        )
        self.assertEqual(_row(index, "CBK008271")["n_profiles"], 2)
        self.assertEqual(_row(index, "CBK008271G")["n_profiles"], 1)

    def test_deterministic_dedup_on_conflicting_metadata(self) -> None:
        """A shared stem resolves to the lexicographically smallest row, stably."""
        first = build_compound_index(_feature_table(["CBK000155"]), METADATA)
        second = build_compound_index(_feature_table(["CBK000155"]), METADATA)
        self.assertEqual(_row(first, "CBK000155")["name"], "beta")
        self.assertEqual(_row(second, "CBK000155")["name"], "beta")

    def test_without_metadata_cbkid_column(self) -> None:
        """With no metadata cbkid column the index still classifies ids."""
        index = build_compound_index(_feature_table(["CBK000155", "[stau]"]), pl.DataFrame())
        self.assertEqual(index.columns, ["cbkid", "cbkid_normalized", "kind", "n_profiles"])
        self.assertEqual(_row(index, "CBK000155")["kind"], "compound")
        self.assertEqual(_row(index, "[stau]")["kind"], "control")


class ReconciliationReportTests(SimpleTestCase):
    """The reconciliation summary emitted into summary.json and the log."""

    def test_report_counts(self) -> None:
        """Counts split annotated/recovered/unannotated compounds from controls."""
        table = _feature_table(["CBK000155", "CBK008271G", "CBK999999", "[stau]", "DO8167002"])
        report = reconciliation_report(build_compound_index(table, METADATA))
        self.assertEqual(report["n_compound_ids"], 3)
        self.assertEqual(report["n_control_ids"], 2)
        self.assertEqual(report["n_annotated"], 2)
        self.assertEqual(report["n_recovered"], 1)
        self.assertEqual(report["n_unannotated"], 1)
        self.assertEqual(report["unmatched_cbkids"], ["CBK999999"])

    def test_unmatched_cbkids_sorted_and_excludes_controls(self) -> None:
        """Unmatched list is sorted and never includes control tokens."""
        table = _feature_table(["CBK999999", "CBK000900", "[stau]"])
        report = reconciliation_report(build_compound_index(table, METADATA))
        self.assertEqual(report["unmatched_cbkids"], ["CBK000900", "CBK999999"])

    def test_report_without_metadata(self) -> None:
        """With no annotations every compound is reported unannotated."""
        table = _feature_table(["CBK000155", "[stau]"])
        report = reconciliation_report(build_compound_index(table, pl.DataFrame()))
        self.assertEqual(report["n_annotated"], 0)
        self.assertEqual(report["n_recovered"], 0)
        self.assertEqual(report["unmatched_cbkids"], ["CBK000155"])
        self.assertEqual(report["n_control_ids"], 1)


class LoadCompoundNamesTests(SimpleTestCase):
    """Reading the companion Arrow file as a three-column lookup (FREYA-2628)."""

    def setUp(self) -> None:
        """Provide a temporary directory for Arrow fixtures."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)

    def _write_ipc(self, frame: pl.DataFrame) -> Path:
        """Write a frame as a compressed Arrow file, as the upstream file is."""
        path = self.base / "lookup.feather"
        frame.write_ipc(path, compression="zstd")
        return path

    def test_only_the_lookup_columns_are_read(self) -> None:
        """Feature values are never read: three columns come back, whatever the file holds."""
        path = self._write_ipc(
            NAME_LOOKUP.with_columns(
                pl.lit(1.0).alias("AreaShape_Area_nuclei"),
                pl.lit(2.0).alias("Intensity_MeanIntensity_illumSYTO_cells"),
            )
        )

        names = load_compound_names(path)

        self.assertEqual(names.columns, NAME_LOOKUP_COLUMNS)
        self.assertEqual(names.height, NAME_LOOKUP.height)

    def test_missing_column_raises(self) -> None:
        """A file without a lookup column fails loudly, naming what is missing."""
        path = self._write_ipc(NAME_LOOKUP.drop("pert_type"))

        with self.assertRaisesMessage(ValueError, "pert_type"):
            load_compound_names(path)


class BuildNameLookupTests(SimpleTestCase):
    """Reducing the raw lookup to one compound name per cbkid (FREYA-2628)."""

    def test_condition_rows_are_dropped_and_ids_are_unique(self) -> None:
        """The negcon/non-inf rows go, leaving one row per remaining id."""
        lookup = build_name_lookup(NAME_LOOKUP)

        self.assertEqual(lookup.columns, ["cbkid", "pert_iname"])
        self.assertEqual(lookup.height, lookup["cbkid"].n_unique())
        self.assertNotIn("CBK281357", lookup["cbkid"].to_list())

    def test_dedup_is_order_independent(self) -> None:
        """A conflicting id resolves the same way whatever the input row order."""
        forward = build_name_lookup(CONFLICTING_LOOKUP)
        reversed_rows = build_name_lookup(CONFLICTING_LOOKUP.reverse())

        self.assertEqual(forward.to_dicts(), reversed_rows.to_dicts())


class CompoundIndexNameLookupTests(SimpleTestCase):
    """The pert_iname join into the compound index (FREYA-2628)."""

    def test_name_column_is_appended_last(self) -> None:
        """The lookup adds one column, at the end of the documented order."""
        index = build_compound_index(_feature_table(["CBK008271"]), METADATA, NAME_LOOKUP)
        self.assertEqual(index.columns, [*EXPECTED_INDEX_COLUMNS, "pert_iname"])

    def test_column_absent_without_a_lookup(self) -> None:
        """Omitting the lookup leaves the index exactly as it was."""
        index = build_compound_index(_feature_table(["CBK008271"]), METADATA)
        self.assertEqual(index.columns, EXPECTED_INDEX_COLUMNS)

    def test_condition_ids_end_with_no_name(self) -> None:
        """The negative-control id is left unnamed: DMSO/non-inf name a condition."""
        index = build_compound_index(
            _feature_table(["CBK281357", "CBK008271"]), METADATA, NAME_LOOKUP
        )
        self.assertIsNone(_row(index, "CBK281357")["pert_iname"])
        self.assertEqual(_row(index, "CBK008271")["pert_iname"], "alpha-iname")

    def test_bracketed_control_keeps_its_own_name(self) -> None:
        """A bracketed positive control is named by the lookup, though it has no CBCS row."""
        row = _row(
            build_compound_index(_feature_table(["[flup]"]), METADATA, NAME_LOOKUP), "[flup]"
        )
        self.assertEqual(row["kind"], "control")
        self.assertIsNone(row["name"])
        self.assertEqual(row["pert_iname"], "Fluphenazine")

    def test_id_absent_from_the_lookup_keeps_its_annotation(self) -> None:
        """An unnamed id keeps an explicit null and its CBCS annotation."""
        row = _row(
            build_compound_index(_feature_table(["CBK011567"]), METADATA, NAME_LOOKUP),
            "CBK011567",
        )
        self.assertEqual(row["name"], "gamma")
        self.assertIsNone(row["pert_iname"])

    def test_join_is_on_the_raw_cbkid(self) -> None:
        """A salt variant inherits the CBCS annotation but not the base id's pert_iname."""
        row = _row(
            build_compound_index(_feature_table(["CBK008271G"]), METADATA, NAME_LOOKUP),
            "CBK008271G",
        )
        self.assertEqual(row["name"], "alpha")
        self.assertIsNone(row["pert_iname"])

    def test_names_are_stable_across_runs(self) -> None:
        """Two runs over the same lookup agree on every name, in any row order."""
        table = _feature_table(["CBK008271", "CBK000155", "CBK281357", "[flup]"])
        first = build_compound_index(table, METADATA, NAME_LOOKUP)
        second = build_compound_index(table, METADATA, NAME_LOOKUP.reverse())

        self.assertEqual(first["pert_iname"].to_list(), second["pert_iname"].to_list())


class NameLookupReportTests(SimpleTestCase):
    """The name_lookup block written into summary.json and the log (FREYA-2628)."""

    def test_report_counts(self) -> None:
        """Provenance, lookup size, named/unnamed rows and the excluded conditions."""
        index = build_compound_index(
            _feature_table(["CBK008271", "CBK281357", "CBK999999"]), METADATA, NAME_LOOKUP
        )
        report = name_lookup_report(
            index, NAME_LOOKUP, source_filename="lookup.feather", source_hash="a" * 64
        )

        self.assertEqual(report["source"], "lookup.feather")
        self.assertEqual(report["sha256"], "a" * 64)
        self.assertEqual(report["n_lookup_ids"], 3)
        self.assertEqual(report["n_named"], 1)
        self.assertEqual(report["n_unnamed"], 2)
        self.assertEqual(report["n_condition_rows_excluded"], 2)
        self.assertEqual(report["n_conflicting_ids"], 0)

    def test_conflicting_ids_are_counted(self) -> None:
        """An id with two names is reported, not silently deduplicated."""
        index = build_compound_index(_feature_table(["CBK000155"]), METADATA, CONFLICTING_LOOKUP)
        report = name_lookup_report(index, CONFLICTING_LOOKUP)
        self.assertEqual(report["n_conflicting_ids"], 1)

    def test_report_without_a_lookup(self) -> None:
        """With no lookup the block still exists, with a null source and no counts."""
        index = build_compound_index(_feature_table(["CBK008271"]), METADATA)
        report = name_lookup_report(index)

        self.assertIsNone(report["source"])
        self.assertIsNone(report["sha256"])
        self.assertEqual(report["n_lookup_ids"], 0)
        self.assertEqual(report["n_named"], 0)
        self.assertEqual(report["n_unnamed"], 0)
        self.assertEqual(report["n_condition_rows_excluded"], 0)
        self.assertEqual(report["n_conflicting_ids"], 0)
