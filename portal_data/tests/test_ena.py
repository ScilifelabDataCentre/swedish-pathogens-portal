"""Tests for the ENA Portal API client."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

from django.core.cache import cache
from django.test import SimpleTestCase

from portal_data.ena import (
    ENA_PORTAL_API_URL,
    RECORD_TYPES,
    EnaRecord,
    _parse_count,
    build_download_url,
    build_query,
    fetch_count,
    fetch_records,
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
                "Severe acute respiratory syndrome coronavirus 2",
                "2021-03-01",
                "Sweden: Uppsala",
                "ILLUMINA",
                "AMPLICON",
                "2021-04-01",
            ),
        )

    def test_missing_and_null_fields_are_blank(self):
        """Test missing or null fields become empty strings."""
        record = EnaRecord.from_ena_result({"run_accession": "ERR1", "country": None}, READ_RUN)
        self.assertEqual(record.cells, ("",) * len(READ_RUN.columns))

    def test_missing_accession_returns_none(self):
        """Test a result without an accession is skipped."""
        self.assertIsNone(EnaRecord.from_ena_result({"run_accession": " "}, READ_RUN))


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
        """Test results are parsed, skipping invalid entries, with paging params passed on."""
        mock_fetch.return_value = [
            {"run_accession": "ERR1", "scientific_name": "Virus"},
            {"scientific_name": "No accession"},
            "not a dict",
            {"run_accession": "ERR2"},
        ]
        records = fetch_records(READ_RUN, QUERY, offset=50, limit=25)
        self.assertEqual([r.accession for r in records], ["ERR1", "ERR2"])

        params = mock_fetch.call_args.kwargs["params"]
        self.assertEqual(mock_fetch.call_args.kwargs["url"], f"{ENA_PORTAL_API_URL}/search")
        self.assertEqual(params["result"], "read_run")
        self.assertEqual(params["query"], QUERY)
        self.assertEqual(params["fields"], ",".join(READ_RUN.fields))
        self.assertEqual(params["format"], "json")
        self.assertEqual(params["offset"], 50)
        self.assertEqual(params["limit"], 25)

    @patch("portal_data.ena.fetch_json")
    def test_pages_are_cached_separately(self, mock_fetch: MagicMock):
        """Test each page is cached under its own key."""
        mock_fetch.return_value = [{"run_accession": "ERR1"}]
        fetch_records(READ_RUN, QUERY, offset=0, limit=25)
        fetch_records(READ_RUN, QUERY, offset=0, limit=25)
        fetch_records(READ_RUN, QUERY, offset=25, limit=25)
        self.assertEqual(mock_fetch.call_count, 2)

    @patch("portal_data.ena.fetch_json")
    def test_failed_or_invalid_fetch_returns_none(self, mock_fetch: MagicMock):
        """Test a failed fetch or a non-list body returns None."""
        mock_fetch.return_value = None
        self.assertIsNone(fetch_records(READ_RUN, QUERY, offset=0, limit=25))
        mock_fetch.return_value = {"message": "error"}
        with self.assertLogs("portal_data.ena", level="ERROR"):
            self.assertIsNone(fetch_records(READ_RUN, QUERY, offset=0, limit=25))


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
