"""Tests for the EBI Search client used by the Genomic data page."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase

from portal_data.ebi_search import (
    BASE_QUERY,
    DATA_TYPES,
    EBI_SEARCH_URL,
    FACET_VALUE_COUNT,
    MAX_PAGE_SIZE,
    Cell,
    build_query,
    fetch_count,
    is_valid_facet_value,
    search,
)

RAW_READS = DATA_TYPES["raw-reads"]


def ebi_response(
    entries: list[dict] | None = None, facets: list[dict] | None = None, total: int | None = None
) -> dict:
    """Build a fake EBI Search response body."""
    entries = entries or []
    return {
        "hitCount": len(entries) if total is None else total,
        "entries": entries,
        "facets": facets or [],
    }


class TestBuildQuery(SimpleTestCase):
    """Tests for build_query."""

    def test_base_query_without_words(self):
        """Test an empty search is limited to Swedish pathogen records."""
        self.assertEqual(build_query(""), '(country:"Sweden") AND tag:pathogen')

    def test_words_are_anded(self):
        """Test every search word must match."""
        self.assertEqual(
            build_query("Escherichia coli"), f"{BASE_QUERY} AND (Escherichia AND coli)"
        )

    def test_query_syntax_is_stripped(self):
        """Test quotes, brackets, colons and operators can't alter the query."""
        self.assertEqual(
            build_query('host:"Homo" OR (x) *'),
            f"{BASE_QUERY} AND (host AND Homo AND OR AND x)",
        )

    def test_accessions_and_dotted_names_survive(self):
        """Test accessions and names with dots, dashes and underscores are kept whole."""
        self.assertEqual(
            build_query("ERX123 GII.4 SARS-CoV-2 a_b"),
            f"{BASE_QUERY} AND (ERX123 AND GII.4 AND SARS-CoV-2 AND a_b)",
        )


class TestFacetValues(SimpleTestCase):
    """Tests for is_valid_facet_value."""

    def test_values_with_commas_are_rejected(self):
        """Test values with commas (which EBI Search can't filter on) are rejected."""
        self.assertTrue(is_valid_facet_value("Homo sapiens"))
        self.assertFalse(is_valid_facet_value("Sweden, Stockholm"))
        self.assertFalse(is_valid_facet_value(""))


