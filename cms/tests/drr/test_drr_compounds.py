"""Unit tests for the DRR cbkid reconciliation + compound index (FREYA-2557)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import polars as pl
from django.test import SimpleTestCase

from dashboard_visualisation.drr import (
    build_compound_index,
    build_name_lookup,
    compound_label,
    load_compound_names,
    name_lookup_report,
    normalize_cbkid,
    reconciliation_report,
)
from dashboard_visualisation.drr.compounds import compound_name
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


def _feature_table(cbkids: list[str], pert_types: list[str | None] | None = None) -> FeatureTable:
    """Build a minimal FeatureTable whose only relevant columns are ``cbkid`` and ``pert_type``.

    Args:
        cbkids: One id per well.
        pert_types: Each well's ``pert_type``, aligned with ``cbkids``; every
            well is treated (``trt``) when omitted.
    """
    types = pert_types if pert_types is not None else ["trt"] * len(cbkids)
    return FeatureTable(
        frame=pl.DataFrame(
            {"cbkid": cbkids, "pert_type": types},
            schema={"cbkid": pl.String, "pert_type": pl.String},
        ),
        metadata_columns=["cbkid", "pert_type"],
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
        """Non-CBCS ids with only control wells are controls, with a null stem and no annotation."""
        index = build_compound_index(
            _feature_table(["[stau]", "[etop]"], ["poscon", "poscon"]), METADATA
        )
        for token in ("[stau]", "[etop]"):
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
        index = build_compound_index(
            _feature_table(["CBK000155", "[stau]"], ["trt", "poscon"]), pl.DataFrame()
        )
        self.assertEqual(index.columns, ["cbkid", "cbkid_normalized", "kind", "n_profiles"])
        self.assertEqual(_row(index, "CBK000155")["kind"], "compound")
        self.assertEqual(_row(index, "[stau]")["kind"], "control")

    def test_cbcs_shaped_id_with_only_control_wells_is_a_control(self) -> None:
        """DMSO's CBCS-shaped id is a control: its wells decide, not its shape."""
        index = build_compound_index(
            _feature_table(["CBK281357", "CBK281357"], ["negcon", "non-inf"]), METADATA
        )
        row = _row(index, "CBK281357")
        self.assertEqual(row["kind"], "control")
        self.assertEqual(row["cbkid_normalized"], "CBK281357")

    def test_non_cbcs_id_with_treated_wells_is_a_compound(self) -> None:
        """Nirmatrelvir's prefixless id is a compound, its stem still null."""
        index = build_compound_index(
            _feature_table(["DO8167002", "DO8167002"], ["trt", "trt"]), METADATA
        )
        row = _row(index, "DO8167002")
        self.assertEqual(row["kind"], "compound")
        self.assertIsNone(row["cbkid_normalized"])
        self.assertIsNone(row["name"])

    def test_id_mixing_control_and_treated_wells_is_a_compound(self) -> None:
        """One treated well is enough to make an id a compound."""
        index = build_compound_index(
            _feature_table(["DO8167002", "DO8167002"], ["negcon", "trt"]), METADATA
        )
        self.assertEqual(_row(index, "DO8167002")["kind"], "compound")

    def test_positive_control_id_stays_a_control(self) -> None:
        """An id holding only poscon wells is a control."""
        index = build_compound_index(
            _feature_table(["[stau]", "[stau]"], ["poscon", "poscon"]), METADATA
        )
        self.assertEqual(_row(index, "[stau]")["kind"], "control")

    def test_table_without_pert_type_raises(self) -> None:
        """Without pert_type the rule has nothing to read, so it fails rather than guesses."""
        table = FeatureTable(
            frame=pl.DataFrame({"cbkid": ["CBK000155", "[stau]"]}),
            metadata_columns=["cbkid"],
            feature_columns=[],
        )
        with self.assertRaisesMessage(ValueError, "pert_type"):
            build_compound_index(table, METADATA)

    def test_unclassifiable_id_raises_naming_it(self) -> None:
        """An id with no treated well and a null or unknown pert_type is neither kind."""
        table = _feature_table(
            ["CBK000155", "CBK008271", "CBK008271", "CBK011567", "[stau]"],
            ["trt", "negcon", None, "mystery", "poscon"],
        )
        with self.assertRaises(ValueError) as caught:
            build_compound_index(table, METADATA)
        message = str(caught.exception)
        self.assertIn("CBK008271", message)
        self.assertIn("CBK011567", message)
        self.assertNotIn("CBK000155", message)
        self.assertNotIn("[stau]", message)


