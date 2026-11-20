"""Tests for portal data service helpers."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings

from portal_data import services
from portal_data.services import (
    apply_facet_filters,
    apply_text_search,
    build_facets,
    find_investigation_file,
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


class LoadAllItemsTests(TestCase):
    """Tests for loading MetaboLights study directories from the dataset root."""

    def setUp(self) -> None:
        """Create a temporary dataset root for each test."""
        self.tmpdir_context = tempfile.TemporaryDirectory()
        self.datasets_root = Path(self.tmpdir_context.name)
        cache.clear()

    def tearDown(self) -> None:
        """Remove the temporary dataset root."""
        self.tmpdir_context.cleanup()
        cache.clear()

    def _make_study(self, accession: str, title: str) -> Path:
        """Create a minimal study directory with an investigation file."""
        study = self.datasets_root / accession
        study.mkdir()
        (study / "i_Investigation.txt").write_text(f"Study Title\t{title}\n", encoding="utf-8")
        return study

    def _bump_root_mtime(self) -> None:
        """Force a distinct root mtime; filesystem timestamp granularity can be coarse."""
        stat = self.datasets_root.stat()
        os.utime(self.datasets_root, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))

    def test_load_all_items_is_cached_between_calls(self) -> None:
        """A second call reuses the cached items instead of re-parsing every study."""
        self._make_study("MTBLS1", "First")

        with (
            override_settings(DATASETS_ROOT=self.datasets_root),
            mock.patch(
                "portal_data.services.parse_investigation_file",
                wraps=parse_investigation_file,
            ) as parse_spy,
        ):
            first = load_all_items("metabolomics")
            second = load_all_items("metabolomics")

        self.assertEqual(parse_spy.call_count, 1)
        self.assertEqual(first, second)

    def test_new_study_dir_invalidates_cache(self) -> None:
        """Adding a study directory changes the root mtime and so the cache key."""
        self._make_study("MTBLS1", "First")

        with override_settings(DATASETS_ROOT=self.datasets_root):
            self.assertEqual(len(load_all_items("metabolomics")), 1)

            self._make_study("MTBLS2", "Second")
            self._bump_root_mtime()

            items = load_all_items("metabolomics")

        self.assertEqual([it["accession"] for it in items], ["MTBLS1", "MTBLS2"])

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

    def test_matches_parsed_metadata_fields(self) -> None:
        """Match on investigation-file metadata even when title and description don't."""
        items = [
            {"title": "A", "description": "", "factors": ["HbA1c", "Age"]},
            {"title": "B", "description": "", "design_types": ["untargeted metabolites"]},
            {"title": "C", "description": "", "platforms": ["Orbitrap Exploris"]},
            {"title": "D", "description": "", "technology": "NMR spectroscopy"},
            {"title": "E", "description": "", "publication_title": "Caries in children"},
            {"title": "F", "description": "", "publication_authors": "Svensson A, Lind B"},
            {"title": "G", "description": "", "publication_doi": "10.1000/xyz123"},
            {"title": "H", "description": "nothing relevant", "factors": ["Time"]},
        ]

        def titles(query: str) -> list[str]:
            return [item["title"] for item in apply_text_search(items, query)]

        self.assertEqual(titles("hba1c"), ["A"])
        self.assertEqual(titles("untargeted"), ["B"])
        self.assertEqual(titles("exploris"), ["C"])
        self.assertEqual(titles("nmr"), ["D"])
        self.assertEqual(titles("caries"), ["E"])
        self.assertEqual(titles("lind"), ["F"])
        self.assertEqual(titles("xyz123"), ["G"])

    def test_string_tags_do_not_stop_the_search(self) -> None:
        """A string-valued tags field no-match still lets later fields match."""
        items = [{"title": "A", "tags": "liver", "factors": ["HbA1c"]}]

        self.assertEqual(len(apply_text_search(items, "hba1c")), 1)

    def test_ignores_missing_none_and_non_search_fields(self) -> None:
        """Missing or None metadata is skipped, and paths/URLs are not searched."""
        items = [
            {
                "title": "A",
                "factors": None,
                "publication_title": None,
                "local_path": "/datasets/MTBLS1/plasma",
                "repo_url": "https://www.ebi.ac.uk/metabolights/plasma",
            }
        ]

        self.assertEqual(apply_text_search(items, "plasma"), [])


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


class MetabolightsWorkDirTests(SimpleTestCase):
    """The study finder's work dir lives inside DATASETS_ROOT but out of the listing."""

    def setUp(self) -> None:
        """Create a datasets root with one study and the work dir in it."""
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (self.root / "MTBLS1").mkdir()
        (self.root / services.METABOLIGHTS_SEARCH_DIRNAME).mkdir()
        self.enterContext(override_settings(DATASETS_ROOT=str(self.root)))

    def test_work_dir_is_a_subfolder_of_the_datasets_root(self) -> None:
        """get_metabolights_work_dir follows DATASETS_ROOT."""
        self.assertEqual(
            services.get_metabolights_work_dir(),
            self.root.resolve() / services.METABOLIGHTS_SEARCH_DIRNAME,
        )

    def test_study_listing_ignores_the_work_dir(self) -> None:
        """Only accession-named folders are treated as studies."""
        studies = services._iter_study_dirs("metabolomics")
        self.assertEqual([p.name for p in studies], ["MTBLS1"])


