"""Tests for the ENA Portal API client."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

from django.core.cache import cache
from django.test import SimpleTestCase

from portal_data.ena import (
    ENA_PORTAL_API_URL,
    MAX_BROWSABLE_RECORDS,
    RECORD_TYPES,
    Cell,
    EnaRecord,
    _parse_count,
    build_download_url,
    build_query,
    fetch_count,
    fetch_records,
    filter_records,
    sort_records,
)

READ_RUN = RECORD_TYPES["read_run"]
QUERY = 'tax_tree(2697049) AND country="Sweden*"'


class TestBuildQuery(SimpleTestCase):
    """Tests for build_query."""

    def test_single_taxon(self):
        """Test a single taxon id is wrapped in tax_tree and scoped to Sweden."""
        self.assertEqual(build_query([2697049]), '(tax_tree(2697049)) AND country="Sweden*"')

    def test_multiple_taxa_are_ored_sorted_and_deduplicated(self):
        """Test multiple taxa are OR-ed together, sorted, with duplicates removed."""
        self.assertEqual(
            build_query([11320, 11520, 11320]),
            '(tax_tree(11320) OR tax_tree(11520)) AND country="Sweden*"',
        )

    def test_non_integer_taxon_is_rejected(self):
        """Test a value that isn't an integer can't be injected into the query."""
        with self.assertRaises(ValueError):
            build_query(["1) OR (tax_tree(2"])

    def test_no_taxa_is_rejected(self):
        """Test an empty taxon list raises rather than matching everything from Sweden."""
        with self.assertRaises(ValueError):
            build_query([])


class TestParseCount(SimpleTestCase):
    """Tests for _parse_count, which handles the count endpoint's plain-text body."""

    def test_header_and_number(self):
        """Test the real response shape, a "count" header line then the number."""
        self.assertEqual(_parse_count("count\n333\n"), 333)

    def test_bare_number(self):
        """Test a body with just the number is also accepted."""
        self.assertEqual(_parse_count("0"), 0)

    def test_invalid_values(self):
        """Test bodies without a non-negative integer on the last line return None."""
        for body in ("", "count\n", "count\nabc", "count\n-1", "count\n\u00b2", '{"count": 3}'):
            with self.subTest(body=body):
                self.assertIsNone(_parse_count(body))


class TestEnaRecord(SimpleTestCase):
    """Tests for EnaRecord.from_ena_result."""

    def test_full_record(self):
        """Test a record is flattened into cells in column order, linking to the ENA browser."""
        record = EnaRecord.from_ena_result(
            {
                "run_accession": "ERR123",
                "scientific_name": "Severe acute respiratory syndrome coronavirus 2",
                "tax_id": "2697049",
                "collection_date": "2021-03-01",
                "country": "Sweden: Uppsala",
                "instrument_platform": "ILLUMINA",
                "library_strategy": "AMPLICON",
                "first_public": "2021-04-01",
            },
            READ_RUN,
        )
        self.assertEqual(record.accession, "ERR123")
        self.assertEqual(record.url, "https://www.ebi.ac.uk/ena/browser/view/ERR123")
        self.assertEqual(
            record.cells,
            (
                Cell("Severe acute respiratory syndrome coronavirus 2"),
                Cell("2697049", "https://www.ebi.ac.uk/ena/browser/view/Taxon:2697049"),
                Cell("2021-03-01"),
                Cell("Sweden: Uppsala"),
                Cell("ILLUMINA"),
                Cell("AMPLICON"),
                Cell("2021-04-01"),
            ),
        )

    def test_every_record_type_has_a_taxon_id_column(self):
        """Test the taxon id is shown for every record type."""
        for record_type in RECORD_TYPES.values():
            with self.subTest(record_type=record_type.result):
                self.assertIn("tax_id", record_type.fields)

    def test_non_numeric_taxon_id_is_not_linked(self):
        """Test an unexpected taxon id value is shown as plain text, without a link."""
        record = EnaRecord.from_ena_result({"run_accession": "ERR1", "tax_id": "n/a"}, READ_RUN)
        self.assertEqual(record.cells[1], Cell("n/a"))

    def test_missing_and_null_fields_are_blank(self):
        """Test missing or null fields become empty, unlinked cells."""
        record = EnaRecord.from_ena_result({"run_accession": "ERR1", "country": None}, READ_RUN)
        self.assertEqual(record.cells, (Cell(""),) * len(READ_RUN.columns))

    def test_missing_accession_returns_none(self):
        """Test a result without an accession is skipped."""
        self.assertIsNone(EnaRecord.from_ena_result({"run_accession": " "}, READ_RUN))


