"""Tests for the home page."""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import RequestFactory
from django.utils import timezone
from wagtail.models import Page, PageViewRestriction, Site
from wagtail.test.utils import WagtailPageTestCase

from cms.pages import HomePage, NewsIndexPage


class TestHomePageClean(WagtailPageTestCase):
    """Tests for the clean method of the HomePage model."""

    def setUp(self):
        """Set up a HomePage instance for testing."""
        self.home_page = HomePage(title="Home", slug="home")

    def test_allows_no_button(self):
        """Test that a HomePage can be valid without any button text, page, or link."""
        self.home_page.clean()

    def test_allows_button_with_page(self):
        """Test that a HomePage can be valid with button text and a page, but no link."""
        self.home_page.hero_title = "Home"
        self.home_page.hero_button_text = "Learn more"
        self.home_page.hero_button_page = Page(title="Target")

        self.home_page.clean()

    def test_allows_button_with_link(self):
        """Test that a HomePage can be valid with button text and a link, but no page."""
        self.home_page.hero_title = "Home"
        self.home_page.hero_button_text = "Learn more"
        self.home_page.hero_button_link = "https://example.com/"

        self.home_page.clean()

    def test_rejects_button_text_without_hero_title_or_text(self):
        """Test that a HomePage is invalid if button text is provided without a hero title/text."""
        self.home_page.hero_button_text = "Learn more"
        self.home_page.hero_button_link = "https://example.com/"

        with self.assertRaises(ValidationError):
            self.home_page.clean()

    def test_rejects_button_text_without_page_or_link(self):
        """Test that a HomePage is invalid if button text is provided without a page or link."""
        self.home_page.hero_title = "Home"
        self.home_page.hero_button_text = "Learn more"

        with self.assertRaises(ValidationError):
            self.home_page.clean()

    def test_rejects_page_and_link_together(self):
        """Test that a HomePage is invalid if both page and link are provided with button text."""
        self.home_page.hero_title = "Home"
        self.home_page.hero_button_text = "Learn more"
        self.home_page.hero_button_page = Page(title="Target")
        self.home_page.hero_button_link = "https://example.com/"

        with self.assertRaises(ValidationError):
            self.home_page.clean()

    def test_rejects_button_page_without_button_text(self):
        """Test that a HomePage is invalid if a button page is provided without button text."""
        self.home_page.hero_title = "Home"
        self.home_page.hero_button_page = Page(title="Target")

        with self.assertRaises(ValidationError):
            self.home_page.clean()

    def test_rejects_link_without_button_text(self):
        """Test that a HomePage is invalid if a button link is provided without button text."""
        self.home_page.hero_title = "Home"
        self.home_page.hero_button_link = "https://example.com/"

        with self.assertRaises(ValidationError):
            self.home_page.full_clean()


class HomePageContextTest(WagtailPageTestCase):
    """Tests for the get_context method of the HomePage model."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Create a site setup with a home page and a dashboard index page."""

        root = Page.get_first_root_node()
        for child in root.get_children():
            child.delete()
        root = Page.get_first_root_node()
        cls.home_page = HomePage(title="Home", slug="home")
        root.add_child(instance=cls.home_page)

        Site.objects.update_or_create(
            is_default_site=True, defaults={"hostname": "testserver", "root_page": cls.home_page}
        )
        cls.request = RequestFactory().get("/")

    def test_context_contains_no_news_page_when_none_exists(self):
        """Test that the context contains no news page when none exists."""
        context = self.home_page.get_context(self.request)

        self.assertIsNone(context["news_page"])
        self.assertEqual(context["news_child_pages"], [])

    def test_context_contains_live_news_index_page(self):
        """Test that the context contains the live news index page when it exists."""
        news_page = self.home_page.add_child(instance=NewsIndexPage(title="News", slug="news"))
        news_page.save_revision().publish()

        context = self.home_page.get_context(self.request)

        self.assertEqual(context["news_page"], news_page)

    def test_context_contains_only_live_public_news_children(self):
        """Test that the context contains only live public news items, excluding drafts/private."""
        news_page = self.home_page.add_child(instance=NewsIndexPage(title="News", slug="news"))
        news_page.save_revision().publish()

        live_child = news_page.add_child(instance=Page(title="Live news", slug="live-news"))
        live_child.save_revision().publish()

        draft_child = news_page.add_child(instance=Page(title="Draft news", slug="draft-news"))
        draft_child.unpublish()  # Ensure this child is in draft state

        private_child = news_page.add_child(
            instance=Page(title="Private news", slug="private-news")
        )
        private_child.save_revision().publish()
        PageViewRestriction.objects.create(page=private_child, restriction_type="password")

        context = self.home_page.get_context(self.request)

        self.assertEqual(list(context["news_child_pages"]), [live_child])
        self.assertNotIn(draft_child, context["news_child_pages"])
        self.assertNotIn(private_child, context["news_child_pages"])

    def test_context_returns_three_most_recent_news_children(self):
        """Test that the context returns the three most recent news children."""
        news_page = self.home_page.add_child(instance=NewsIndexPage(title="News", slug="news"))
        news_page.save_revision().publish()

        children = []

        for index in range(5):
            child = news_page.add_child(instance=Page(title=f"News {index}", slug=f"news-{index}"))
            child.save_revision().publish()
            children.append(child)

        # Make the ordering deterministic.
        base_time = timezone.now()
        for index, child in enumerate(children):
            child.first_published_at = base_time + timedelta(days=index)
            child.save(update_fields=["first_published_at"])

        context = self.home_page.get_context(self.request)

        self.assertEqual(list(context["news_child_pages"]), list(reversed(children))[:3])