class EnsureWritableDirTests(SimpleTestCase):
    """ensure_writable_dir creates the directory and rejects unwritable ones."""

    def setUp(self) -> None:
        """Create a temporary parent directory."""
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def test_creates_missing_directories(self) -> None:
        """Missing parents are created, like mkdir -p."""
        target = self.tmp / "a" / "b"
        services.ensure_writable_dir(target)
        self.assertTrue(target.is_dir())

    def test_existing_unwritable_directory_raises_permission_error(self) -> None:
        """An existing but read-only directory is reported, not silently accepted."""
        with mock.patch("os.access", return_value=False), self.assertRaises(PermissionError):
            services.ensure_writable_dir(self.tmp)

    def test_uncreatable_directory_raises_os_error(self) -> None:
        """A path that can't be created (here: under a file) raises OSError."""
        blocker = self.tmp / "file"
        blocker.write_text("x")
        with self.assertRaises(OSError):
            services.ensure_writable_dir(blocker / "sub")


def _write_sample_file(
    study_dir: Path, name: str, header: list[str], rows: list[list[str]]
) -> None:
    """Write a tab-separated, quoted ISA-Tab sample file like MetaboLights does."""
    study_dir.mkdir(parents=True, exist_ok=True)
    lines = ["\t".join(f'"{cell}"' for cell in line) for line in [header, *rows]]
    (study_dir / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


class ParseSampleOrganismsTests(SimpleTestCase):
    """Organisms come from Characteristics[Organism] in the s_*.txt sample files."""

    HEADER = ["Source Name", "Characteristics[Organism]", "Characteristics[Organism part]"]

    def setUp(self) -> None:
        """Create an empty study directory."""
        self.study = Path(self.enterContext(tempfile.TemporaryDirectory())) / "MTBLS1"
        self.study.mkdir()

    def test_collects_distinct_organisms_sorted(self) -> None:
        """Each organism appears once, sorted case-insensitively."""
        rows = [
            ["s1", "Homo sapiens", "plasma"],
            ["s2", "Homo sapiens", "plasma"],
            ["s3", "escherichia coli", "whole organism"],
        ]
        _write_sample_file(self.study, "s_MTBLS1.txt", self.HEADER, rows)

        self.assertEqual(
            services.parse_sample_organisms(self.study), ["Escherichia coli", "Homo sapiens"]
        )

    def test_merges_strains_of_one_species(self) -> None:
        """Two strains of E. coli are one facet entry."""
        rows = [
            ["s1", "Escherichia coli E1777", "whole organism"],
            ["s2", "Escherichia coli E2265", "whole organism"],
        ]
        _write_sample_file(self.study, "s_MTBLS1.txt", self.HEADER, rows)

        self.assertEqual(services.parse_sample_organisms(self.study), ["Escherichia coli"])

    def test_splits_co_cultures_and_merges_spelling_variants(self) -> None:
        """'A;B' and 'A; B' name two organisms; case/spacing variants are one."""
        rows = [
            ["s1", "Streptococcus gordonii;Actinomyces naeslundii", "biofilm"],
            ["s2", "Streptococcus gordonii; Actinomyces  naeslundii", "biofilm"],
            ["s3", "streptococcus gordonii", "biofilm"],
        ]
        _write_sample_file(self.study, "s_MTBLS1.txt", self.HEADER, rows)

        self.assertEqual(
            services.parse_sample_organisms(self.study),
            ["Actinomyces naeslundii", "Streptococcus gordonii"],
        )

    def test_drops_control_and_missing_placeholders(self) -> None:
        """Blanks, growth medium, solvent and empty cells aren't organisms."""
        rows = [
            ["s1", "Trypanosoma brucei", "whole organism"],
            ["s2", "Blank", "Blank"],
            ["s3", "Medium", "Growth Medium"],
            ["s4", "solvent", "solvent"],
            ["s5", "", ""],
        ]
        _write_sample_file(self.study, "s_MTBLS1.txt", self.HEADER, rows)

        self.assertEqual(services.parse_sample_organisms(self.study), ["Trypanosoma brucei"])

    def test_combines_several_sample_files(self) -> None:
        """A study with more than one sample file gets the organisms of all of them."""
        _write_sample_file(self.study, "s_a.txt", self.HEADER, [["s1", "Homo sapiens", "x"]])
        _write_sample_file(self.study, "s_b.txt", self.HEADER, [["s1", "Mus musculus", "x"]])

        self.assertEqual(
            services.parse_sample_organisms(self.study), ["Homo sapiens", "Mus musculus"]
        )

    def test_no_sample_file_or_no_organism_column_gives_empty_list(self) -> None:
        """Studies fetched before sample files were downloaded simply have no organisms."""
        self.assertEqual(services.parse_sample_organisms(self.study), [])

        _write_sample_file(self.study, "s_MTBLS1.txt", ["Source Name", "Sample Name"], [["a", "b"]])
        self.assertEqual(services.parse_sample_organisms(self.study), [])

    def test_ignores_sample_files_in_subdirectories(self) -> None:
        """Older revisions under METADATA_REVISIONS aren't read."""
        revision = self.study / "METADATA_REVISIONS" / "MTBLS1_01"
        _write_sample_file(revision, "s_MTBLS1.txt", self.HEADER, [["s1", "Old organism", "x"]])
        _write_sample_file(self.study, "s_MTBLS1.txt", self.HEADER, [["s1", "Homo sapiens", "x"]])

        self.assertEqual(services.parse_sample_organisms(self.study), ["Homo sapiens"])


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}})
class OrganismFacetTests(SimpleTestCase):
    """The listing exposes organisms as a facet, a filter and searchable text."""

    def setUp(self) -> None:
        """Create a datasets root with two studies."""
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        header = ["Source Name", "Characteristics[Organism]"]
        for accession, organism in (("MTBLS1", "Homo sapiens"), ("MTBLS2", "Escherichia coli")):
            study = self.root / accession
            study.mkdir()
            (study / "i_Investigation.txt").write_text(
                f"Study Title\t{accession} study\n", encoding="utf-8"
            )
            _write_sample_file(study, f"s_{accession}.txt", header, [["s1", organism]])
        self.enterContext(override_settings(DATASETS_ROOT=str(self.root)))

    def _listing(self, **kwargs: object) -> dict:
        """Return the metabolomics listing with the organisms facet."""
        defaults = {"datatype": "metabolomics", "query": "", "filters": {}}
        return services.get_dataset_listing(facet_names=["organisms"], **{**defaults, **kwargs})

    def test_organisms_is_a_default_facet(self) -> None:
        """The metabolomics page shows Organisms among its facets."""
        config = services.get_datatype_config("metabolomics")
        self.assertIn("organisms", config.default_facets)

    def test_facet_counts_studies_per_organism(self) -> None:
        """Each organism is a facet bucket counting its studies."""
        buckets = self._listing()["facets"]["organisms"]
        self.assertEqual(
            {b["value"]: b["count"] for b in buckets}, {"Escherichia coli": 1, "Homo sapiens": 1}
        )

    def test_filter_and_search_by_organism(self) -> None:
        """Selecting an organism, or searching its name, narrows the listing."""
        filtered = self._listing(filters={"organisms": ["Escherichia coli"]})["items"]
        searched = self._listing(query="sapiens")["items"]

        self.assertEqual([item["id"] for item in filtered], ["MTBLS2"])
        self.assertEqual([item["id"] for item in searched], ["MTBLS1"])


