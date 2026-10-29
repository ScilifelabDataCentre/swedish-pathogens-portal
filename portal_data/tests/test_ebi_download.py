"""Tests for the Genomic data downloads (accession lists, metadata TSV and ENA data files)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
from django.test import SimpleTestCase

from portal_data.ebi_download import (
    ENA_BROWSER_API_URL,
    FASTA,
    TSV,
    XML,
    DownloadError,
    data_formats,
    get_format,
    iter_accessions,
    iter_ena_data,
    iter_tsv,
    parse_accessions,
)
from portal_data.ebi_search import BASE_QUERY, DATA_TYPES, EBI_SEARCH_URL

RAW_READS = DATA_TYPES["raw-reads"]
SEQUENCES = DATA_TYPES["sequences"]


def response(status: int = 200, text: str = "", content: bytes | None = None) -> httpx.Response:
    """Build an httpx response for the mocked client."""
    request = httpx.Request("GET", "https://example.test")
    if content is None:
        content = text.encode()
    return httpx.Response(status, content=content, request=request)


class TestFormats(SimpleTestCase):
    """Tests for the download options offered per data type."""

    def test_sequences_offer_embl_and_fasta_others_xml(self):
        """Test the data formats match the central Pathogens Portal's."""
        self.assertEqual([f.key for f in data_formats(SEQUENCES)], ["embl", "fasta"])
        for key in ("analyses", "raw-reads", "samples", "assemblies"):
            with self.subTest(data_type=key):
                self.assertEqual([f.key for f in data_formats(DATA_TYPES[key])], ["xml"])

    def test_get_format(self):
        """Test only formats offered for the data type are accepted."""
        self.assertEqual(get_format(SEQUENCES, "fasta"), FASTA)
        self.assertEqual(get_format(RAW_READS, "tsv"), TSV)
        self.assertIsNone(get_format(RAW_READS, "fasta"))
        self.assertIsNone(get_format(RAW_READS, "nonsense"))


class TestParseAccessions(SimpleTestCase):
    """Tests for parse_accessions."""

    def test_valid_accessions_are_kept_in_order_without_duplicates(self):
        """Test commas and whitespace separate accessions, and duplicates are dropped."""
        self.assertEqual(
            parse_accessions(" ERX1,GCA_001835525.1\nERX1  SAMEA2 "),
            ["ERX1", "GCA_001835525.1", "SAMEA2"],
        )

    def test_invalid_accessions_are_dropped(self):
        """Test anything that could alter a query is rejected."""
        self.assertEqual(parse_accessions("ERX1,a OR b,x:y,(z),ERX2,1ABC"), ["ERX1", "ERX2"])
        self.assertEqual(parse_accessions("E" + "1" * 40), [])
        self.assertEqual(parse_accessions(""), [])


@patch("portal_data.ebi_download.CLIENT")
class TestIterAccessions(SimpleTestCase):
    """Tests for iter_accessions."""

    @patch("portal_data.ebi_download.ACCESSION_PAGE_SIZE", 2)
    def test_pages_until_a_short_page(self, mock_client: MagicMock):
        """Test pages are requested until one comes back short, with the search and facets."""
        mock_client.get.side_effect = [
            response(text="ERX1\nERX2\n"),
            response(text="ERX3\n"),
        ]
        accessions = list(
            iter_accessions(
                RAW_READS, text="coli", selected_facets={"classification": ["bacteria"]}
            )
        )
        self.assertEqual(accessions, ["ERX1", "ERX2", "ERX3"])
        first, second = (c.kwargs["params"] for c in mock_client.get.call_args_list)
        self.assertEqual(mock_client.get.call_args.args[0], f"{EBI_SEARCH_URL}/sra-experiment")
        self.assertEqual(first["query"], f"{BASE_QUERY} AND (coli*)")
        self.assertEqual(first["facets"], "classification:bacteria")
        self.assertEqual((first["format"], first["size"], first["start"]), ("idlist", 2, 0))
        self.assertEqual(second["start"], 2)

    def test_failure_raises_download_error(self, mock_client: MagicMock):
        """Test EBI Search being unreachable raises DownloadError."""
        mock_client.get.side_effect = httpx.ConnectError("down")
        with (
            self.assertLogs("portal_data.ebi_download", level="ERROR"),
            self.assertRaises(DownloadError),
        ):
            list(iter_accessions(RAW_READS))


