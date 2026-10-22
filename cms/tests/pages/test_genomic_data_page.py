"""Tests for the GenomicDataPage model and its listing service."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import RequestFactory
from wagtail.models import Page, Site
from wagtail.test.utils import WagtailPageTestCase

from cms.pages import GenomicDataPage, HomePage
from cms.services.genomic_data import (
    DEFAULT_PAGE_SIZE,
    Sort,
    build_context_dict,
    resolve_state,
)


def fake_ebi_search(total: int = 3, facets: list[dict] | None = None) -> MagicMock:
    """Build a fake fetch_json answering EBI Search requests.

    Count requests (size=0) return ``total``. Searches return ``total`` hits and the
    page of generated entries (accessions ERX0, ERX1, ...) asked for by start/size.
    """

    def side_effect(url: str, params: dict) -> dict:
        if params["size"] == 0:
            return {"hitCount": total}
        start, size = params["start"], params["size"]
        entries = [
            {
                "acc": f"ERX{n}",
                "fields": {
                    "acc": [f"ERX{n}"],
                    "scientific_name": ["Escherichia coli"],
                    "TAXON": ["562"],
                    "collection_date": ["20240102"],
                },
            }
            for n in range(start, min(start + size, total))
        ]
        return {"hitCount": total, "entries": entries, "facets": facets or []}

    return MagicMock(side_effect=side_effect)


CLASSIFICATION = {
    "id": "classification",
    "label": "Classification",
    "facetValues": [
        {"value": "bacteria", "label": "Bacteria", "count": 15974},
        {"value": "viruses", "label": "Viruses", "count": 2680},
    ],
}
HOSTS = {
    "id": "host",
    "label": "Host",
    "facetValues": [
        {"value": f"Host {n}", "label": f"Host {n}", "count": 10 - n} for n in range(8)
    ],
}


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
            content=[("text", "<p>Some descriptive text.</p>"), ("ena_data", None)],
        )
        cls.home.add_child(instance=cls.page)
        cls.page.save_revision().publish()

    def setUp(self):
        """Clear the cache so EBI Search results don't leak between tests."""
        cache.clear()

    def get_htmx(self, params: dict | list | None = None):
        """GET the page as an HTMX request with the given query parameters."""
        return self.client.get(self.page.url, params or {}, HTTP_HX_REQUEST="true")

    def searches(self, mock_fetch: MagicMock) -> list[dict]:
        """Return the params of every search (non-count) request sent to EBI Search."""
        return [c.kwargs["params"] for c in mock_fetch.call_args_list if c.kwargs["params"]["size"]]

    # --- Page model ---------------------------------------------------------------

    def test_can_be_created_under_home_page_only(self):
        """Test the page can only live under the home page."""
        self.assertAllowedParentPageTypes(GenomicDataPage, {HomePage})
        self.assertAllowedSubpageTypes(GenomicDataPage, set())

    @patch("portal_data.ebi_search.fetch_json")
    def test_full_page_renders_search_form_without_calling_ebi(self, mock_fetch: MagicMock):
        """Test the full page has the search box and lazy-load container, but no API calls."""
        response = self.client.get(self.page.url, {"q": "coli", "type": "samples"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Some descriptive text.")
        self.assertContains(response, 'id="ena-search-input" name="q" value="coli"')
        self.assertContains(response, "<h1>Genomic data</h1>")
        self.assertContains(response, 'href="/genomic-data/" class="btn btn-outline btn-sm"')
        self.assertContains(response, 'hx-get="/genomic-data/?q=coli&amp;type=samples"')
        mock_fetch.assert_not_called()

    @patch("portal_data.ebi_search.fetch_json")
    def test_htmx_history_restore_gets_full_page(self, mock_fetch: MagicMock):
        """Test an HTMX history restore request gets the full page, not the partial."""
        response = self.client.get(
            self.page.url, HTTP_HX_REQUEST="true", HTTP_HX_HISTORY_RESTORE_REQUEST="true"
        )
        self.assertContains(response, "Some descriptive text.")
        mock_fetch.assert_not_called()

    # --- Listing ------------------------------------------------------------------

    @patch("portal_data.ebi_search.fetch_json")
    def test_default_listing(self, mock_fetch: MagicMock):
        """Test the default listing shows sequences, tab counts and linked rows."""
        mock_fetch.side_effect = fake_ebi_search(total=3).side_effect
        response = self.get_htmx()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="type" value="sequences"')
        self.assertContains(response, "Showing 1 to 3 of 3 sequences from Sweden")
        self.assertContains(response, 'href="https://www.ebi.ac.uk/ena/browser/view/ERX0"')
        self.assertContains(response, 'href="https://www.ebi.ac.uk/ena/browser/view/Taxon:562"')
        self.assertContains(response, "2024-01-02")
        for label in ("Sequences", "Analyses", "Raw reads", "Samples", "Assemblies"):
            self.assertContains(response, label)
        self.assertEqual(
            self.searches(mock_fetch)[0]["query"], '(country:"Sweden") AND tag:pathogen'
        )

    @patch("portal_data.ebi_search.fetch_json")
    def test_data_type_selects_the_index(self, mock_fetch: MagicMock):
        """Test the ``type`` parameter picks the EBI Search domain."""
        mock_fetch.side_effect = fake_ebi_search().side_effect
        self.get_htmx({"type": "raw-reads"})
        search_urls = [
            c.kwargs["url"] for c in mock_fetch.call_args_list if c.kwargs["params"]["size"]
        ]
        self.assertEqual(search_urls, ["https://www.ebi.ac.uk/ebisearch/ws/rest/sra-experiment"])

    @patch("portal_data.ebi_search.fetch_json")
    def test_facets_are_rendered_as_labelled_checkboxes(self, mock_fetch: MagicMock):
        """Test facets render as fieldsets of checkboxes with counts and "Show more"."""
        mock_fetch.side_effect = fake_ebi_search(facets=[CLASSIFICATION, HOSTS]).side_effect
        response = self.get_htmx({"classification": "viruses"})
        content = response.content.decode()
        self.assertIn("<legend", content)
        self.assertIn("Classification", content)
        self.assertIn('name="classification" value="viruses"', content)
        self.assertIn("15,974", content)
        # the selected value is ticked, the other isn't
        self.assertRegex(content, r'value="viruses"\s+class="[^"]*" checked')
        self.assertNotRegex(content, r'value="bacteria"\s+class="[^"]*" checked')
        # hosts beyond the first four are in a hidden list, revealed by "Show more"
        more_list = content.index('<ul id="ena-facet-more-host"')
        self.assertLess(content.index("Host 3"), more_list)
        self.assertGreater(content.index("Host 4"), more_list)
        self.assertRegex(content, r'<ul id="ena-facet-more-host"\s+class="[^"]* hidden"')
        self.assertIn('aria-controls="ena-facet-more-host"', content)
        self.assertIn('aria-expanded="false"', content)
        self.assertContains(response, "Clear all filters")

    @patch("portal_data.ebi_search.fetch_json")
    def test_selected_hidden_facet_value_keeps_its_list_open(self, mock_fetch: MagicMock):
        """Test a ticked value beyond the first four keeps "Show more" expanded."""
        mock_fetch.side_effect = fake_ebi_search(facets=[HOSTS]).side_effect
        content = self.get_htmx({"host": "Host 6"}).content.decode()
        self.assertNotRegex(content, r'<ul id="ena-facet-more-host"\s+class="[^"]* hidden"')
        self.assertIn('aria-expanded="true"', content)
        self.assertIn("Show less", content)

    @patch("portal_data.ebi_search.fetch_json")
    def test_selected_facets_and_search_are_sent(self, mock_fetch: MagicMock):
        """Test facet parameters and search words reach EBI Search."""
        mock_fetch.side_effect = fake_ebi_search().side_effect
        self.get_htmx({"type": "raw-reads", "q": "coli", "classification": ["bacteria", "viruses"]})
        params = self.searches(mock_fetch)[0]
        self.assertEqual(params["facets"], "classification:bacteria,classification:viruses")
        self.assertEqual(params["query"], '(country:"Sweden") AND tag:pathogen AND (coli)')

    @patch("portal_data.ebi_search.fetch_json")
    def test_pagination_requests_the_right_start(self, mock_fetch: MagicMock):
        """Test page 3 asks EBI Search for the third page, and links keep the state."""
        mock_fetch.side_effect = fake_ebi_search(total=DEFAULT_PAGE_SIZE * 10).side_effect
        response = self.get_htmx(
            {"type": "raw-reads", "q": "coli", "classification": "bacteria", "page": "3"}
        )
        params = self.searches(mock_fetch)[0]
        self.assertEqual(params["start"], DEFAULT_PAGE_SIZE * 2)
        self.assertEqual(params["size"], DEFAULT_PAGE_SIZE)
        self.assertContains(response, f'/view/ERX{DEFAULT_PAGE_SIZE * 2}"')
        self.assertContains(
            response, "?type=raw-reads&amp;q=coli&amp;classification=bacteria&amp;page=4"
        )

    @patch("portal_data.ebi_search.fetch_json")
    def test_page_size_can_be_chosen(self, mock_fetch: MagicMock):
        """Test a chosen page size is requested from EBI Search and kept in every link."""
        mock_fetch.side_effect = fake_ebi_search(total=500).side_effect
        response = self.get_htmx({"type": "raw-reads", "size": "50", "page": "2"})
        params = self.searches(mock_fetch)[0]
        self.assertEqual(params["size"], 50)
        self.assertEqual(params["start"], 50)
        self.assertContains(response, "Showing 51 to 100 of 500")
        self.assertContains(response, '<option value="50" selected>50</option>')
        # pagination, tabs and sorting all keep the page size
        self.assertContains(response, "?type=raw-reads&amp;size=50&amp;page=3")
        self.assertContains(response, 'href="/genomic-data/?type=samples&amp;size=50"')
        self.assertContains(response, "sort=acc&amp;order=asc&amp;size=50")

    @patch("portal_data.ebi_search.fetch_json")
    def test_default_page_size(self, mock_fetch: MagicMock):
        """Test the default page size is preselected and left out of links."""
        mock_fetch.side_effect = fake_ebi_search(total=500).side_effect
        response = self.get_htmx({"type": "raw-reads"})
        self.assertEqual(self.searches(mock_fetch)[0]["size"], DEFAULT_PAGE_SIZE)
        self.assertContains(
            response, f'<option value="{DEFAULT_PAGE_SIZE}" selected>{DEFAULT_PAGE_SIZE}</option>'
        )
        self.assertContains(response, '<label for="ena-page-size">Per page</label>')
        self.assertNotContains(response, "size=")

    def test_unsupported_page_size_falls_back_to_default(self):
        """Test page sizes outside the offered options are ignored."""
        for size in ("10", "1000", "abc", ""):
            with self.subTest(size=size):
                request = self.factory.get("/", {"size": size})
                self.assertEqual(resolve_state(request).page_size, DEFAULT_PAGE_SIZE)

    @patch("portal_data.ebi_search.fetch_json")
    def test_page_beyond_last_is_clamped(self, mock_fetch: MagicMock):
        """Test an out-of-range page shows the last page."""
        mock_fetch.side_effect = fake_ebi_search(total=30).side_effect
        response = self.get_htmx({"page": "999"})
        self.assertContains(response, "Showing 26 to 30 of 30")
        self.assertEqual(self.searches(mock_fetch)[-1]["start"], DEFAULT_PAGE_SIZE)

    @patch("portal_data.ebi_search.fetch_json")
    def test_sortable_headers(self, mock_fetch: MagicMock):
        """Test sortable columns link to sorting, the sorted one flips and has aria-sort."""
        mock_fetch.side_effect = fake_ebi_search().side_effect
        response = self.get_htmx({"type": "raw-reads", "sort": "collection_date", "order": "asc"})
        self.assertEqual(self.searches(mock_fetch)[0]["sort"], "collection_date:ascending")
        self.assertContains(response, 'aria-sort="ascending"', count=1)
        self.assertContains(response, "sort=collection_date&amp;order=desc")
        self.assertContains(response, "sort=acc&amp;order=asc")
        # Organism isn't sortable in EBI Search, so its header isn't a link
        self.assertNotContains(response, "sort=scientific_name")
        # checkbox changes keep the sort through hidden inputs
        self.assertContains(response, '<input type="hidden" name="sort" value="collection_date">')

    @patch("portal_data.ebi_search.fetch_json")
    def test_type_tabs_keep_search_but_drop_facets_and_sort(self, mock_fetch: MagicMock):
        """Test switching data type keeps the search words only."""
        mock_fetch.side_effect = fake_ebi_search().side_effect
        response = self.get_htmx(
            {"q": "coli", "classification": "bacteria", "sort": "acc", "order": "desc"}
        )
        self.assertContains(response, 'href="/genomic-data/?type=samples&amp;q=coli"')

    @patch("portal_data.ebi_search.fetch_json")
    def test_no_results(self, mock_fetch: MagicMock):
        """Test a search with no hits shows a message."""
        mock_fetch.side_effect = fake_ebi_search(total=0).side_effect
        response = self.get_htmx({"q": "nothing"})
        self.assertContains(response, "No sequences found")
        self.assertContains(response, "No sequences from Sweden match your current search.")
        self.assertNotContains(response, "<table")

    @patch("portal_data.ebi_search.fetch_json")
    def test_failure_shows_error(self, mock_fetch: MagicMock):
        """Test EBI Search being unreachable shows an error message."""
        mock_fetch.return_value = None
        response = self.get_htmx()
        self.assertContains(response, "could not be loaded from ENA")

    # --- Service helpers ----------------------------------------------------------

    def test_resolve_state_validates_input(self):
        """Test unknown types, facets, comma values and unsortable fields are dropped."""
        request = self.factory.get(
            "/",
            {
                "type": "nonsense",
                "q": "  coli \n",
                "classification": ["viruses", "viruses", ""],
                "host": "A, B",
                "not_a_facet": "x",
                "sort": "scientific_name",
            },
        )
        state = resolve_state(request)
        self.assertEqual(state.data_type.key, "sequences")
        self.assertEqual(state.text, "coli")
        self.assertEqual(state.facets, {"classification": ["viruses"]})
        self.assertIsNone(state.sort)

    def test_resolve_state_sort(self):
        """Test a sortable field is accepted, with order defaulting to ascending."""
        for order, descending in (("desc", True), ("asc", False), ("sideways", False)):
            with self.subTest(order=order):
                request = self.factory.get(
                    "/", {"type": "raw-reads", "sort": "acc", "order": order}
                )
                self.assertEqual(resolve_state(request).sort, Sort("acc", descending))

    @patch("portal_data.ebi_search.fetch_json")
    def test_invalid_page_number_defaults_to_first_page(self, mock_fetch: MagicMock):
        """Test a non-numeric page parameter is treated as page 1."""
        mock_fetch.side_effect = fake_ebi_search(total=30).side_effect
        context = build_context_dict(self.factory.get(self.page.url, {"page": "abc"}))
        self.assertEqual(context["page_obj"].number, 1)
