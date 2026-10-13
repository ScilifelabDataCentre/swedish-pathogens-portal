"""Tests for the GenomicDataPage model and its ENA listing service."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import RequestFactory
from wagtail.models import Page, Site
from wagtail.test.utils import WagtailPageTestCase

from cms.pages import GenomicDataPage, HomePage
from cms.services.genomic_data import (
    PAGE_SIZE,
    EnaPathogen,
    build_context_dict,
    resolve_active_pathogen,
    resolve_record_type,
)


def fake_ena(counts: dict[str, int | None], records: list[dict] | None = None) -> MagicMock:
    """Build a fake fetch_text/fetch_json answering ENA count and search requests.

    ``counts`` maps an ENA result type to the count returned for it, as the count
    endpoint's plain-text body (None meaning a failed fetch). Search requests
    return ``records`` (or a page of generated read_run records if not given).
    """

    def side_effect(url: str, params: dict) -> object:
        if url.endswith("/count"):
            count = counts.get(params["result"])
            return None if count is None else f"count\n{count}\n"
        if records is not None:
            return records
        start = params["offset"]
        return [{"run_accession": f"ERR{n}"} for n in range(start, start + params["limit"])]

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

    def get_htmx(self, **params: str):
        """GET the page as an HTMX request with the given query parameters."""
        return self.client.get(self.page.url, params, HTTP_HX_REQUEST="true")

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
        self.assertContains(response, '<th scope="col">Host</th>', html=False)
        self.assertEqual(mock_fetch.call_args_list[-1].kwargs["params"]["result"], "sample")

    @patch_ena
    def test_pagination_requests_the_right_offset(self, mock_fetch: MagicMock):
        """Test page 3 asks ENA for the third page and renders pagination links."""
        mock_fetch.side_effect = fake_ena(
            counts={"read_run": PAGE_SIZE * 10, "sample": 0, "sequence": 0}
        ).side_effect
        response = self.get_htmx(pathogen="SARS-CoV-2", page="3")
        self.assertEqual(mock_fetch.call_args_list[-1].kwargs["params"]["offset"], PAGE_SIZE * 2)
        self.assertContains(response, f"ERR{PAGE_SIZE * 2}")
        self.assertContains(response, 'aria-label="Pagination"')
        self.assertContains(response, "?pathogen=SARS-CoV-2&amp;type=read_run&amp;page=4")
        # the first page's link has no page parameter
        self.assertContains(response, 'href="/genomic-data/?pathogen=SARS-CoV-2&amp;type=read_run"')

    @patch_ena
    def test_page_beyond_last_shows_last_page(self, mock_fetch: MagicMock):
        """Test an out-of-range page number falls back to the last page."""
        mock_fetch.side_effect = fake_ena(
            counts={"read_run": 30, "sample": 0, "sequence": 0}
        ).side_effect
        self.get_htmx(pathogen="SARS-CoV-2", page="999")
        self.assertEqual(mock_fetch.call_args_list[-1].kwargs["params"]["offset"], PAGE_SIZE)

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
