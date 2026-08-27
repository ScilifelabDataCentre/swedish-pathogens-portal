"""Tests for the PublicationsPage model."""

from unittest.mock import MagicMock, patch

from django.test import RequestFactory
from wagtail.models import Page, Site
from wagtail.test.utils import WagtailPageTestCase

from cms.pages import HomePage, PublicationsPage

from .test_publications_services import mock_europe_pmc_json


class TestPublicationsPage(WagtailPageTestCase):
    """Tests for the PublicationsPage model."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Create a home and a publications page."""
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

        cls.page = PublicationsPage(
            title="Publications",
            slug="publications",
            content=[
                ("text", "<p>Some descriptive text.</p>"),
                (
                    "publications",
                    {
                        "pathogens": [
                            {"name": "Influenza", "search_terms": ["Influenza"]},
                            {
                                "name": "Antibiotic Resistance",
                                "search_terms": ["antibiotic resistance", "AMR"],
                            },
                        ]
                    },
                ),
            ],
        )
        cls.home.add_child(instance=cls.page)
        cls.page.save_revision().publish()

    @patch("cms.pages.publications.resolve_active_pathogen")
    def test_get_context_active_pathogen_none_when_unresolved(self, mock_resolve: MagicMock):
        """Test get_context stores None when no pathogen could be resolved."""
        mock_resolve.return_value = None
        request = self.factory.get(self.page.url)
        context = self.page.get_context(request)
        self.assertIsNone(context["active_pathogen"])

    @patch("cms.services.publications.fetch_json")
    def test_full_page_load_renders_pathogen_side_nav(self, mock_get: MagicMock):
        """Test the plain page load renders both configured pathogens."""
        # don't care about the publications returned in this test
        mock_get.return_value = mock_europe_pmc_json(results=[])
        response = self.client.get(self.page.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Influenza")
        self.assertContains(response, "Antibiotic Resistance")

    @patch("cms.services.publications.fetch_json")
    def test_htmx_load_renders_fetched_publication(self, mock_get: MagicMock):
        """Test an HTMX request for a specific pathogen renders what Europe PMC returned."""
        mock_get.return_value = mock_europe_pmc_json(
            results=[
                {
                    "title": "A study of Influenza",
                    "authorString": "Doe J.",
                    "journalInfo": {"journal": {"title": "Journal of Testing"}},
                    "doi": "10.1234/abcd",
                },
                {
                    "title": "Another Influenza study",
                    "authorString": "Smith A.",
                    "journalInfo": {"journal": {"title": "Journal of More Testing"}},
                    "doi": "10.5678/efgh",
                },
            ]
        )
        response = self.client.get(
            self.page.url, {"pathogen": "Antibiotic Resistance"}, HTTP_HX_REQUEST="true"
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "A study of Influenza")
        self.assertContains(response, "Another Influenza study")
        self.assertContains(response, "Doe J.")
        self.assertContains(response, "Smith A.")
        self.assertContains(response, "Journal of Testing")
        self.assertContains(response, "Journal of More Testing")
        self.assertContains(response, "https://doi.org/10.1234/abcd")
        self.assertContains(response, "https://doi.org/10.5678/efgh")

    @patch("cms.services.publications.fetch_json")
    def test_htmx_load_for_unrecognized_pathogen_shows_message(self, mock_get: MagicMock):
        """Test an unconfigured pathogen requested via HTMX shows the "isn't recognized" message."""
        mock_get.return_value = mock_europe_pmc_json(results=[])
        with self.assertLogs("cms.services.publications", level="WARNING"):
            response = self.client.get(
                self.page.url, {"pathogen": "Nonexistent"}, HTTP_HX_REQUEST="true"
            )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "isn't recognized")
