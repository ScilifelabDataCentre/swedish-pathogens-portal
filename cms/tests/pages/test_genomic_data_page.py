"""Tests for the GenomicDataPage model and its ENA listing service."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.http import HttpResponse
from django.test import RequestFactory
from wagtail.models import Page, Site
from wagtail.test.utils import WagtailPageTestCase

from cms.pages import GenomicDataPage, HomePage
from cms.services.genomic_data import (
    MAX_FILTER_LENGTH,
    PAGE_SIZE,
    EnaPathogen,
    Sort,
    build_context_dict,
    resolve_active_pathogen,
    resolve_filters,
    resolve_record_type,
    resolve_sort,
)
from portal_data.ena import fetch_records


def fake_ena(counts: dict[str, int | None], records: list[dict] | None = None) -> MagicMock:
    """Build a fake fetch_text/fetch_json answering ENA count and search requests.

    ``counts`` maps an ENA result type to the count returned for it, as the count
    endpoint's plain-text body (None meaning a failed fetch). Search requests
    return ``records``, or if not given one generated read_run record per count
    (up to the request's limit), numbered from ERR0.
    """

    def side_effect(url: str, params: dict) -> object:
        if url.endswith("/count"):
            count = counts.get(params["result"])
            return None if count is None else f"count\n{count}\n"
        if records is not None:
            return records
        total = min(counts.get(params["result"]) or 0, params["limit"])
        return [{"run_accession": f"ERR{n}"} for n in range(total)]

    return MagicMock(side_effect=side_effect)


def patch_ena(test: Callable) -> Callable:
    """Patch ENA's fetch_json (search) and fetch_text (count) with one shared mock.

    The mock is passed to the test, like ``@patch`` does.
    """

    @wraps(test)
    def wrapper(self: WagtailPageTestCase) -> None:
        mock = MagicMock()
        with patch("portal_data.ena.fetch_json", mock), patch("portal_data.ena.fetch_text", mock):
            test(self, mock)

    return wrapper


class TestGenomicDataPage(WagtailPageTestCase):
    """Tests for the GenomicDataPage model and listing."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Create a home and a genomic data page."""
        cls.factory = RequestFactory()

        root = Page.get_first_root_node()
        for child in root.get_children():
            child.delete()
        root = Page.get_first_root_node()
        cls.home = HomePage(title="Home", slug="home")
        root.add_child(instance=cls.home)
        Site.objects.update_or_create(
            is_default_site=True, defaults={"hostname": "testserver", "root_page": cls.home}
        )

        cls.page = GenomicDataPage(
            title="Genomic data",
            slug="genomic-data",
            content=[
                ("text", "<p>Some descriptive text.</p>"),
                (
                    "ena_data",
                    {
                        "pathogens": [
                            {"name": "SARS-CoV-2", "taxon_ids": [2697049]},
                            {"name": "Influenza", "taxon_ids": [11320, 11520]},
                        ]
                    },
                ),
            ],
        )
        cls.home.add_child(instance=cls.page)
        cls.page.save_revision().publish()

    def setUp(self):
        """Clear the cache so ENA results don't leak between tests."""
        cache.clear()

    def get_htmx(self, target: str = "ena-listing", **params: str):
        """GET the page as an HTMX request for ``target`` with the given query parameters."""
        return self.client.get(self.page.url, params, HTTP_HX_REQUEST="true", HTTP_HX_TARGET=target)

    # --- Page model ---------------------------------------------------------------

    def test_can_be_created_under_home_page_only(self):
        """Test the page can only live under the home page."""
        self.assertAllowedParentPageTypes(GenomicDataPage, {HomePage})
        self.assertAllowedSubpageTypes(GenomicDataPage, set())

    def test_pathogens_are_sorted_by_name(self):
        """Test the pathogens are read from the ENA data block and sorted by name."""
        self.assertEqual(
            self.page.pathogens,
            [
                EnaPathogen(name="Influenza", taxon_ids=(11320, 11520)),
                EnaPathogen(name="SARS-CoV-2", taxon_ids=(2697049,)),
            ],
        )

    @patch_ena
    def test_full_page_load_does_not_call_ena(self, mock_fetch: MagicMock):
        """Test the full page renders the lazy-load container without fetching from ENA."""
        response = self.client.get(self.page.url, {"pathogen": "Influenza"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Some descriptive text.")
        self.assertContains(response, 'id="ena-listing"')
        self.assertContains(response, 'hx-get="/genomic-data/?pathogen=Influenza"')
        mock_fetch.assert_not_called()

    @patch_ena
    def test_htmx_history_restore_gets_full_page(self, mock_fetch: MagicMock):
        """Test an HTMX history restore request gets the full page, not the partial."""
        response = self.client.get(
            self.page.url, HTTP_HX_REQUEST="true", HTTP_HX_HISTORY_RESTORE_REQUEST="true"
        )
        self.assertContains(response, "Some descriptive text.")
        mock_fetch.assert_not_called()

    # --- HTMX listing -------------------------------------------------------------

    @patch_ena
    def test_htmx_load_renders_records_for_first_pathogen(self, mock_fetch: MagicMock):
        """Test the default listing shows raw reads for the first pathogen alphabetically."""
        mock_fetch.side_effect = fake_ena(
            counts={"read_run": 2, "sample": 1, "sequence": 0},
            records=[
                {"run_accession": "ERR111", "scientific_name": "Influenza A virus"},
                {"run_accession": "ERR222", "country": "Sweden: Lund"},
            ],
        ).side_effect
        response = self.get_htmx()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Influenza data from Sweden")
        self.assertContains(response, "https://www.ebi.ac.uk/ena/browser/view/ERR111")
        self.assertContains(response, "Influenza A virus")
        self.assertContains(response, "Sweden: Lund")
        self.assertContains(response, "Showing 1 to 2 of 2 raw reads")
        self.assertContains(response, "Download all as TSV from ENA")
        self.assertNotContains(response, 'aria-label="Pagination"')
        # the Influenza query ORs both taxa
        search_query = mock_fetch.call_args_list[-1].kwargs["params"]["query"]
        self.assertEqual(search_query, '(tax_tree(11320) OR tax_tree(11520)) AND country="Sweden*"')

    @patch_ena
    def test_record_type_tabs_show_counts(self, mock_fetch: MagicMock):
        """Test each record type tab shows its count with thousands separators."""
        mock_fetch.side_effect = fake_ena(
            counts={"read_run": 123456, "sample": 7, "sequence": None}
        ).side_effect
        response = self.get_htmx(pathogen="SARS-CoV-2")
        self.assertContains(response, "123,456")
        self.assertContains(response, '<span class="badge badge-sm">7</span>')
        # a failed count shows "?" on its tab
        self.assertContains(response, '<span class="badge badge-sm">?</span>')

    @patch_ena
    def test_selected_record_type_is_listed(self, mock_fetch: MagicMock):
        """Test the ``type`` parameter selects which ENA result is listed."""
        mock_fetch.side_effect = fake_ena(
            counts={"read_run": 5, "sample": 1, "sequence": 0},
            records=[{"sample_accession": "SAMEA1", "host": "Homo sapiens"}],
        ).side_effect
        response = self.get_htmx(pathogen="SARS-CoV-2", type="sample")
        self.assertContains(response, "SAMEA1")
        self.assertContains(response, "Homo sapiens")
        self.assertContains(response, "sort=host&amp;order=asc")
        self.assertEqual(mock_fetch.call_args_list[-1].kwargs["params"]["result"], "sample")

    @patch_ena
    def test_pagination_shows_the_requested_page(self, mock_fetch: MagicMock):
        """Test page 3 shows the third slice of records and renders pagination links."""
        mock_fetch.side_effect = fake_ena(
            counts={"read_run": PAGE_SIZE * 10, "sample": 0, "sequence": 0}
        ).side_effect
        response = self.get_htmx(pathogen="SARS-CoV-2", page="3")
        self.assertContains(response, f'/view/ERR{PAGE_SIZE * 2}"')
        self.assertNotContains(response, f'/view/ERR{PAGE_SIZE * 2 - 1}"')
        self.assertNotContains(response, f'/view/ERR{PAGE_SIZE * 3}"')
        self.assertContains(response, f"Showing {PAGE_SIZE * 2 + 1} to {PAGE_SIZE * 3} of")
        self.assertContains(response, 'aria-label="Pagination"')
        self.assertContains(response, "?pathogen=SARS-CoV-2&amp;type=read_run&amp;page=4")
        # the first page's link has no page parameter
        self.assertContains(response, 'href="/genomic-data/?pathogen=SARS-CoV-2&amp;type=read_run"')

    @patch_ena
    def test_paging_reuses_one_cached_search(self, mock_fetch: MagicMock):
        """Test moving between pages doesn't send another search request to ENA."""
        mock_fetch.side_effect = fake_ena(
            counts={"read_run": PAGE_SIZE * 3, "sample": 0, "sequence": 0}
        ).side_effect
        for page in ("1", "2", "3"):
            self.get_htmx(pathogen="SARS-CoV-2", page=page)
        searches = [c for c in mock_fetch.call_args_list if c.kwargs["url"].endswith("/search")]
        self.assertEqual(len(searches), 1)
        self.assertNotIn("offset", searches[0].kwargs["params"])

    @patch_ena
    def test_page_beyond_last_shows_last_page(self, mock_fetch: MagicMock):
        """Test an out-of-range page number falls back to the last page."""
        mock_fetch.side_effect = fake_ena(
            counts={"read_run": 30, "sample": 0, "sequence": 0}
        ).side_effect
        response = self.get_htmx(pathogen="SARS-CoV-2", page="999")
        self.assertContains(response, "Showing 26 to 30 of 30")

    @patch_ena
    def test_more_records_than_browsable_shows_note(self, mock_fetch: MagicMock):
        """Test a count above the browsable cap pages only the cap and points to the download."""
        mock_fetch.side_effect = fake_ena(
            counts={"read_run": 60, "sample": 0, "sequence": 0}
        ).side_effect
        # cap the browsable records at 50 rather than MAX_BROWSABLE_RECORDS
        with patch(
            "cms.services.genomic_data.fetch_records",
            side_effect=lambda record_type, query: fetch_records(record_type, query, limit=50),
        ):
            response = self.get_htmx(pathogen="SARS-CoV-2", page="99")
        self.assertContains(response, "Only the first 50 raw reads can be browsed here")
        self.assertContains(response, "Showing 26 to 50 of 60")

    @patch_ena
    def test_no_records(self, mock_fetch: MagicMock):
        """Test a zero count shows a message and skips the search request."""
        mock_fetch.side_effect = fake_ena(
            counts={"read_run": 0, "sample": 0, "sequence": 0}
        ).side_effect
        response = self.get_htmx(pathogen="SARS-CoV-2")
        self.assertContains(response, "No raw reads from Sweden were found")
        self.assertTrue(all(c.kwargs["url"].endswith("/count") for c in mock_fetch.call_args_list))

    @patch_ena
    def test_failed_count_shows_error(self, mock_fetch: MagicMock):
        """Test ENA being unreachable shows an error message."""
        mock_fetch.return_value = None
        response = self.get_htmx(pathogen="SARS-CoV-2")
        self.assertContains(response, "could not be loaded from")

    @patch_ena
    def test_failed_search_shows_error(self, mock_fetch: MagicMock):
        """Test a failed records request after a successful count shows an error message."""

        def side_effect(url: str, params: dict) -> object:
            return "count\n10\n" if url.endswith("/count") else None

        mock_fetch.side_effect = side_effect
        response = self.get_htmx(pathogen="SARS-CoV-2")
        self.assertContains(response, "could not be loaded from")

    @patch_ena
    def test_unknown_pathogen_shows_message(self, mock_fetch: MagicMock):
        """Test an unconfigured pathogen shows the "isn't recognised" message without fetching."""
        with self.assertLogs("cms.services.genomic_data", level="WARNING"):
            response = self.get_htmx(pathogen="Nonexistent")
        self.assertContains(response, "isn't recognised")
        mock_fetch.assert_not_called()

    # --- Taxon id column and filters -----------------------------------------------

    FILTER_RECORDS = [
        {"run_accession": "ERR1", "tax_id": "2697049", "instrument_platform": "ILLUMINA"},
        {"run_accession": "ERR2", "tax_id": "2697049", "instrument_platform": "OXFORD_NANOPORE"},
        {"run_accession": "ERR3", "tax_id": "2697049", "instrument_platform": "ILLUMINA"},
    ]

    @patch_ena
    def test_taxon_id_column_links_to_ena_taxon_page(self, mock_fetch: MagicMock):
        """Test each row shows its taxon id, linking to the taxon's ENA browser page."""
        mock_fetch.side_effect = fake_ena(
            counts={"read_run": 3, "sample": 0, "sequence": 0}, records=self.FILTER_RECORDS
        ).side_effect
        response = self.get_htmx(pathogen="SARS-CoV-2")
        self.assertContains(response, "sort=tax_id&amp;order=asc")
        self.assertContains(
            response, 'href="https://www.ebi.ac.uk/ena/browser/view/Taxon:2697049"', count=3
        )

    @patch_ena
    def test_listing_renders_a_labelled_filter_per_column(self, mock_fetch: MagicMock):
        """Test the filter form has a labelled input for the accession and every column."""
        mock_fetch.side_effect = fake_ena(
            counts={"read_run": 3, "sample": 0, "sequence": 0}, records=self.FILTER_RECORDS
        ).side_effect
        response = self.get_htmx(pathogen="SARS-CoV-2")
        self.assertContains(response, 'id="ena-filters"')
        self.assertContains(response, 'id="ena-results"')
        for field in ("run_accession", "tax_id", "instrument_platform", "first_public"):
            self.assertContains(response, f'<label for="ena-filter-{field}"')
            self.assertContains(response, f'name="{field}"')

    @patch_ena
    def test_filtering_returns_only_the_matching_results(self, mock_fetch: MagicMock):
        """Test a filter request for #ena-results returns just the filtered results partial."""
        mock_fetch.side_effect = fake_ena(
            counts={"read_run": 3, "sample": 0, "sequence": 0}, records=self.FILTER_RECORDS
        ).side_effect
        response = self.get_htmx(
            target="ena-results", pathogen="SARS-CoV-2", instrument_platform="illumina"
        )
        self.assertContains(response, '/view/ERR1"')
        self.assertContains(response, '/view/ERR3"')
        self.assertNotContains(response, '/view/ERR2"')
        self.assertContains(response, "of 2 raw reads matching the filters (out of 3)")
        # the filter form and sidebar aren't re-rendered, so typing keeps focus
        self.assertNotContains(response, 'id="ena-filters"')
        self.assertNotContains(response, "Pathogens</h3>")

    @patch_ena
    def test_no_matching_records_shows_message(self, mock_fetch: MagicMock):
        """Test filters that match nothing show a message instead of the table."""
        mock_fetch.side_effect = fake_ena(
            counts={"read_run": 3, "sample": 0, "sequence": 0}, records=self.FILTER_RECORDS
        ).side_effect
        response = self.get_htmx(target="ena-results", pathogen="SARS-CoV-2", run_accession="x")
        self.assertContains(response, "No raw reads match these filters.")
        self.assertNotContains(response, "<table")

    @patch_ena
    def test_pagination_links_keep_the_filters(self, mock_fetch: MagicMock):
        """Test page links carry the active filters, while clearing drops them."""
        mock_fetch.side_effect = fake_ena(
            counts={"read_run": PAGE_SIZE * 3, "sample": 0, "sequence": 0}
        ).side_effect
        response = self.get_htmx(pathogen="SARS-CoV-2", run_accession="ERR")
        self.assertContains(
            response, "?pathogen=SARS-CoV-2&amp;type=read_run&amp;run_accession=ERR&amp;page=2"
        )
        self.assertContains(
            response, 'href="/genomic-data/?pathogen=SARS-CoV-2&amp;type=read_run" hx-get'
        )

    @patch_ena
    def test_filter_form_is_prefilled_and_open_when_filtering(self, mock_fetch: MagicMock):
        """Test a shared filtered URL loads with the filter values filled in and visible."""
        mock_fetch.side_effect = fake_ena(
            counts={"read_run": 3, "sample": 0, "sequence": 0}, records=self.FILTER_RECORDS
        ).side_effect
        response = self.get_htmx(pathogen="SARS-CoV-2", instrument_platform="ILLUMINA")
        self.assertContains(response, 'value="ILLUMINA"')
        self.assertContains(
            response, '<details class="rounded-box border border-pp-pale-grey px-3 py-2" open>'
        )

    def test_resolve_filters(self):
        """Test only the record type's fields are read as filters, blank ones dropped."""
        record_type = resolve_record_type(self.factory.get("/"))
        request = self.factory.get(
            "/",
            {
                "pathogen": "SARS-CoV-2",
                "page": "2",
                "host": "Homo",  # a sample field, not a read_run one
                "country": " ",
                "instrument_platform": " illumina ",
                "run_accession": "E" * (MAX_FILTER_LENGTH + 10),
            },
        )
        self.assertEqual(
            resolve_filters(request, record_type),
            {"instrument_platform": "illumina", "run_accession": "E" * MAX_FILTER_LENGTH},
        )

    # --- Sorting ------------------------------------------------------------------

    SORT_RECORDS = [
        {"run_accession": "ERR10", "collection_date": "2021-03-01"},
        {"run_accession": "ERR2", "collection_date": ""},
        {"run_accession": "ERR1", "collection_date": "2020-12-24"},
    ]

    def row_order(self, response: HttpResponse) -> list[str]:
        """Return the accessions in the order their rows appear in ``response``."""
        content = response.content.decode()
        positions = {acc: content.index(f'/view/{acc}"') for acc in ("ERR1", "ERR2", "ERR10")}
        return sorted(positions, key=positions.get)

    @patch_ena
    def test_sort_ascending_and_descending(self, mock_fetch: MagicMock):
        """Test sorting by accession is natural (ERR2 before ERR10), in both directions."""
        mock_fetch.side_effect = fake_ena(
            counts={"read_run": 3, "sample": 0, "sequence": 0}, records=self.SORT_RECORDS
        ).side_effect
        response = self.get_htmx(pathogen="SARS-CoV-2", sort="run_accession", order="asc")
        self.assertEqual(self.row_order(response), ["ERR1", "ERR2", "ERR10"])
        response = self.get_htmx(pathogen="SARS-CoV-2", sort="run_accession", order="desc")
        self.assertEqual(self.row_order(response), ["ERR10", "ERR2", "ERR1"])

    @patch_ena
    def test_blank_values_sort_last(self, mock_fetch: MagicMock):
        """Test rows with a blank value in the sorted column come last in either direction."""
        mock_fetch.side_effect = fake_ena(
            counts={"read_run": 3, "sample": 0, "sequence": 0}, records=self.SORT_RECORDS
        ).side_effect
        response = self.get_htmx(pathogen="SARS-CoV-2", sort="collection_date", order="asc")
        self.assertEqual(self.row_order(response), ["ERR1", "ERR10", "ERR2"])
        response = self.get_htmx(pathogen="SARS-CoV-2", sort="collection_date", order="desc")
        self.assertEqual(self.row_order(response), ["ERR10", "ERR1", "ERR2"])

    @patch_ena
    def test_sorted_header_has_aria_sort_and_toggles(self, mock_fetch: MagicMock):
        """Test the sorted column is marked for screen readers and its link flips the order."""
        mock_fetch.side_effect = fake_ena(
            counts={"read_run": 3, "sample": 0, "sequence": 0}, records=self.SORT_RECORDS
        ).side_effect
        response = self.get_htmx(pathogen="SARS-CoV-2", sort="run_accession", order="asc")
        self.assertContains(response, 'aria-sort="ascending"', count=1)
        self.assertContains(response, "sort=run_accession&amp;order=desc")
        # other columns start ascending
        self.assertContains(response, "sort=collection_date&amp;order=asc")

    @patch_ena
    def test_sort_is_kept_by_pagination_filters_and_clear(self, mock_fetch: MagicMock):
        """Test page links, the filter form and "Clear filters" all keep the sort."""
        mock_fetch.side_effect = fake_ena(
            counts={"read_run": PAGE_SIZE * 3, "sample": 0, "sequence": 0}
        ).side_effect
        response = self.get_htmx(
            pathogen="SARS-CoV-2", run_accession="ERR", sort="run_accession", order="desc"
        )
        self.assertContains(
            response,
            "type=read_run&amp;run_accession=ERR&amp;sort=run_accession&amp;order=desc&amp;page=2",
        )
        self.assertContains(response, '<input type="hidden" name="sort" value="run_accession">')
        self.assertContains(response, '<input type="hidden" name="order" value="desc">')
        self.assertContains(
            response,
            'href="/genomic-data/?pathogen=SARS-CoV-2&amp;type=read_run'
            '&amp;sort=run_accession&amp;order=desc" hx-get',
        )

    @patch_ena
    def test_sorting_applies_before_paging(self, mock_fetch: MagicMock):
        """Test descending sort puts the last record on the first page."""
        mock_fetch.side_effect = fake_ena(
            counts={"read_run": PAGE_SIZE * 2, "sample": 0, "sequence": 0}
        ).side_effect
        response = self.get_htmx(pathogen="SARS-CoV-2", sort="run_accession", order="desc")
        self.assertContains(response, f'/view/ERR{PAGE_SIZE * 2 - 1}"')
        self.assertNotContains(response, '/view/ERR0"')

    def test_resolve_sort(self):
        """Test the sort field is validated against the record type and order defaults to asc."""
        record_type = resolve_record_type(self.factory.get("/"))
        cases = [
            ({}, None),
            ({"sort": "host"}, None),  # a sample field, not a read_run one
            ({"sort": "tax_id"}, Sort("tax_id", descending=False)),
            ({"sort": "tax_id", "order": "desc"}, Sort("tax_id", descending=True)),
            ({"sort": "tax_id", "order": "sideways"}, Sort("tax_id", descending=False)),
        ]
        for params, expected in cases:
            with self.subTest(params=params):
                request = self.factory.get("/", params)
                self.assertEqual(resolve_sort(request, record_type), expected)

    # --- Service helpers ----------------------------------------------------------

    def test_resolve_active_pathogen(self):
        """Test the default, a named and an unknown pathogen are resolved."""
        request = self.factory.get("/")
        self.assertEqual(resolve_active_pathogen(self.page, request).name, "Influenza")
        request = self.factory.get("/", {"pathogen": "SARS-CoV-2"})
        self.assertEqual(resolve_active_pathogen(self.page, request).name, "SARS-CoV-2")
        request = self.factory.get("/", {"pathogen": "Unknown"})
        with self.assertLogs("cms.services.genomic_data", level="WARNING"):
            self.assertIsNone(resolve_active_pathogen(self.page, request))

    def test_resolve_record_type_falls_back_to_default(self):
        """Test an unknown or missing record type falls back to raw reads."""
        for params in ({}, {"type": "nonsense"}):
            with self.subTest(params=params):
                request = self.factory.get("/", params)
                self.assertEqual(resolve_record_type(request).result, "read_run")

    @patch_ena
    def test_invalid_page_number_defaults_to_first_page(self, mock_fetch: MagicMock):
        """Test a non-numeric page parameter is treated as page 1."""
        mock_fetch.side_effect = fake_ena(
            counts={"read_run": 30, "sample": 0, "sequence": 0}
        ).side_effect
        request = self.factory.get(self.page.url, {"page": "abc"})
        context = build_context_dict(request, self.page)
        self.assertEqual(context["page_obj"].number, 1)
