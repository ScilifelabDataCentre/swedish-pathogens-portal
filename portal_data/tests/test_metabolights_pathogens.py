"""Tests for portal_data.metabolights.pathogens and the Pathogens facet."""

from __future__ import annotations

import csv
import os
import tempfile
from pathlib import Path

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from portal_data import services
from portal_data.metabolights import europepmc, pathogens

MAPPING = {"e. coli": "Escherichia coli", "etec": "Escherichia coli", "covid": "SARS-CoV-2"}


def _write_papers_csv(path: Path, rows: list[tuple[str, str]]) -> None:
    """Write a minimal papers CSV of (metabolights_accessions, matched_keywords) rows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["epmc_id", "metabolights_accessions", "matched_keywords"])
        for i, (accessions, keywords) in enumerate(rows):
            writer.writerow([i, accessions, keywords])


class PathogenMappingFileTests(SimpleTestCase):
    """The bundled keyword -> pathogen mapping stays consistent with the keyword list."""

    def setUp(self) -> None:
        """Read the mapping file and the search keyword list."""
        with pathogens.PATHOGEN_KEYWORDS_CSV.open(encoding="utf-8", newline="") as f:
            self.rows = list(csv.DictReader(f))
        self.keywords = europepmc.load_keywords(europepmc.DEFAULT_KEYWORDS_CSV)

    def test_every_mapped_keyword_is_a_search_keyword(self) -> None:
        """A mapping for a keyword the search never matches would never apply."""
        known = set(self.keywords)
        unknown = [row["keyword"] for row in self.rows if row["keyword"] not in known]
        self.assertEqual(unknown, [])

    def test_each_keyword_names_one_pathogen(self) -> None:
        """Rows are complete, and no keyword (ignoring case) maps to two pathogens."""
        seen: dict[str, str] = {}
        for row in self.rows:
            self.assertTrue(row["keyword"].strip() and row["pathogen"].strip(), row)
            key = row["keyword"].casefold()
            self.assertEqual(seen.setdefault(key, row["pathogen"]), row["pathogen"], row)

    def test_ambiguous_and_generic_keywords_are_not_mapped(self) -> None:
        """Keywords that would mostly produce false pathogens stay out."""
        mapping = pathogens.load_pathogen_map()
        for keyword in ("host", "biofilm", "bacteria", "pneumonia", "coronavirus", "GAS", "VRE"):
            with self.subTest(keyword=keyword):
                self.assertNotIn(keyword.casefold(), mapping)

    def test_synonyms_share_one_pathogen(self) -> None:
        """Different names for one pathogen map to the same facet value."""
        mapping = pathogens.load_pathogen_map()
        self.assertEqual(
            {mapping[k.casefold()] for k in ("E. coli", "Escherichia coli", "ETEC")},
            {"Escherichia coli"},
        )
        self.assertEqual(mapping["covid-19"], "SARS-CoV-2")
        self.assertEqual(mapping["tuberculosis"], "Mycobacterium tuberculosis")


class PathogensByAccessionTests(SimpleTestCase):
    """Studies get the mapped pathogens of all papers that link to them."""

    def setUp(self) -> None:
        """Create a temporary directory for a papers CSV."""
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.papers = self.tmp / "papers.csv"

    def test_maps_keywords_and_merges_papers_per_study(self) -> None:
        """Synonyms merge, unmapped keywords are ignored, and papers combine per study."""
        _write_papers_csv(
            self.papers,
            [
                ("MTBLS1", "E. coli; ETEC; host; biofilm"),
                ("MTBLS1; mtbls2", "COVID"),
                ("MTBLS3", "host; bacteria"),
            ],
        )

        result = pathogens.pathogens_by_accession(self.papers, MAPPING)

        self.assertEqual(
            result,
            {"MTBLS1": ["Escherichia coli", "SARS-CoV-2"], "MTBLS2": ["SARS-CoV-2"]},
        )

    def test_missing_search_results_give_no_pathogens(self) -> None:
        """Before any search has run, every study simply has no pathogens."""
        self.assertEqual(pathogens.pathogens_by_accession(self.tmp / "nope.csv", MAPPING), {})


class PathogenFacetTests(SimpleTestCase):
    """The listing exposes pathogens from the search results as a facet."""

    def setUp(self) -> None:
        """Create a datasets root with two studies and search results for one."""
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        for accession in ("MTBLS1", "MTBLS2"):
            (self.root / accession).mkdir()
            (self.root / accession / "i_Investigation.txt").write_text(
                f"Study Title\t{accession} study\n", encoding="utf-8"
            )
        self.papers = self.root / services.METABOLIGHTS_SEARCH_DIRNAME / europepmc.PAPERS_OUTPUT_CSV
        _write_papers_csv(self.papers, [("MTBLS1", "Escherichia coli; host")])
        self.enterContext(override_settings(DATASETS_ROOT=str(self.root)))
        cache.clear()
        self.addCleanup(cache.clear)

    def _listing(self, **kwargs: object) -> dict:
        """Return the metabolomics listing with the pathogens facet."""
        defaults = {"datatype": "metabolomics", "query": "", "filters": {}}
        return services.get_dataset_listing(facet_names=["pathogens"], **{**defaults, **kwargs})

    def test_pathogens_is_a_default_facet(self) -> None:
        """The metabolomics page shows Pathogens among its facets."""
        self.assertIn("pathogens", services.get_datatype_config("metabolomics").default_facets)

    def test_facet_filter_and_search(self) -> None:
        """The study's pathogen is a facet bucket, a filter and searchable."""
        listing = self._listing()
        self.assertEqual(
            [(b["value"], b["count"]) for b in listing["facets"]["pathogens"]],
            [("Escherichia coli", 1)],
        )
        filtered = self._listing(filters={"pathogens": ["Escherichia coli"]})["items"]
        self.assertEqual([item["id"] for item in filtered], ["MTBLS1"])
        self.assertEqual(
            [item["id"] for item in self._listing(query="escherichia")["items"]], ["MTBLS1"]
        )

    def test_new_search_results_show_without_waiting_for_the_cache(self) -> None:
        """Rewriting the papers CSV changes the cache key, so the listing updates at once."""
        self.assertEqual(self._listing()["items"][1]["pathogens"], [])  # MTBLS2

        _write_papers_csv(self.papers, [("MTBLS2", "COVID-19")])
        stat = self.papers.stat()
        os.utime(self.papers, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))

        items = {item["id"]: item for item in self._listing()["items"]}
        self.assertEqual(items["MTBLS2"]["pathogens"], ["SARS-CoV-2"])
        self.assertEqual(items["MTBLS1"]["pathogens"], [])