class TestFilterRecords(SimpleTestCase):
    """Tests for filter_records."""

    def setUp(self):
        """Build a few read_run records to filter."""
        self.records = [
            EnaRecord.from_ena_result(result, READ_RUN)
            for result in (
                {"run_accession": "ERR1", "instrument_platform": "ILLUMINA", "country": "Sweden"},
                {"run_accession": "ERR2", "instrument_platform": "OXFORD_NANOPORE"},
                {
                    "run_accession": "SRR3",
                    "instrument_platform": "ILLUMINA",
                    "country": "Sweden: Lund",
                },
            )
        ]

    def accessions(self, filters: dict[str, str]) -> list[str]:
        """Return the accessions of the records matching ``filters``."""
        return [r.accession for r in filter_records(self.records, READ_RUN, filters)]

    def test_substring_match_is_case_insensitive(self):
        """Test a column matches when it contains the filter text, ignoring case."""
        self.assertEqual(self.accessions({"instrument_platform": "illum"}), ["ERR1", "SRR3"])

    def test_accession_column_can_be_filtered(self):
        """Test the accession column is filtered by its ENA field name."""
        self.assertEqual(self.accessions({"run_accession": "err"}), ["ERR1", "ERR2"])

    def test_filters_are_combined_with_and(self):
        """Test every filter must match."""
        self.assertEqual(
            self.accessions({"instrument_platform": "ILLUMINA", "country": "lund"}), ["SRR3"]
        )

    def test_blank_and_unknown_filters_are_ignored(self):
        """Test blank values and fields that aren't columns don't filter anything out."""
        self.assertEqual(
            self.accessions({"country": "  ", "not_a_column": "x"}), ["ERR1", "ERR2", "SRR3"]
        )


class TestSortRecords(SimpleTestCase):
    """Tests for sort_records."""

    def records(self, *results: dict) -> list[EnaRecord]:
        """Build read_run records from raw results."""
        return [EnaRecord.from_ena_result(result, READ_RUN) for result in results]

    def test_numbers_sort_by_value(self):
        """Test taxon ids sort numerically, not as text (9 before 10)."""
        records = self.records(
            {"run_accession": "A", "tax_id": "10"}, {"run_accession": "B", "tax_id": "9"}
        )
        sorted_records = sort_records(records, READ_RUN, "tax_id")
        self.assertEqual([r.accession for r in sorted_records], ["B", "A"])

    def test_text_sorts_case_insensitively(self):
        """Test text values sort ignoring case."""
        records = self.records(
            {"run_accession": "A", "instrument_platform": "oxford_nanopore"},
            {"run_accession": "B", "instrument_platform": "ILLUMINA"},
        )
        sorted_records = sort_records(records, READ_RUN, "instrument_platform", descending=True)
        self.assertEqual([r.accession for r in sorted_records], ["A", "B"])

    def test_unknown_field_keeps_order(self):
        """Test a field that isn't a column leaves the records unchanged."""
        records = self.records({"run_accession": "B"}, {"run_accession": "A"})
        self.assertEqual(sort_records(records, READ_RUN, "host"), records)


class TestFetchCount(SimpleTestCase):
    """Tests for fetch_count."""

    def setUp(self):
        """Clear the cache so results don't leak between tests."""
        cache.clear()

    @patch("portal_data.ena.fetch_text")
    def test_returns_and_caches_count(self, mock_fetch: MagicMock):
        """Test the count is returned, requested with the right params and then cached."""
        mock_fetch.return_value = "count\n42\n"
        self.assertEqual(fetch_count(READ_RUN, QUERY), 42)
        self.assertEqual(fetch_count(READ_RUN, QUERY), 42)
        mock_fetch.assert_called_once_with(
            url=f"{ENA_PORTAL_API_URL}/count", params={"result": "read_run", "query": QUERY}
        )

    @patch("portal_data.ena.fetch_text")
    def test_zero_is_cached(self, mock_fetch: MagicMock):
        """Test a count of zero is a valid, cacheable result."""
        mock_fetch.return_value = "count\n0\n"
        self.assertEqual(fetch_count(READ_RUN, QUERY), 0)
        self.assertEqual(fetch_count(READ_RUN, QUERY), 0)
        mock_fetch.assert_called_once()

    @patch("portal_data.ena.fetch_text")
    def test_failed_fetch_returns_none_and_is_not_cached(self, mock_fetch: MagicMock):
        """Test a failed fetch returns None and is retried on the next call."""
        mock_fetch.return_value = None
        self.assertIsNone(fetch_count(READ_RUN, QUERY))
        self.assertIsNone(fetch_count(READ_RUN, QUERY))
        self.assertEqual(mock_fetch.call_count, 2)

    @patch("portal_data.ena.fetch_text")
    def test_invalid_body_returns_none(self, mock_fetch: MagicMock):
        """Test an unparseable body is logged and returns None."""
        mock_fetch.return_value = "<html>error</html>"
        with self.assertLogs("portal_data.ena", level="ERROR"):
            self.assertIsNone(fetch_count(READ_RUN, QUERY))