class NormalizeOrganismTests(SimpleTestCase):
    """normalize_organism merges strains to species but leaves other names alone."""

    def test_reduces_strains_and_subspecies_to_the_species(self) -> None:
        """Strain codes and below-species ranks are dropped."""
        cases = {
            "Escherichia coli E1777": "Escherichia coli",
            "Escherichia coli K-12": "Escherichia coli",
            "Escherichia coli O157:H7": "Escherichia coli",
            "Escherichia coli strain Nissle 1917": "Escherichia coli",
            "Staphylococcus aureus MRSA": "Staphylococcus aureus",
            "Staphylococcus aureus subsp. aureus NCTC 8325": "Staphylococcus aureus",
            "Mycobacterium avium subsp. paratuberculosis": "Mycobacterium avium",
            "Salmonella enterica serovar Typhimurium": "Salmonella enterica",
            "Mus musculus C57BL/6J": "Mus musculus",
            "Streptococcus sp. ABC12": "Streptococcus sp.",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(services.normalize_organism(raw), expected)

    def test_normalises_case_and_spacing(self) -> None:
        """Genus capitalised, species lowercased, whitespace collapsed."""
        self.assertEqual(services.normalize_organism("escherichia  COLI"), "Escherichia coli")
        self.assertEqual(services.normalize_organism("Homo sapiens"), "Homo sapiens")

    def test_leaves_names_that_are_not_strains_alone(self) -> None:
        """Hybrids, genus-only names and non-binomial (virus) names are kept as written."""
        for name in (
            "Populus tremula x Populus tremuloides",
            "Gomphrena",
            "Severe acute respiratory syndrome coronavirus 2",
            "Influenza A virus (A/Puerto Rico/8/1934(H1N1))",
            "Hepatitis B virus",
        ):
            with self.subTest(name=name):
                self.assertEqual(services.normalize_organism(name), name)