@patch("portal_data.ebi_download.CLIENT")
class TestIterTsv(SimpleTestCase):
    """Tests for iter_tsv."""

    EBI_TSV = (
        '"acc"\t"scientific_name"\t"TAXON"\t"collection_date"\t"host"\t'
        '"instrument_platform"\t"library_strategy"\t"first_public_date"\n'
        '"ERX1"\t"Escherichia coli"\t"562"\t"20240102"\t"Homo sapiens"\t"ILLUMINA"\t"WGS"\t""\n'
    )

    def test_all_results(self, mock_client: MagicMock):
        """Test the header uses column labels and rows are formatted like the table."""
        mock_client.get.return_value = response(text=self.EBI_TSV)
        lines = list(iter_tsv(RAW_READS, text="coli"))
        self.assertEqual(
            lines,
            [
                "Accession\tOrganism\tTaxon ID\tCollection date\tHost\tPlatform\t"
                "Library strategy\tFirst public\n",
                "ERX1\tEscherichia coli\t562\t2024-01-02\tHomo sapiens\tILLUMINA\tWGS\t\n",
            ],
        )
        params = mock_client.get.call_args.kwargs["params"]
        self.assertEqual(params["format"], "tsv")
        self.assertEqual(params["query"], f"{BASE_QUERY} AND (coli*)")
        self.assertEqual(params["fields"].split(",")[0], "acc")

    @patch("portal_data.ebi_download.TSV_PAGE_SIZE", 1)
    def test_all_results_are_paged(self, mock_client: MagicMock):
        """Test pages are requested until one comes back short."""
        header = self.EBI_TSV.splitlines()[0] + "\n"
        mock_client.get.side_effect = [response(text=self.EBI_TSV), response(text=header)]
        lines = list(iter_tsv(RAW_READS))
        self.assertEqual(len(lines), 2)
        self.assertEqual(mock_client.get.call_args_list[1].kwargs["params"]["start"], 1)

    @patch("portal_data.ebi_download.SELECTED_BATCH_SIZE", 2)
    def test_selected_accessions_are_looked_up_in_batches(self, mock_client: MagicMock):
        """Test selected records are queried by accession, a batch at a time."""
        mock_client.get.return_value = response(text=self.EBI_TSV)
        list(iter_tsv(RAW_READS, accessions=["ERX1", "ERX2", "ERX3"]))
        queries = [c.kwargs["params"]["query"] for c in mock_client.get.call_args_list]
        self.assertEqual(
            queries,
            [f"{BASE_QUERY} AND acc:(ERX1 OR ERX2)", f"{BASE_QUERY} AND acc:(ERX3)"],
        )

    def test_values_needing_quotes_are_quoted(self, mock_client: MagicMock):
        """Test a value containing a tab is quoted, so the TSV stays aligned."""
        mock_client.get.return_value = response(text='"acc"\t"scientific_name"\n"ERX1"\t"a\tb"\n')
        lines = list(iter_tsv(RAW_READS))
        self.assertTrue(lines[1].startswith('ERX1\t"a\tb"\t'))


@patch("portal_data.ebi_download.CLIENT")
class TestIterEnaData(SimpleTestCase):
    """Tests for iter_ena_data."""

    @patch("portal_data.ebi_download.ENA_BATCH_SIZE", 2)
    def test_fasta_batches_are_concatenated(self, mock_client: MagicMock):
        """Test accessions are posted as JSON in batches and the files concatenated."""
        mock_client.post.side_effect = [
            response(content=b">A\nAC\n>B\nGT\n"),
            response(content=b">C\nTT\n"),
        ]
        data = b"".join(iter_ena_data(FASTA, iter(["A", "B", "C"])))
        self.assertEqual(data, b">A\nAC\n>B\nGT\n>C\nTT\n")
        first = mock_client.post.call_args_list[0]
        self.assertEqual(first.args[0], f"{ENA_BROWSER_API_URL}/fasta")
        self.assertEqual(
            first.kwargs["json"], {"accessions": "A,B", "download": False, "gzip": False}
        )

    @patch("portal_data.ebi_download.ENA_BATCH_SIZE", 1)
    def test_xml_batches_are_merged_under_one_root(self, mock_client: MagicMock):
        """Test each batch's root element is merged, so the file is one valid XML document."""
        declaration = '<?xml version="1.0" encoding="UTF-8"?>\n'
        mock_client.post.side_effect = [
            response(
                text=f'{declaration}<EXPERIMENT_SET>\n<EXPERIMENT accession="A"/>\n'
                "</EXPERIMENT_SET>\n"
            ),
            response(text='<EXPERIMENT_SET>\n<EXPERIMENT accession="B"/>\n</EXPERIMENT_SET>'),
        ]
        data = b"".join(iter_ena_data(XML, ["A", "B"])).decode()
        self.assertEqual(
            data,
            f"{declaration}<EXPERIMENT_SET>\n"
            '<EXPERIMENT accession="A"/>\n<EXPERIMENT accession="B"/>\n</EXPERIMENT_SET>\n',
        )

    def test_no_accessions_gives_an_empty_file(self, mock_client: MagicMock):
        """Test nothing is requested or written when there are no accessions."""
        self.assertEqual(b"".join(iter_ena_data(XML, [])), b"")
        mock_client.post.assert_not_called()

    @patch("portal_data.ebi_download.ENA_BATCH_SIZE", 4)
    def test_rejected_batch_is_split_and_bad_accessions_skipped(self, mock_client: MagicMock):
        """Test a batch ENA rejects is split in half until only the bad accession is left out."""

        def post(url: str, json: dict, timeout: float) -> httpx.Response:
            accessions = json["accessions"].split(",")
            if "BAD" in accessions:
                return response(400, text="Unknown accession format")
            return response(content="".join(f">{a}\n" for a in accessions).encode())

        mock_client.post.side_effect = post
        with self.assertLogs("portal_data.ebi_download", level="WARNING"):
            data = b"".join(iter_ena_data(FASTA, ["A", "BAD", "C", "D"]))
        self.assertEqual(data, b">A\n>C\n>D\n")

    def test_server_errors_are_retried_once_then_raise(self, mock_client: MagicMock):
        """Test ENA server errors are retried once before DownloadError."""
        mock_client.post.return_value = response(503, text="busy")
        with (
            self.assertLogs("portal_data.ebi_download", level="ERROR"),
            self.assertRaises(DownloadError),
        ):
            list(iter_ena_data(FASTA, ["A"]))
        self.assertEqual(mock_client.post.call_count, 2)

    def test_retry_recovers_from_a_single_failure(self, mock_client: MagicMock):
        """Test one network failure followed by success still downloads."""
        mock_client.post.side_effect = [httpx.ReadTimeout("slow"), response(content=b">A\n")]
        self.assertEqual(b"".join(iter_ena_data(FASTA, ["A"])), b">A\n")
