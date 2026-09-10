"""Tests for portal data service helpers."""

from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

from django.test import TestCase, override_settings

from portal_data.services import (
    apply_facet_filters,
    apply_text_search,
    build_facets,
    find_investigation_file,
    list_study_files,
    load_all_items,
    parse_investigation_file,
)


class ParseInvestigationFileTests(TestCase):
    """Tests for parsing ISA investigation files into study metadata."""

    def setUp(self) -> None:
        """Create a temporary directory for each test."""
        self.tmpdir_context = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmpdir_context.name)

    def tearDown(self) -> None:
        """Remove the temporary directory."""
        self.tmpdir_context.cleanup()

    def test_parse_investigation_file_extracts_study_metadata(self) -> None:
        """Parse study metadata fields from an ISA investigation file."""
        investigation = self.tmp_path / "i_Investigation.txt"
        investigation.write_text(
            "\n".join(
                [
                    "Study Title\tExample metabolomics study",
                    "Study Description\tA useful description.",
                    "Study Public Release Date\t2024-01-15",
                    "Study Factor Name\tTreatment\tTimepoint",
                    "Study Design Type\tcase control design",
                    "Study Assay Technology Platform\tLC-MS",
                    "Study Assay Technology Type\tmass spectrometry",
                ]
            ),
            encoding="utf-8",
        )

        meta = parse_investigation_file(investigation)

        self.assertEqual(meta["study_title"], "Example metabolomics study")
        self.assertEqual(meta["study_description"], "A useful description.")
        self.assertEqual(meta["study_public_release_date"], "2024-01-15")
        self.assertEqual(meta["factors"], ["Treatment", "Timepoint"])
        self.assertEqual(meta["design_types"], ["case control design"])
        self.assertEqual(meta["platforms"], ["LC-MS"])
        self.assertEqual(meta["technology"], "mass spectrometry")

    def test_parse_investigation_file_returns_empty_dict_for_missing_file(self) -> None:
        """Return an empty dict when the investigation file doesn't exist."""
        missing = self.tmp_path / "does_not_exist.txt"

        self.assertEqual(parse_investigation_file(missing), {})

    def test_parse_investigation_file_ignores_malformed_and_unknown_lines(self) -> None:
        """Skip blank lines, lines without a tab, and lines with no values."""
        investigation = self.tmp_path / "i_Investigation.txt"
        investigation.write_text(
            "\n".join(
                [
                    "",
                    "Not a tab-separated line",
                    "Study Title\t",
                    "Some Unrecognised Key\tsome value",
                    "Study Title\tReal title",
                ]
            ),
            encoding="utf-8",
        )

        meta = parse_investigation_file(investigation)

        self.assertEqual(meta, {"study_title": "Real title"})


class FindInvestigationFileTests(TestCase):
    """Tests for locating a study's investigation file, preferring revisions."""

    def setUp(self) -> None:
        """Create a temporary study directory for each test."""
        self.tmpdir_context = tempfile.TemporaryDirectory()
        self.study_dir = Path(self.tmpdir_context.name)

    def tearDown(self) -> None:
        """Remove the temporary study directory."""
        self.tmpdir_context.cleanup()

    def test_returns_top_level_file_when_no_revisions_exist(self) -> None:
        """Fall back to the top-level investigation file with no revisions dir."""
        top_level = self.study_dir / "i_Investigation.txt"
        top_level.write_text("Study Title\tTop level\n", encoding="utf-8")

        self.assertEqual(find_investigation_file(self.study_dir), top_level)

    def test_prefers_the_latest_revision_over_top_level(self) -> None:
        """Prefer the most recent METADATA_REVISIONS entry over the top-level file."""
        (self.study_dir / "i_Investigation.txt").write_text(
            "Study Title\tTop level\n", encoding="utf-8"
        )

        rev_root = self.study_dir / "METADATA_REVISIONS"
        older = rev_root / "2023-01-01"
        newer = rev_root / "2024-06-01"
        older.mkdir(parents=True)
        newer.mkdir(parents=True)
        (older / "i_Investigation.txt").write_text(
            "Study Title\tOlder revision\n", encoding="utf-8"
        )
        newest_file = newer / "i_Investigation.txt"
        newest_file.write_text("Study Title\tNewer revision\n", encoding="utf-8")

        self.assertEqual(find_investigation_file(self.study_dir), newest_file)

    def test_falls_back_to_top_level_when_revisions_have_no_investigation_file(self) -> None:
        """Fall back to the top-level file when revision dirs exist but are empty."""
        top_level = self.study_dir / "i_Investigation.txt"
        top_level.write_text("Study Title\tTop level\n", encoding="utf-8")

        rev_root = self.study_dir / "METADATA_REVISIONS"
        (rev_root / "2024-01-01").mkdir(parents=True)

        self.assertEqual(find_investigation_file(self.study_dir), top_level)

    def test_returns_none_when_no_investigation_file_exists(self) -> None:
        """Return None when neither a revision nor a top-level file is present."""
        self.assertIsNone(find_investigation_file(self.study_dir))


