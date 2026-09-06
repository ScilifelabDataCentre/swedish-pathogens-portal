"""Unit tests for the DRR cbkid reconciliation + compound index (FREYA-2557)."""

from __future__ import annotations

import polars as pl
from django.test import SimpleTestCase

from dashboard_visualisation.drr import (
    build_compound_index,
    normalize_cbkid,
    reconciliation_report,
)
from dashboard_visualisation.drr.loader import FeatureTable

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
