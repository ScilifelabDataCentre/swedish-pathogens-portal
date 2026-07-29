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
