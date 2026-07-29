"""Tests for site-wide search (indexing, results view, autocomplete)."""

from io import StringIO

from django.core.management import call_command
from wagtail.models import Page, Site
from wagtail.test.utils import WagtailPageTestCase

from cms.pages import HomePage, NewsIndexPage, NewsPage
from cms.tests.utils import create_test_image


class SearchTestCase(WagtailPageTestCase):
    """Base setup: a site with a home page, a news index, and searchable pages."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Build a minimal live site and index it for search."""
        root = Page.get_first_root_node()
        for child in root.get_children():
            child.delete()
        root = Page.get_first_root_node()
        cls.home = HomePage(title="Home", slug="home")
        root.add_child(instance=cls.home)
        Site.objects.update_or_create(
            is_default_site=True,
            defaults={"hostname": "testserver", "root_page": cls.home},
        )
        cls.news_index = NewsIndexPage(title="News", slug="news")
        cls.home.add_child(instance=cls.news_index)
        cls.news_index.save_revision().publish()

        cls.article = NewsPage(
            title="Influenza surveillance update",
            slug="influenza-surveillance-update",
            description="Weekly zuluwidget report on national influenza monitoring.",
            image=create_test_image(),
        )
        cls.news_index.add_child(instance=cls.article)
        cls.article.save_revision().publish()

        call_command("update_index", stdout=StringIO())

    def test_page_description_is_searchable(self) -> None:
        """A distinctive term in a page's description field is findable."""
        results = Page.objects.live().public().search("zuluwidget")
        self.assertTrue(any(r.pk == self.article.pk for r in results))

    def test_search_page_returns_matches(self) -> None:
        """The results page lists a page whose text matches the query."""
        resp = self.client.get("/search/", {"q": "zuluwidget"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Influenza surveillance update")

    def test_blank_query_renders_prompt(self) -> None:
        """No query renders the empty prompt, not a zero-results message."""
        resp = self.client.get("/search/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Enter a search term")

    def test_no_results_message(self) -> None:
        """A non-matching query renders a friendly empty state."""
        resp = self.client.get("/search/", {"q": "notarealtermxyz"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "No results")

    def test_draft_pages_excluded(self) -> None:
        """Unpublished pages never appear in results."""
        draft = NewsPage(
            title="Zuluwidget draft",
            slug="zuluwidget-draft",
            description="zuluwidget secret draft",
            image=create_test_image(),
            live=False,
        )
        self.news_index.add_child(instance=draft)
        call_command("update_index", stdout=StringIO())
        resp = self.client.get("/search/", {"q": "zuluwidget"})
        self.assertNotContains(resp, "Zuluwidget draft")

    def test_facet_filter_narrows_to_type(self) -> None:
        """Selecting a type facet restricts results to that page type."""
        resp = self.client.get("/search/", {"q": "influenza", "type": "news"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Influenza surveillance update")
