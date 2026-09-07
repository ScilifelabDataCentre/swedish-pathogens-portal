"""Tests for news pages."""

from wagtail.models import Page, Site
from wagtail.test.utils import WagtailPageTestCase

from cms.pages import HomePage, NewsIndexPage, NewsPage
from cms.tests.utils import create_test_image

#######################################################################
############# Helper classes and functions for testing ################
#######################################################################


class BasePageTestCase(WagtailPageTestCase):
    """Base test case for page tests, providing common setup and utilities."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Create a site setup with a home page and a news index page for testing."""

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


#################################################################
############## Test suite for NewsIndexPage model ###############
#################################################################


class TestNewsIndexPage(BasePageTestCase):
    """Tests for the NewsIndexPage model."""

    def test_max_count_set_on_model(self):
        """Test that only one instance of NewsIndexPage can be created."""
        self.assertEqual(NewsIndexPage.max_count, 1)

    def test_parent_page_type_restriction(self):
        """Test that only HomePage can be a parent of NewsIndexPage."""
        self.assertEqual(NewsIndexPage.parent_page_types, ["cms.HomePage"])

    def test_subpage_type_restriction(self):
        """Test that only NewsPage can be added as a child of NewsIndexPage."""
        self.assertEqual(NewsIndexPage.subpage_types, ["cms.NewsPage"])

    def test_get_context_includes_all_news(self):
        """Test that the get_context method includes all NewsPage instances."""
        image1 = create_test_image(title="Image 1", file_name="image1.jpg")
        news1 = NewsPage(
            title="News Article 1",
            slug="news-article-1",
            description="Description for news article 1",
            image=image1,
        )
        self.news_index.add_child(instance=news1)
        news1.save_revision().publish()

        image2 = create_test_image(title="Image 2", file_name="image2.jpg")
        news2 = NewsPage(
            title="News Article 2",
            slug="news-article-2",
            description="Description for news article 2",
            image=image2,
        )
        self.news_index.add_child(instance=news2)
        news2.save_revision().publish()

        request = self.client.get("/news/").wsgi_request
        context = self.news_index.get_context(request)

        self.assertIn("all_news", context)
        all_news = context["all_news"]

        self.assertEqual(len(all_news), 2)
        self.assertTrue(all(isinstance(n, NewsPage) for n in all_news))
        self.assertEqual(all_news[0].title, "News Article 2")


##################################################################
################# Test suite for NewsPage model ##################
##################################################################


class TestNewsPage(BasePageTestCase):
    """Tests for the NewsPage model."""

    def test_parent_page_type_restriction(self):
        """Test that only NewsIndexPage can be a parent of NewsPage."""
        self.assertEqual(NewsPage.parent_page_types, ["cms.NewsIndexPage"])

    def test_subpage_type_restriction(self):
        """Test that NewsPage cannot have any child pages."""
        self.assertEqual(NewsPage.subpage_types, [])

    def test_image_field_is_required_by_model_constraint(self):
        """Test that the image field is required based on the model definition."""
        field = NewsPage._meta.get_field("image")
        self.assertFalse(field.blank)

    def test_description_is_required_by_model_constraint(self):
        """Test that the description field is required based on the model definition."""
        field = NewsPage._meta.get_field("description")
        self.assertFalse(field.blank)

    def test_can_create_news_page_under_news_index(self):
        """Test that a NewsPage can be created as a child of NewsIndexPage."""
        image = create_test_image(title="Test Image", file_name="test_image.jpg")
        news_page = NewsPage(
            title="Test News Article",
            slug="test-news-article",
            description="This is a test news article.",
            image=image,
        )
        self.news_index.add_child(instance=news_page)
        news_page.save_revision().publish()

        self.assertTrue(NewsPage.objects.filter(id=news_page.id).exists())
        self.assertEqual(news_page.get_parent(), self.news_index)
