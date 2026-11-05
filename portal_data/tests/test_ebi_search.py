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
    REQUEST_TIMEOUT_SECONDS,
    Cell,
    _facet_filters,
    build_query,
    capitalise_first_letter,
    facet_label,
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

    def test_words_are_anded_and_matched_as_prefixes(self):
        """Test every search word must match, as a prefix."""
        self.assertEqual(
            build_query("Escherichi coli"), f"{BASE_QUERY} AND (Escherichi* AND coli*)"
        )

    def test_accession_prefix(self):
        """Test a partial accession matches the accessions starting with it."""
        self.assertEqual(build_query("PQ0642"), f"{BASE_QUERY} AND (PQ0642*)")

    def test_short_dashed_and_dotted_words_match_as_typed(self):
        """Test words EBI Search can't use wildcards on are matched in full."""
        self.assertEqual(
            build_query("ab GII.4 SARS-CoV-2 a_b"),
            f"{BASE_QUERY} AND (ab AND GII.4 AND SARS-CoV-2 AND a_b*)",
        )

    def test_and_or_are_ignored_in_any_case(self):
        """Test AND and OR (any case) are dropped rather than breaking the query."""
        expected = f"{BASE_QUERY} AND (coli* AND Escherichia*)"
        for text in ("coli AND Escherichia", "coli OR Escherichia", "coli and Escherichia"):
            with self.subTest(text=text):
                self.assertEqual(build_query(text), expected)

    def test_not_and_minus_exclude_the_next_word(self):
        """Test NOT (any case) or a leading "-" excludes a word instead of requiring it."""
        expected = f"{BASE_QUERY} AND (coli*) AND NOT Escherichia*"
        for text in ("coli NOT Escherichia", "coli not Escherichia", "coli -Escherichia"):
            with self.subTest(text=text):
                self.assertEqual(build_query(text), expected)

    def test_only_excluded_words(self):
        """Test a search with only excluded words excludes them from everything."""
        self.assertEqual(build_query("NOT coli"), f"{BASE_QUERY} AND NOT coli*")

    def test_dangling_operators_are_ignored(self):
        """Test operators with nothing to apply to leave just the base query."""
        self.assertEqual(build_query("AND OR NOT"), BASE_QUERY)
        self.assertEqual(build_query("coli NOT"), f"{BASE_QUERY} AND (coli*)")

    def test_query_syntax_is_stripped(self):
        """Test quotes, brackets, colons and wildcards can't alter the query."""
        self.assertEqual(
            build_query('host:"Homo" (x) * ?'),
            f"{BASE_QUERY} AND (host* AND Homo* AND x)",
        )


class TestFacetValues(SimpleTestCase):
    """Tests for is_valid_facet_value."""

    def test_printable_values_are_accepted(self):
        """Test any printable value, including brackets and commas, can be a filter."""
        for value in ("Homo sapiens", "[mallard]", "Sweden, Stockholm"):
            with self.subTest(value=value):
                self.assertTrue(is_valid_facet_value(value))

    def test_empty_long_and_unprintable_values_are_rejected(self):
        """Test empty, overlong and control-character values are rejected."""
        for value in ("", "x" * 201, "a\x00b"):
            with self.subTest(value=value):
                self.assertFalse(is_valid_facet_value(value))


