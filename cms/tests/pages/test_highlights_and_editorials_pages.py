"""Tests for highlights and editorials pages."""

from unittest.mock import MagicMock, patch

from django.test import RequestFactory
from wagtail.models import Page, Site
from wagtail.test.utils import WagtailPageTestCase

from cms.pages import (
    HighlightsAndEditorialsIndexPage,
    HighlightsAndEditorialsPage,
    HomePage,
)
from cms.tests.utils import create_test_image

#######################################################################
############# Helper classes and functions for testing ################
#######################################################################


class BasePageTestCase(WagtailPageTestCase):
    """Base test case for page tests, providing common setup and utilities."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Create a site setup with a home page and a highlights/editorials index page."""

        cls.factory = RequestFactory()
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

        cls.index_page = HighlightsAndEditorialsIndexPage(
            title="Highlights and Editorials", slug="highlights-and-editorials"
        )
        cls.home.add_child(instance=cls.index_page)
        cls.index_page.save_revision().publish()


#######################################################################################
############### Test suite for HighlightsAndEditorialsIndexPage model #################
#######################################################################################


class TestHighlightsAndEditorialsIndexPage(BasePageTestCase):
    """Tests for the HighlightsAndEditorialsIndexPage model."""

    def test_max_count_set_on_model(self):
        """Test that only one instance of HighlightsAndEditorialsIndexPage can be created."""
        self.assertEqual(HighlightsAndEditorialsIndexPage.max_count, 1)

    def test_parent_page_type_restriction(self):
        """Test that only HomePage can be a parent of HighlightsAndEditorialsIndexPage."""
        self.assertEqual(HighlightsAndEditorialsIndexPage.parent_page_types, ["cms.HomePage"])

    def test_subpage_type_restriction(self):
        """Test that only HighlightsAndEditorialsPage can be added as a child."""
        self.assertEqual(
            HighlightsAndEditorialsIndexPage.subpage_types, ["cms.HighlightsAndEditorialsPage"]
        )

    @patch("cms.pages.highlights_and_editorials_index.validate_filters")
    def test_get_context_adds_filter_metadata(self, mock_validate_filters: MagicMock):
        """Test that get_context adds the correct filter metadata to the context."""
        mock_validate_filters.return_value = {}

        request = self.factory.get("/")

        with (
            patch("cms.pages.HighlightsAndEditorialsTopic.objects.filter") as mock_topic_filter,
            patch("cms.pages.HighlightsAndEditorialsPage.objects.child_of") as mock_child_of,
        ):
            # Mock topics queryset chain
            mock_topic_filter.return_value.values_list.return_value.distinct.return_value = [
                "COVID-19",
                "Infectious Diseases",
            ]

            # Mock article queryset chain
            mock_queryset = MagicMock()
            (
                mock_child_of.return_value.live.return_value.public.return_value.prefetch_related.return_value.order_by.return_value.distinct.return_value.filter.return_value
            ) = mock_queryset

            context = self.index_page.get_context(request)

        self.assertEqual(context["all_topics"], ["COVID-19", "Infectious Diseases"])
        self.assertEqual(
            context["all_article_types"],
            ["Data Highlight", "Editorial"],
        )
        self.assertEqual(context["articles_list"], mock_queryset)

        mock_validate_filters.assert_called_once_with(
            request.GET,
            valid_topics=["COVID-19", "Infectious Diseases"],
            valid_types=["Data Highlight", "Editorial"],
        )

    @patch("cms.pages.highlights_and_editorials_index.validate_filters")
    def test_get_context_applies_search_filter(self, mock_validate_filters: MagicMock):
        """Test that get_context applies the search filter correctly."""
        mock_validate_filters.return_value = {
            "search": "influenza",
        }

        request = self.factory.get("/?search=influenza")

        with (
            patch("cms.pages.HighlightsAndEditorialsTopic.objects.filter") as mock_topic_filter,
            patch("cms.pages.HighlightsAndEditorialsPage.objects.child_of") as mock_child_of,
        ):
            mock_topic_filter.return_value.values_list.return_value.distinct.return_value = []

            mock_filter = MagicMock()

            queryset_chain = mock_child_of.return_value.live.return_value.public.return_value.prefetch_related.return_value.order_by.return_value.distinct.return_value  # noqa: E501

            queryset_chain.filter.return_value = mock_filter

            context = self.index_page.get_context(request)

        self.assertEqual(context["articles_list"], mock_filter)
        queryset_chain.filter.assert_called_once()