class TestFetchRecords(SimpleTestCase):
    """Tests for fetch_records."""

    def setUp(self):
        """Clear the cache so results don't leak between tests."""
        cache.clear()

    @patch("portal_data.ena.fetch_json")
    def test_returns_parsed_records(self, mock_fetch: MagicMock):
        """Test results are parsed, skipping invalid entries, with the right params sent."""
        mock_fetch.return_value = [
            {"run_accession": "ERR1", "scientific_name": "Virus"},
            {"scientific_name": "No accession"},
            "not a dict",
            {"run_accession": "ERR2"},
        ]
        records = fetch_records(READ_RUN, QUERY)
        self.assertEqual([r.accession for r in records], ["ERR1", "ERR2"])

        params = mock_fetch.call_args.kwargs["params"]
        self.assertEqual(mock_fetch.call_args.kwargs["url"], f"{ENA_PORTAL_API_URL}/search")
        self.assertEqual(params["result"], "read_run")
        self.assertEqual(params["query"], QUERY)
        self.assertEqual(params["fields"], ",".join(READ_RUN.fields))
        self.assertEqual(params["format"], "json")
        self.assertEqual(params["limit"], MAX_BROWSABLE_RECORDS)

    @patch("portal_data.ena.fetch_json")
    def test_offset_is_never_sent(self, mock_fetch: MagicMock):
        """Test no offset is sent, as ENA rejects it with "Unsupported param offset"."""
        mock_fetch.return_value = []
        fetch_records(READ_RUN, QUERY, limit=10)
        self.assertNotIn("offset", mock_fetch.call_args.kwargs["params"])

    @patch("portal_data.ena.fetch_json")
    def test_records_are_cached(self, mock_fetch: MagicMock):
        """Test repeat calls are served from the cache, with each limit cached separately."""
        mock_fetch.return_value = [{"run_accession": "ERR1"}]
        fetch_records(READ_RUN, QUERY)
        fetch_records(READ_RUN, QUERY)
        fetch_records(READ_RUN, QUERY, limit=10)
        self.assertEqual(mock_fetch.call_count, 2)

    @patch("portal_data.ena.fetch_json")
    def test_failed_or_invalid_fetch_returns_none(self, mock_fetch: MagicMock):
        """Test a failed fetch or a non-list body returns None."""
        mock_fetch.return_value = None
        self.assertIsNone(fetch_records(READ_RUN, QUERY))
        mock_fetch.return_value = {"message": "error"}
        with self.assertLogs("portal_data.ena", level="ERROR"):
            self.assertIsNone(fetch_records(READ_RUN, QUERY))


class TestBuildDownloadUrl(SimpleTestCase):
    """Tests for build_download_url."""

    def test_url_requests_all_records_as_tsv(self):
        """Test the link asks ENA for every matching record as a TSV download."""
        url = build_download_url(READ_RUN, QUERY)
        parts = urlsplit(url)
        self.assertEqual(
            f"{parts.scheme}://{parts.netloc}{parts.path}", f"{ENA_PORTAL_API_URL}/search"
        )
        params = parse_qs(parts.query)
        self.assertEqual(params["query"], [QUERY])
        self.assertEqual(params["result"], ["read_run"])
        self.assertEqual(params["format"], ["tsv"])
        self.assertEqual(params["limit"], ["0"])
        self.assertEqual(params["fields"], [",".join(READ_RUN.fields)])
