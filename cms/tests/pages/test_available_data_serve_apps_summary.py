"""Tests for the ServeAppsSummaryBlock on the AvailableDataPage, and the summary it loads."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.http import HttpResponse
from wagtail.models import Page, Site
from wagtail.test.utils import WagtailPageTestCase

from cms.pages import AvailableDataPage, HomePage, ServeAppsPage
from cms.tests.pages.test_serve_apps_page import serve_item

SERVE_RESPONSE = {
    "data": [
        serve_item(1, "Malaria explorer", "Plasma proteins during acute malaria."),
        serve_item(2, "TB and malaria", "Tuberculosis and malaria cohorts.", app_type="Custom App"),
        serve_item(3, "Bedaquiline simulator", "Tuberculosis treatment outcomes."),
        serve_item(4, "Malaria atlas", "Malaria maps.", app_type="Gradio App"),
        serve_item(5, "Flower classifier", "Predicts flower types from images."),
    ]
}


def summary_block(page: Page | None, **value: object) -> tuple[str, dict]:
    """Return a serve_apps_summary StreamField entry for ``page``, with any values replaced."""
    return (
        "serve_apps_summary",
        {"page": page, "title": "", "breakdown": "keyword", "max_rows": 8, **value},
    )


class TestServeAppsSummary(WagtailPageTestCase):
    """Tests for the Serve apps summary block and the summary section it loads."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Create a home, a models and apps page and an available data page."""
        root = Page.get_first_root_node()
        for child in root.get_children():
            child.delete()
        root = Page.get_first_root_node()
        cls.home = HomePage(title="Home", slug="home")
        root.add_child(instance=cls.home)
        Site.objects.update_or_create(
            is_default_site=True, defaults={"hostname": "testserver", "root_page": cls.home}
        )

        cls.serve_page = ServeAppsPage(
            title="Models and apps",
            slug="models-and-apps",
            content=[("serve_apps", {"include_app_ids": [], "exclude_app_ids": []})],
        )
        cls.home.add_child(instance=cls.serve_page)
        cls.serve_page.save_revision().publish()

        cls.page = AvailableDataPage(
            title="Available Data",
            slug="available-data",
            content=[("available_data", {}), summary_block(cls.serve_page)],
        )
        cls.home.add_child(instance=cls.page)
        cls.page.save_revision().publish()

    def setUp(self):
        """Clear the cache so Serve results don't leak between tests."""
        cache.clear()

    def set_block(self, **value: object) -> None:
        """Replace the available data page's summary block with one using ``value``."""
        self.page.content = [("available_data", {}), summary_block(self.serve_page, **value)]
        self.page.save_revision().publish()

    def get_summary(self, params: dict) -> HttpResponse:
        """GET the models and apps page's summary section, as the block's HTMX request does."""
        return self.client.get(self.serve_page.url, params, HTTP_HX_REQUEST="true")

    # --- The block on the Available data page -------------------------------------

    @patch("portal_data.serve_apps.fetch_json")
    def test_block_renders_lazy_loading_placeholder(self, mock_fetch: MagicMock):
        """The block renders a placeholder that loads the summary, without calling Serve."""
        response = self.client.get(self.page.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'hx-get="/models-and-apps/?summary=keyword&amp;rows=8"')
        self.assertContains(response, 'hx-swap="outerHTML"')
        mock_fetch.assert_not_called()

    @patch("portal_data.serve_apps.fetch_json")
    def test_block_passes_its_settings(self, _mock: MagicMock):
        """The breakdown, row count and title are passed on in the summary URL."""
        self.set_block(breakdown="type", max_rows=3, title="Apps & models")
        self.assertContains(
            self.client.get(self.page.url),
            'hx-get="/models-and-apps/?summary=type&amp;rows=3&amp;title=Apps+%26+models"',
        )

    @patch("portal_data.serve_apps.fetch_json")
    def test_block_renders_nothing_for_an_unpublished_page(self, _mock: MagicMock):
        """No placeholder is rendered when the chosen page isn't live."""
        self.serve_page.unpublish()
        try:
            self.assertNotContains(self.client.get(self.page.url), "summary=")
        finally:
            self.serve_page.save_revision().publish()

    # --- The summary section --------------------------------------------------------

    @patch("portal_data.serve_apps.fetch_json", return_value=SERVE_RESPONSE)
    def test_summary_by_pathogen_keyword(self, _mock: MagicMock):
        """Pathogen rows are counted, largest first, and link to the pre-filtered listing."""
        response = self.get_summary({"summary": "keyword", "rows": "8"})

        self.assertTemplateUsed(response, "cms/pages/serve_apps/partials/serve_summary.html")
        section = response.context["section"]
        self.assertEqual(section["title"], "Models and apps")
        self.assertEqual(section["total_count"], 4)
        self.assertEqual(section["total_url"], "/models-and-apps/")
        self.assertEqual(
            [(row["display_label"], row["count"], row["url"]) for row in section["rows"]],
            [
                ("Malaria", 3, "/models-and-apps/?keyword=malaria"),
                ("Tuberculosis", 2, "/models-and-apps/?keyword=tuberculosis"),
            ],
        )
        self.assertContains(response, "View all <strong>4</strong> results in Models and apps")
        self.assertContains(response, 'href="/models-and-apps/?keyword=malaria"')
        self.assertNotContains(response, 'target="_blank"')

    @patch("portal_data.serve_apps.fetch_json", return_value=SERVE_RESPONSE)
    def test_summary_by_app_type_with_title_and_row_limit(self, _mock: MagicMock):
        """The breakdown, title and row count come from the query string."""
        response = self.get_summary({"summary": "type", "rows": "2", "title": "Serve apps"})

        section = response.context["section"]
        self.assertEqual(section["title"], "Serve apps")
        self.assertEqual(
            [(row["label"], row["count"]) for row in section["rows"]],
            [("Shiny App", 2), ("Custom App", 1)],
        )
        self.assertEqual(section["rows"][0]["url"], "/models-and-apps/?type=Shiny+App")

    @patch("portal_data.serve_apps.fetch_json", return_value=SERVE_RESPONSE)
    def test_summary_follows_the_pages_include_and_exclude_settings(self, _mock: MagicMock):
        """The counts match the apps the page itself lists."""
        self.serve_page.content = [
            ("serve_apps", {"include_app_ids": [5], "exclude_app_ids": [4]}),
        ]
        self.serve_page.save_revision().publish()
        try:
            section = self.get_summary({"summary": "keyword"}).context["section"]
            self.assertEqual(section["total_count"], 4)
            self.assertEqual(
                [(row["label"], row["count"]) for row in section["rows"]],
                [("malaria", 2), ("tuberculosis", 2)],
            )
        finally:
            self.serve_page.content = [
                ("serve_apps", {"include_app_ids": [], "exclude_app_ids": []})
            ]
            self.serve_page.save_revision().publish()

    @patch("portal_data.serve_apps.fetch_json", return_value=SERVE_RESPONSE)
    def test_invalid_summary_params_fall_back_to_defaults(self, _mock: MagicMock):
        """Unknown breakdowns and bad row counts fall back to safe values."""
        section = self.get_summary({"summary": "bogus", "rows": "lots"}).context["section"]
        self.assertEqual(section["rows"][0]["label"], "malaria")
        self.assertEqual(len(section["rows"]), 2)

        section = self.get_summary({"summary": "type", "rows": "-5"}).context["section"]
        self.assertEqual(len(section["rows"]), 1)

    @patch("portal_data.serve_apps.fetch_json", return_value=None)
    def test_summary_renders_nothing_if_serve_is_unreachable(self, _mock: MagicMock):
        """A failed fetch replaces the placeholder with nothing."""
        response = self.get_summary({"summary": "keyword"})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "View all")

    @patch("portal_data.serve_apps.fetch_json", return_value=SERVE_RESPONSE)
    def test_listing_is_unchanged_without_summary_param(self, _mock: MagicMock):
        """Other HTMX requests to the models and apps page still get the listing."""
        response = self.client.get(self.serve_page.url, HTTP_HX_REQUEST="true")
        self.assertTemplateUsed(response, "cms/pages/serve_apps/partials/serve_listing.html")