class TestCapitaliseFirstLetter(SimpleTestCase):
    """Tests for capitalise_first_letter, used on facet value labels."""

    def test_capitalisation(self):
        """Test only the first letter changes, after any leading punctuation."""
        cases = {
            "bovine": "Bovine",
            "[mallard]": "[Mallard]",
            "[black-headed gull]": "[Black-headed gull]",
            "HIV-1 group M": "HIV-1 group M",
            "ILLUMINA": "ILLUMINA",
            "2024": "2024",
            "": "",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(capitalise_first_letter(text), expected)


class TestFacetLabel(SimpleTestCase):
    """Tests for facet_label, how facet values are shown."""

    def test_surrounding_brackets_are_stripped(self):
        """Test brackets around the whole value are dropped, others kept."""
        cases = {
            "[mallard]": "Mallard",
            "[black-headed gull]": "Black-headed gull",
            " [Homo sapiens] ": "Homo sapiens",
            "Influenza A virus (A/mallard/Sweden/1/2009(mixed))": (
                "Influenza A virus (A/mallard/Sweden/1/2009(mixed))"
            ),
            "[a] and [b]": "[A] and [b]",
            "[]": "[]",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(facet_label(text), expected)


class TestFacetFilters(SimpleTestCase):
    """Tests for how selected facets are sent: the facets parameter or the query."""

    def test_plain_values_use_the_facets_parameter(self):
        """Test values the facets parameter accepts are sent there, comma-separated."""
        self.assertEqual(
            _facet_filters({"classification": ["bacteria", "viruses"], "host": ["Homo sapiens"]}),
            ("classification:bacteria,classification:viruses,host:Homo sapiens", ""),
        )

    def test_a_single_comma_and_space_uses_the_facets_parameter(self):
        """Test locations like "Abisko, Stordalen Mire" go in the facets parameter."""
        self.assertEqual(
            _facet_filters({"region": ["Abisko, Stordalen Mire", "Stockholm"]}),
            ("region:Abisko, Stordalen Mire,region:Stockholm", ""),
        )

    def test_bracketed_values_go_in_the_query_as_regex_or_phrase(self):
        """Test values like "[mallard]" (Sequences hosts) become ORed regex/phrase matches."""
        self.assertEqual(
            _facet_filters({"host": ["[mallard]", "[black-headed gull]"]}),
            (
                "",
                r'(host:/\[mallard\]/ OR host:"mallard"'
                r' OR host:/\[black\-headed\ gull\]/ OR host:"black headed gull")',
            ),
        )

    def test_two_or_more_commas_go_in_the_query(self):
        """Test values with several commas, which the facets parameter can't take, use the query."""
        self.assertEqual(
            _facet_filters({"region": ["Vasterbotten, Lovanger, Angessjon"]}),
            (
                "",
                r"(region:/Vasterbotten\,\ Lovanger\,\ Angessjon/"
                r' OR region:"Vasterbotten Lovanger Angessjon")',
            ),
        )

    def test_one_awkward_value_moves_its_whole_facet_to_the_query(self):
        """Test a facet's values stay ORed together when one needs the query form."""
        facets_param, query = _facet_filters(
            {"classification": ["viruses"], "host": ["Homo sapiens", "[mallard]"]}
        )
        self.assertEqual(facets_param, "classification:viruses")
        self.assertEqual(
            query,
            r'(host:/Homo\ sapiens/ OR host:"Homo sapiens"'
            r' OR host:/\[mallard\]/ OR host:"mallard")',
        )

    def test_unknown_facets_and_invalid_values_are_dropped(self):
        """Test fields that aren't facets and invalid values are never sent."""
        self.assertEqual(_facet_filters({"not_a_facet": ["x"], "host": [""]}), ("", ""))


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
        self.assertEqual(mock_fetch.call_args.kwargs["timeout"], REQUEST_TIMEOUT_SECONDS)
        params = mock_fetch.call_args.kwargs["params"]
        self.assertEqual(params["query"], f"{BASE_QUERY} AND (coli*)")
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
            selected_facets={"not_a_facet": ["x"]},
            size=1000,
            sort=("scientific_name", False),
        )
        params = mock_fetch.call_args.kwargs["params"]
        self.assertNotIn("sort", params)
        self.assertNotIn("facets", params)
        self.assertEqual(params["size"], MAX_PAGE_SIZE)

    @patch("portal_data.ebi_search.fetch_json")
    def test_bracketed_facet_values_are_added_to_the_query(self, mock_fetch: MagicMock):
        """Test regex facet filters are ANDed onto the search query, others stay facets."""
        mock_fetch.return_value = ebi_response()
        search(
            DATA_TYPES["sequences"],
            text="coli",
            selected_facets={"classification": ["viruses"], "host": ["[mallard]"]},
        )
        params = mock_fetch.call_args.kwargs["params"]
        self.assertEqual(
            params["query"],
            rf'{BASE_QUERY} AND (coli*) AND (host:/\[mallard\]/ OR host:"mallard")',
        )
        self.assertEqual(params["facets"], "classification:viruses")

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
        self.assertEqual([v.value for v in host.values], ["Homo sapiens", "A, B"])

    @patch("portal_data.ebi_search.fetch_json")
    def test_facet_value_labels_are_capitalised_but_values_unchanged(self, mock_fetch: MagicMock):
        """Test labels are shown cleaned up while the value sent as a filter stays as-is."""
        mock_fetch.return_value = ebi_response(
            facets=[
                {
                    "id": "host",
                    "label": "Host",
                    "facetValues": [{"value": "[mallard]", "label": "[mallard]", "count": 3}],
                }
            ]
        )
        value = search(DATA_TYPES["sequences"]).facets[0].values[0]
        self.assertEqual((value.value, value.label), ("[mallard]", "Mallard"))

    @patch("portal_data.ebi_search.fetch_json")
    def test_region_facet_is_labelled_location(self, mock_fetch: MagicMock):
        """Test the region facet is shown as "Location" rather than EBI's "Region"."""
        mock_fetch.return_value = ebi_response(
            facets=[
                {
                    "id": "region",
                    "label": "Region",
                    "facetValues": [{"value": "Stockholm", "label": "Stockholm", "count": 3}],
                }
            ]
        )
        result = search(RAW_READS)
        self.assertEqual([(f.field, f.label) for f in result.facets], [("region", "Location")])

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
        self.assertEqual(params["query"], f"{BASE_QUERY} AND (coli*)")

    @patch("portal_data.ebi_search.fetch_json")
    def test_failure_returns_none(self, mock_fetch: MagicMock):
        """Test a failed request returns None."""
        mock_fetch.return_value = None
        self.assertIsNone(fetch_count(RAW_READS))
