"""Tests for the PortalDataSummaryBlock on the AvailableDataPage."""

from unittest.mock import MagicMock, patch

from django.core.cache import cache
from wagtail.models import Page, Site
from wagtail.test.utils import WagtailPageTestCase

from cms.pages import AvailableDataPage, HomePage, PortalDataPage

ITEMS = [
    {"id": "MTBLS1", "country": "", "technology": "mass spectrometry", "year": "2024"},
    {"id": "MTBLS2", "country": "", "technology": "mass spectrometry", "year": "2023"},
    {"id": "MTBLS3", "country": "", "technology": "NMR spectroscopy", "year": "2024"},
]


@patch("portal_data.summary.load_all_items", return_value=ITEMS)
class TestPortalDataSummaryBlock(WagtailPageTestCase):
    """Tests for rendering the portal data summary block on the available data page."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Create a home, a portal data page and an available data page."""
        root = Page.get_first_root_node()
        for child in root.get_children():
            child.delete()
        root = Page.get_first_root_node()
        cls.home = HomePage(title="Home", slug="home")
        root.add_child(instance=cls.home)
        Site.objects.update_or_create(
            is_default_site=True, defaults={"hostname": "testserver", "root_page": cls.home}
        )

        cls.portal_data_page = PortalDataPage(
            title="Portal Data", slug="portal-data", datatype="metabolomics"
        )
        cls.home.add_child(instance=cls.portal_data_page)
        cls.portal_data_page.save_revision().publish()

        cls.page = AvailableDataPage(
            title="Available Data",
            slug="available-data",
            content=[
                ("text", "<h2>Results for Sweden</h2>"),
                ("available_data", {}),
                (
                    "portal_data_summary",
                    {
                        "page": cls.portal_data_page,
                        "title": "",
                        "breakdown": "technology",
                        "max_rows": 8,
                        "country": "",
                    },
                ),
            ],
        )
        cls.home.add_child(instance=cls.page)
        cls.page.save_revision().publish()

    def setUp(self) -> None:
        """Start each test with an empty cache."""
        cache.clear()

    def test_renders_counts_on_full_page_load(self, mock_load: MagicMock) -> None:
        """The summary is rendered server-side, without waiting for the HTMX request."""
        response = self.client.get(self.page.url)
        self.assertEqual(response.status_code, 200)

        self.assertContains(response, "Metabolomics")
        self.assertContains(response, "View all <strong>3</strong> results in Metabolomics")
        self.assertContains(response, "results in mass spectrometry")
        self.assertContains(response, "results in NMR spectroscopy")
        self.assertContains(response, 'href="/portal-data/?technology=mass+spectrometry"')

    def test_internal_links_open_in_same_tab(self, mock_load: MagicMock) -> None:
        """Links into the portal data listing don't open a new tab."""
        response = self.client.get(self.page.url)
        self.assertContains(response, 'href="/portal-data/">')
        self.assertNotContains(response, 'href="/portal-data/" target="_blank"')

    def test_renders_nothing_when_portal_data_page_unpublished(self, mock_load: MagicMock) -> None:
        """The section is hidden if the chosen portal data page isn't live."""
        self.portal_data_page.unpublish()
        try:
            response = self.client.get(self.page.url)
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, "results in Metabolomics")
            mock_load.assert_not_called()
        finally:
            self.portal_data_page.save_revision().publish()