class ReconciliationReportTests(SimpleTestCase):
    """The reconciliation summary emitted into summary.json and the log."""

    def test_report_counts(self) -> None:
        """Counts split annotated/recovered/unannotated compounds from controls."""
        table = _feature_table(
            ["CBK000155", "CBK008271G", "CBK999999", "[stau]", "DO8167002"],
            ["trt", "trt", "trt", "poscon", "poscon"],
        )
        report = reconciliation_report(build_compound_index(table, METADATA))
        self.assertEqual(report["n_compound_ids"], 3)
        self.assertEqual(report["n_control_ids"], 2)
        self.assertEqual(report["n_annotated"], 2)
        self.assertEqual(report["n_recovered"], 1)
        self.assertEqual(report["n_unannotated"], 1)
        self.assertEqual(report["unmatched_cbkids"], ["CBK999999"])

    def test_unmatched_cbkids_sorted_and_excludes_controls(self) -> None:
        """Unmatched list is sorted and never includes control tokens."""
        table = _feature_table(["CBK999999", "CBK000900", "[stau]"], ["trt", "trt", "poscon"])
        report = reconciliation_report(build_compound_index(table, METADATA))
        self.assertEqual(report["unmatched_cbkids"], ["CBK000900", "CBK999999"])

    def test_report_follows_the_wells_not_the_id_shape(self) -> None:
        """Nirmatrelvir's id is the unannotated compound; DMSO's is a control."""
        table = _feature_table(
            ["CBK281357", "CBK281357", "DO8167002", "DO8167002", "CBK000155", "[stau]"],
            ["negcon", "non-inf", "trt", "trt", "trt", "poscon"],
        )
        names = pl.concat(
            [
                NAME_LOOKUP,
                pl.DataFrame(
                    {"cbkid": ["DO8167002"], "pert_iname": ["Nirmatrelvir"], "pert_type": ["trt"]}
                ),
            ]
        )
        report = reconciliation_report(build_compound_index(table, METADATA, names))
        self.assertEqual(report["unmatched_cbkids"], ["DO8167002"])
        self.assertEqual(report["n_compound_ids"], 2)
        self.assertEqual(report["n_control_ids"], 2)

    def test_report_without_metadata(self) -> None:
        """With no annotations every compound is reported unannotated."""
        table = _feature_table(["CBK000155", "[stau]"], ["trt", "poscon"])
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

    def test_null_pert_type_raises(self) -> None:
        """An unclassifiable row stops the run: nothing decides it but pert_type."""
        path = self._write_ipc(
            NAME_LOOKUP.with_columns(
                pl.when(pl.col("cbkid") == "CBK008271")
                .then(None)
                .otherwise(pl.col("pert_type"))
                .alias("pert_type")
            )
        )

        with self.assertRaisesMessage(ValueError, "no 'pert_type'"):
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

    def test_null_pert_type_is_not_a_condition_row(self) -> None:
        """A row with no pert_type is neither dropped nor reported as excluded."""
        names = pl.DataFrame(
            {
                "cbkid": ["CBK008271", "CBK281357"],
                "pert_iname": ["alpha-iname", "DMSO"],
                "pert_type": [None, "negcon"],
            }
        )

        lookup = build_name_lookup(names)
        report = name_lookup_report(
            build_compound_index(_feature_table(["CBK008271"]), METADATA, names), names
        )

        self.assertEqual(lookup["cbkid"].to_list(), ["CBK008271"])
        self.assertEqual(report["n_condition_rows_excluded"], 1)
        self.assertEqual(report["n_named"], 1)


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
            _feature_table(["CBK281357", "CBK281357", "CBK008271"], ["negcon", "non-inf", "trt"]),
            METADATA,
            NAME_LOOKUP,
        )
        self.assertIsNone(_row(index, "CBK281357")["pert_iname"])
        self.assertEqual(_row(index, "CBK008271")["pert_iname"], "alpha-iname")

    def test_bracketed_control_keeps_its_own_name(self) -> None:
        """A bracketed positive control is named by the lookup, though it has no CBCS row."""
        row = _row(
            build_compound_index(_feature_table(["[flup]"], ["poscon"]), METADATA, NAME_LOOKUP),
            "[flup]",
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
        table = _feature_table(
            ["CBK008271", "CBK000155", "CBK281357", "[flup]"], ["trt", "trt", "negcon", "poscon"]
        )
        first = build_compound_index(table, METADATA, NAME_LOOKUP)
        second = build_compound_index(table, METADATA, NAME_LOOKUP.reverse())

        self.assertEqual(first["pert_iname"].to_list(), second["pert_iname"].to_list())


class NameLookupReportTests(SimpleTestCase):
    """The name_lookup block written into summary.json and the log (FREYA-2628)."""

    def test_report_counts(self) -> None:
        """Provenance, lookup size, named/unnamed rows and the excluded conditions."""
        index = build_compound_index(
            _feature_table(["CBK008271", "CBK281357", "CBK999999"], ["trt", "negcon", "trt"]),
            METADATA,
            NAME_LOOKUP,
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


class CompoundLabelTests(SimpleTestCase):
    """The one naming rule every reader-facing compound name goes through (FREYA-3126)."""

    def test_a_compound_without_a_cbcs_name_falls_back_to_pert_iname(self) -> None:
        """Nirmatrelvir has no CBCS row, so its own name labels it."""
        self.assertEqual(
            compound_label("DO8167002", name=None, pert_iname="Nirmatrelvir", kind="compound"),
            "Nirmatrelvir (DO8167002)",
        )

    def test_a_blank_cbcs_name_falls_back_too(self) -> None:
        """A whitespace-only name is no name."""
        self.assertEqual(
            compound_label("DO8167002", name="  ", pert_iname="Nirmatrelvir", kind="compound"),
            "Nirmatrelvir (DO8167002)",
        )

    def test_the_cbcs_name_wins_over_pert_iname(self) -> None:
        """The fallback is only a fallback."""
        self.assertEqual(
            compound_label("CBK008271", name="alpha", pert_iname="alpha-iname", kind="compound"),
            "alpha (CBK008271)",
        )

    def test_a_control_keeps_its_control_label(self) -> None:
        """A control with a pert_iname still reads '<id> (control)'."""
        self.assertEqual(
            compound_label("[flup]", name=None, pert_iname="Fluphenazine", kind="control"),
            "[flup] (control)",
        )

    def test_a_compound_with_neither_name_is_its_bare_id(self) -> None:
        """No name and a blank pert_iname leave the id alone."""
        self.assertEqual(
            compound_label("CBK999999", name=None, pert_iname=" ", kind="compound"), "CBK999999"
        )


class CompoundNameTests(SimpleTestCase):
    """The name half of the naming rule, shared by the label and the table's Name (FREYA-3126)."""

    def test_the_cbcs_name_wins(self) -> None:
        """The fallback is only a fallback."""
        self.assertEqual(compound_name("alpha", "alpha-iname"), "alpha")

    def test_a_blank_or_missing_cbcs_name_falls_back_to_pert_iname(self) -> None:
        """A missing or whitespace-only name is no name."""
        self.assertEqual(compound_name(None, "Nirmatrelvir"), "Nirmatrelvir")
        self.assertEqual(compound_name("  ", "Nirmatrelvir"), "Nirmatrelvir")

    def test_two_blank_names_are_no_name(self) -> None:
        """Neither a missing nor a whitespace-only value is returned."""
        for name, pert_iname in ((None, None), (" ", None), (None, " "), ("", "  ")):
            with self.subTest(name=name, pert_iname=pert_iname):
                self.assertIsNone(compound_name(name, pert_iname))