class TestSearch(SimpleTestCase):
    """Tests for search."""

    def setUp(self):
        """Clear the cache so results don't leak between tests."""
        cache.clear()

    @patch("portal_data.ebi_search.fetch_json")
    def test_request_params(self, mock_fetch: MagicMock):
        """Test the domain, query, fields, paging, facets and sort are sent."""
        mock_fetch.return_value = ebi_response()
        search(
            RAW_READS,
            text="coli",
            selected_facets={"classification": ["bacteria", "viruses"], "host": ["Homo sapiens"]},
            start=50,
            size=25,
            sort=("collection_date", True),
        )
        self.assertEqual(mock_fetch.call_args.kwargs["url"], f"{EBI_SEARCH_URL}/sra-experiment")
        params = mock_fetch.call_args.kwargs["params"]
        self.assertEqual(params["query"], f"{BASE_QUERY} AND (coli)")
        self.assertEqual(params["fields"], ",".join(RAW_READS.fields))
        self.assertEqual(params["start"], 50)
        self.assertEqual(params["size"], 25)
        self.assertEqual(params["facetcount"], FACET_VALUE_COUNT)
        self.assertEqual(
            params["facets"], "classification:bacteria,classification:viruses,host:Homo sapiens"
        )
        self.assertEqual(params["sort"], "collection_date:descending")

    @patch("portal_data.ebi_search.fetch_json")
    def test_unsortable_sort_unknown_facets_and_big_pages_are_dropped(self, mock_fetch: MagicMock):
        """Test only sortable fields, known facets and valid page sizes reach EBI Search."""
        mock_fetch.return_value = ebi_response()
        search(
            RAW_READS,
            selected_facets={"not_a_facet": ["x"], "host": ["A, B"]},
            size=1000,
            sort=("scientific_name", False),
        )
        params = mock_fetch.call_args.kwargs["params"]
        self.assertNotIn("sort", params)
        self.assertNotIn("facets", params)
        self.assertEqual(params["size"], MAX_PAGE_SIZE)

    @patch("portal_data.ebi_search.fetch_json")
    def test_records_are_parsed(self, mock_fetch: MagicMock):
        """Test entries become rows: dates formatted, lists joined, taxon ids linked."""
        mock_fetch.return_value = ebi_response(
            entries=[
                {
                    "acc": "ERX1",
                    "fields": {
                        "acc": ["ERX1"],
                        "scientific_name": ["Escherichia coli"],
                        "TAXON": ["562"],
                        "collection_date": ["20240102"],
                        "host": ["Homo sapiens", "Homo sapiens"],
                        "instrument_platform": ["ILLUMINA"],
                        "library_strategy": [],
                        "first_public_date": ["2024"],
                    },
                },
                {"fields": {"scientific_name": ["no accession"]}},
            ],
            total=7,
        )
        result = search(RAW_READS)
        self.assertEqual(result.total, 7)
        self.assertEqual(len(result.records), 1)
        record = result.records[0]
        self.assertEqual(record.accession, "ERX1")
        self.assertEqual(record.url, "https://www.ebi.ac.uk/ena/browser/view/ERX1")
        self.assertEqual(
            record.cells,
            (
                Cell("Escherichia coli"),
                Cell("562", "https://www.ebi.ac.uk/ena/browser/view/Taxon:562"),
                Cell("2024-01-02"),
                Cell("Homo sapiens"),
                Cell("ILLUMINA"),
                Cell(""),
                Cell("2024"),
            ),
        )

    @patch("portal_data.ebi_search.fetch_json")
    def test_facets_are_parsed_in_order_with_selection(self, mock_fetch: MagicMock):
        """Test facets follow FACET_FIELDS order, skip unknown/comma values, mark selection."""
        mock_fetch.return_value = ebi_response(
            facets=[
                {"id": "country", "label": "Country", "facetValues": [{"value": "Sweden"}]},
                {
                    "id": "host",
                    "label": "Host",
                    "facetValues": [
                        {"value": "Homo sapiens", "label": "Homo sapiens", "count": "12"},
                        {"value": "A, B", "label": "A, B", "count": 1},
                    ],
                },
                {
                    "id": "classification",
                    "label": "Classification",
                    "facetValues": [
                        {"value": "bacteria", "label": "Bacteria", "count": 10},
                        {"value": "viruses", "label": "Viruses", "count": 2},
                    ],
                },
            ]
        )
        result = search(
            RAW_READS, selected_facets={"classification": ["viruses"], "TAXON": ["562"]}
        )
        self.assertEqual(
            [facet.field for facet in result.facets], ["classification", "TAXON", "host"]
        )
        classification = result.facets[0]
        self.assertEqual(
            [(v.label, v.count, v.selected) for v in classification.values],
            [("Bacteria", 10, False), ("Viruses", 2, True)],
        )
        # a selected value missing from the response is still offered, so it can be unticked
        taxon = result.facets[1]
        self.assertEqual([(v.value, v.selected) for v in taxon.values], [("562", True)])
        host = result.facets[2]
        self.assertEqual([v.value for v in host.values], ["Homo sapiens"])

    @patch("portal_data.ebi_search.fetch_json")
    def test_results_are_cached(self, mock_fetch: MagicMock):
        """Test identical searches are served from the cache."""
        mock_fetch.return_value = ebi_response()
        search(RAW_READS, start=0)
        search(RAW_READS, start=0)
        search(RAW_READS, start=25)
        self.assertEqual(mock_fetch.call_count, 2)

    @patch("portal_data.ebi_search.fetch_json")
    def test_failed_or_invalid_response_returns_none(self, mock_fetch: MagicMock):
        """Test a failed request or unexpected body returns None."""
        mock_fetch.return_value = None
        self.assertIsNone(search(RAW_READS))
        mock_fetch.return_value = {"diagnostics": {"message": "bad"}}
        with self.assertLogs("portal_data.ebi_search", level="ERROR"):
            self.assertIsNone(search(RAW_READS, start=1))


class TestFetchCount(SimpleTestCase):
    """Tests for fetch_count."""

    def setUp(self):
        """Clear the cache so results don't leak between tests."""
        cache.clear()

    @patch("portal_data.ebi_search.fetch_json")
    def test_count(self, mock_fetch: MagicMock):
        """Test the hit count is returned, asking for no entries or facets."""
        mock_fetch.return_value = {"hitCount": 18960}
        self.assertEqual(fetch_count(RAW_READS, "coli"), 18960)
        params = mock_fetch.call_args.kwargs["params"]
        self.assertEqual(params["size"], 0)
        self.assertEqual(params["facetcount"], 0)
        self.assertEqual(params["query"], f"{BASE_QUERY} AND (coli)")

    @patch("portal_data.ebi_search.fetch_json")
    def test_failure_returns_none(self, mock_fetch: MagicMock):
        """Test a failed request returns None."""
        mock_fetch.return_value = None
        self.assertIsNone(fetch_count(RAW_READS))