class ListStudyFilesTests(TestCase):
    """Tests for listing files available within a study directory."""

    def setUp(self) -> None:
        """Create a temporary study directory for each test."""
        self.tmpdir_context = tempfile.TemporaryDirectory()
        self.study_dir = Path(self.tmpdir_context.name)

    def tearDown(self) -> None:
        """Remove the temporary study directory."""
        self.tmpdir_context.cleanup()

    def test_returns_empty_list_for_an_empty_directory(self) -> None:
        """Return an empty list when the study directory has no files."""
        self.assertEqual(list_study_files(self.study_dir), [])

    def test_lists_nested_files_sorted_by_relative_path(self) -> None:
        """List files recursively with forward-slash relpaths, sorted."""
        (self.study_dir / "b_top.txt").write_text("top", encoding="utf-8")
        nested_dir = self.study_dir / "subdir"
        nested_dir.mkdir()
        (nested_dir / "a_nested.txt").write_text("nested contents", encoding="utf-8")

        files = list_study_files(self.study_dir)

        self.assertEqual([f["relpath"] for f in files], ["b_top.txt", "subdir/a_nested.txt"])
        self.assertEqual(files[0]["name"], "b_top.txt")
        self.assertEqual(files[0]["size"], len(b"top"))
        self.assertIsInstance(files[0]["mtime"], datetime)
        self.assertEqual(files[1]["name"], "a_nested.txt")
        self.assertEqual(files[1]["size"], len(b"nested contents"))


class LoadAllItemsTests(TestCase):
    """Tests for loading MetaboLights study directories from the dataset root."""

    def setUp(self) -> None:
        """Create a temporary dataset root for each test."""
        self.tmpdir_context = tempfile.TemporaryDirectory()
        self.datasets_root = Path(self.tmpdir_context.name)

    def tearDown(self) -> None:
        """Remove the temporary dataset root."""
        self.tmpdir_context.cleanup()

    def test_load_all_items_reads_valid_metabolights_dirs(self) -> None:
        """Load only valid MetaboLights study directories from the dataset root."""
        study = self.datasets_root / "MTBLS9999"
        study.mkdir()
        (study / "i_Investigation.txt").write_text(
            "Study Title\tExample study\nStudy Public Release Date\t2024-01-15\n",
            encoding="utf-8",
        )

        ignored = self.datasets_root / "not-a-study"
        ignored.mkdir()

        with override_settings(DATASETS_ROOT=self.datasets_root):
            items = load_all_items("metabolomics")

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["accession"], "MTBLS9999")
        self.assertEqual(items[0]["title"], "Example study")
        self.assertEqual(items[0]["year"], "2024")


class BuildFacetsTests(TestCase):
    """Tests for building facet buckets from dataset listing items."""

    def test_counts_scalar_field_values(self) -> None:
        """Count occurrences of a scalar facet field across items."""
        items = [
            {"repository": "MetaboLights"},
            {"repository": "MetaboLights"},
            {"repository": "GEO"},
        ]

        facets = build_facets(
            items=items, facet_names=["repository"], filters=None, datatype="metabolomics"
        )

        self.assertEqual(
            facets["repository"],
            [
                {"value": "GEO", "count": 1, "checked": False},
                {"value": "MetaboLights", "count": 2, "checked": False},
            ],
        )

    def test_counts_list_valued_field_values_separately(self) -> None:
        """Count each value of a list-valued facet field independently."""
        items = [
            {"platforms": ["LC-MS", "NMR"]},
            {"platforms": ["LC-MS"]},
        ]

        facets = build_facets(
            items=items, facet_names=["platforms"], filters=None, datatype="metabolomics"
        )

        self.assertEqual(
            facets["platforms"],
            [
                {"value": "LC-MS", "count": 2, "checked": False},
                {"value": "NMR", "count": 1, "checked": False},
            ],
        )

    def test_excludes_items_missing_the_facet_value(self) -> None:
        """Skip items where the facet field is missing, None, or empty."""
        items = [
            {"repository": "MetaboLights"},
            {"repository": None},
            {"repository": ""},
            {"repository": []},
            {},
        ]

        facets = build_facets(
            items=items, facet_names=["repository"], filters=None, datatype="metabolomics"
        )

        self.assertEqual(
            facets["repository"], [{"value": "MetaboLights", "count": 1, "checked": False}]
        )

    def test_year_facet_sorts_numeric_descending(self) -> None:
        """Sort the year facet newest-first when all values are integers."""
        items = [{"year": "2021"}, {"year": "2024"}, {"year": "2023"}]

        facets = build_facets(
            items=items, facet_names=["year"], filters=None, datatype="metabolomics"
        )

        self.assertEqual([bucket["value"] for bucket in facets["year"]], ["2024", "2023", "2021"])

    def test_year_facet_falls_back_to_string_sort_for_non_integer_values(self) -> None:
        """Sort the year facet as strings, descending, when a value isn't an integer."""
        items = [{"year": "2021"}, {"year": "unknown"}]

        facets = build_facets(
            items=items, facet_names=["year"], filters=None, datatype="metabolomics"
        )

        self.assertEqual([bucket["value"] for bucket in facets["year"]], ["unknown", "2021"])

    def test_checked_reflects_active_filters(self) -> None:
        """Mark a bucket as checked when its value is an active filter."""
        items = [{"repository": "MetaboLights"}, {"repository": "GEO"}]

        facets = build_facets(
            items=items,
            facet_names=["repository"],
            filters={"repository": ["MetaboLights"]},
            datatype="metabolomics",
        )

        checked_by_value = {bucket["value"]: bucket["checked"] for bucket in facets["repository"]}
        self.assertEqual(checked_by_value, {"GEO": False, "MetaboLights": True})