##################################################################################
############### Test suite for HighlightsAndEditorialsPage model #################
##################################################################################


class TestHighlightsAndEditorialsPage(BasePageTestCase):
    """Tests for the HighlightsAndEditorialsPage model."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Create a HighlightsAndEditorialsPage instance for testing."""

        super().setUpTestData()

        image = create_test_image(title="Test Image", file_name="test_image.jpg")
        cls.editorial_page = HighlightsAndEditorialsPage(
            title="Article",
            slug="article",
            image=image,
            description="Test description",
            article_type="editorial",
            keywords="COVID-19, Infectious Diseases",
        )

        cls.index_page.add_child(instance=cls.editorial_page)
        cls.editorial_page.save_revision().publish()

    def test_parent_page_type_restriction(self):
        """Test that only HighlightsAndEditorialsIndexPage can be the parent."""
        self.assertEqual(
            HighlightsAndEditorialsPage.parent_page_types, ["cms.HighlightsAndEditorialsIndexPage"]
        )

    def test_subpage_type_restriction(self):
        """Test that no child pages can be added to HighlightsAndEditorialsPage."""
        self.assertEqual(HighlightsAndEditorialsPage.subpage_types, [])

    def test_image_field_is_required_by_model_constraint(self):
        """Test that the image field is required based on the model definition."""
        field = HighlightsAndEditorialsPage._meta.get_field("image")
        self.assertFalse(field.blank)

    def test_description_is_required_by_model_constraint(self):
        """Test that the description field is required based on the model definition."""
        field = HighlightsAndEditorialsPage._meta.get_field("description")
        self.assertFalse(field.blank)

    def test_status_field_is_required_by_model_constraint(self):
        """Test that the status field is required based on the model definition."""
        field = HighlightsAndEditorialsPage._meta.get_field("article_type")
        self.assertFalse(field.blank)

    def test_status_field_has_correct_choices(self):
        """Test that the status field has the correct choices defined."""
        field = HighlightsAndEditorialsPage._meta.get_field("article_type")
        expected_choices = [("data-highlight", "Data Highlight"), ("editorial", "Editorial")]
        self.assertEqual(field.choices, expected_choices)

    def test_keyword_list_returns_cleaned_keywords(self):
        """Test that the keyword_list property returns a cleaned list of keywords."""
        self.assertEqual(self.editorial_page.keyword_list, ["covid-19", "infectious diseases"])

    def test_topics_returns_topics_sorted_by_title(self):
        """Test that the topics property returns topics sorted alphabetically by title."""
        topic_b = MagicMock()
        topic_b.title = "Zebra"

        topic_a = MagicMock()
        topic_a.title = "AI"

        rel1 = MagicMock(topic=topic_b)
        rel2 = MagicMock(topic=topic_a)

        manager_cls = self.editorial_page.article_topics.__class__

        with patch.object(manager_cls, "all", return_value=[rel1, rel2]):
            topics = list(self.editorial_page.topics)

        self.assertEqual([topic.title for topic in topics], ["AI", "Zebra"])

    @patch("cms.pages.highlights_and_editorials.get_related_articles")
    def test_get_context_adds_parent_heading_and_related_articles(
        self, mock_related_articles: MagicMock
    ):
        """Test that the parent page heading and related articles are added to the context."""
        request = self.factory.get("/")

        related_articles = [MagicMock(), MagicMock()]
        mock_related_articles.return_value = related_articles

        context = self.editorial_page.get_context(request)

        # The page heading should be same as the parent index page title set in setUpTestData
        self.assertEqual(context["page_heading"], "Highlights and Editorials")
        self.assertEqual(context["related_articles"], related_articles)

        mock_related_articles.assert_called_once_with(self.editorial_page)
