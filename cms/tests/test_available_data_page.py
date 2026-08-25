"""Tests for the AvailableDataPage model."""

from unittest.mock import MagicMock, patch

from wagtail.models import Page, Site
from wagtail.test.utils import WagtailPageTestCase

from cms.pages import AvailableDataPage, HomePage


class TestAvailableDataPage(WagtailPageTestCase):
    """Tests for the AvailableDataPage model."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Create a home and an available data page."""
        root = Page.get_first_root_node()
        for child in root.get_children():
            child.delete()
        root = Page.get_first_root_node()
        cls.home = HomePage(title="Home", slug="home")
        root.add_child(instance=cls.home)
        Site.objects.update_or_create(
            is_default_site=True, defaults={"hostname": "testserver", "root_page": cls.home}
        )

        cls.page = AvailableDataPage(
            title="Available Data",
            slug="available-data",
            content=[
                ("text", "<p>Some descriptive text.</p>"),
                ("available_data", {}),
            ],
        )
        cls.home.add_child(instance=cls.page)
        cls.page.save_revision().publish()

    def test_full_page_load_renders_lazy_load_container(self):
        """Test the plain page load renders the HTMX lazy-load wrapper, not any counts."""
        response = self.client.get(self.page.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'hx-trigger="load once"')
        self.assertContains(response, 'id="available-data-counts"')

    @patch("cms.services.available_data.fetch_ebi_hit_count", return_value=5)
    @patch("cms.services.available_data.fetch_priority_pathogen_taxon_ids", return_value=["9606"])
    def test_htmx_load_renders_both_sections(
        self, mock_taxon_ids: MagicMock, mock_hit_count: MagicMock
    ):
        """Test an HTMX request renders both sections with the fetched counts."""
        response = self.client.get(self.page.url, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)

        self.assertContains(response, "Outbreaks")
        self.assertContains(response, "Pathogen Sequences")
        self.assertContains(response, "Priority Pathogens")
        self.assertContains(response, "Raw Reads")
        self.assertContains(response, "Samples")
        self.assertContains(response, "Assembly")

        # 6 outbreaks rows and 5 pathogen sequences rows, each mocked to 5.
        self.assertContains(response, "<strong>30</strong>")
        self.assertContains(response, "<strong>25</strong>")

    @patch("cms.services.available_data.fetch_ebi_hit_count", return_value=0)
    @patch("cms.services.available_data.fetch_priority_pathogen_taxon_ids", return_value=[])
    def test_htmx_load_with_all_fetches_failing_still_renders(
        self, mock_taxon_ids: MagicMock, mock_hit_count: MagicMock
    ):
        """Test the page still renders (with zero counts) if every EBI fetch fails."""
        response = self.client.get(self.page.url, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        # 2 section totals + 6 outbreaks rows + 5 pathogen sequences rows, all mocked to 0.
        self.assertContains(response, "<strong>0</strong>", count=13)