class ApplyTextSearchTests(TestCase):
    """Tests for the free-text search applied to dataset listing items."""

    def test_empty_query_returns_all_items_unchanged(self) -> None:
        """Return every item unchanged when the query is empty."""
        items = [{"title": "Plasma study"}]

        self.assertEqual(apply_text_search(items, ""), items)

    def test_matches_title_case_insensitively(self) -> None:
        """Match items whose title contains the query, ignoring case."""
        items = [{"title": "Plasma metabolomics"}, {"title": "Urine metabolomics"}]

        results = apply_text_search(items, "PLASMA")

        self.assertEqual([item["title"] for item in results], ["Plasma metabolomics"])

    def test_matches_accession_and_description(self) -> None:
        """Match items by accession or description as well as title."""
        items = [
            {"title": "A", "accession": "MTBLS1001", "description": ""},
            {"title": "B", "accession": "MTBLS2002", "description": "mentions plasma"},
            {"title": "C", "accession": "MTBLS3003", "description": ""},
        ]

        results = apply_text_search(items, "plasma")

        self.assertEqual([item["accession"] for item in results], ["MTBLS2002"])

    def test_matches_list_and_string_tags(self) -> None:
        """Match items via list-valued or string-valued tags."""
        items = [
            {"title": "A", "tags": ["liver", "plasma"]},
            {"title": "B", "tags": "plasma sample"},
            {"title": "C", "tags": ["urine"]},
        ]

        results = apply_text_search(items, "plasma")

        self.assertEqual([item["title"] for item in results], ["A", "B"])

    def test_no_match_returns_empty_list(self) -> None:
        """Return an empty list when nothing matches the query."""
        items = [{"title": "Plasma metabolomics"}]

        self.assertEqual(apply_text_search(items, "nonexistent"), [])


class ApplyFacetFiltersTests(TestCase):
    """Tests for applying selected facet filters to dataset listing items."""

    def test_no_filters_returns_all_items(self) -> None:
        """Return every item unchanged when there are no active filters."""
        items = [{"repository": "MetaboLights"}, {"repository": "GEO"}]

        self.assertEqual(apply_facet_filters(items, {}), items)

    def test_filters_by_scalar_field(self) -> None:
        """Keep only items whose scalar field value matches an active filter."""
        items = [{"repository": "MetaboLights"}, {"repository": "GEO"}]

        results = apply_facet_filters(items, {"repository": ["MetaboLights"]})

        self.assertEqual(results, [{"repository": "MetaboLights"}])

    def test_filters_by_list_valued_field(self) -> None:
        """Keep items whose list-valued field contains any active filter value."""
        items = [{"platforms": ["LC-MS", "NMR"]}, {"platforms": ["GC-MS"]}]

        results = apply_facet_filters(items, {"platforms": ["NMR"]})

        self.assertEqual(results, [{"platforms": ["LC-MS", "NMR"]}])

    def test_multiple_filters_are_combined_with_and(self) -> None:
        """Require items to satisfy every active filter field."""
        items = [
            {"repository": "MetaboLights", "year": "2024"},
            {"repository": "MetaboLights", "year": "2023"},
            {"repository": "GEO", "year": "2024"},
        ]

        results = apply_facet_filters(items, {"repository": ["MetaboLights"], "year": ["2024"]})

        self.assertEqual(results, [{"repository": "MetaboLights", "year": "2024"}])

    def test_items_missing_the_filtered_field_are_excluded(self) -> None:
        """Exclude items that don't have the filtered field at all."""
        items = [{"repository": "MetaboLights"}, {"year": "2024"}]

        results = apply_facet_filters(items, {"repository": ["MetaboLights"]})

        self.assertEqual(results, [{"repository": "MetaboLights"}])
