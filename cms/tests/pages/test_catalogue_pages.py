"""Tests for the CataloguePage model."""

from unittest.mock import MagicMock, patch

from django.test import RequestFactory
from wagtail.models import Page, Site
from wagtail.test.utils import WagtailPageTestCase

from cms.pages import CataloguePage, HomePage
from cms.tests.utils import create_test_image


class TestCataloguePage(WagtailPageTestCase):
    """Base test case for page tests, providing common setup and utilities."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Create a site setup with a home page and a catalogue page."""

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

        image1 = create_test_image(title="Image 1", file_name="test_image1.jpg")
        image2 = create_test_image(title="Image 2", file_name="test_image2.jpg")
        cls.catalogue = CataloguePage(
            title="Catalogue",
            slug="catalogue",
            filter_label="Catalogue Type",
            content=[
                (
                    "card_grid",
                    {
                        "cards": [
                            {
                                "title": "Bravo",
                                "description": "Bravo description",
                                "image": image1,
                                "url": "/bravo/",
                                "type": "Guides, Tools",
                                "keywords": "beta second",
                            },
                            {
                                "title": "Alpha",
                                "description": "Alpha description",
                                "image": image2,
                                "url": "/alpha/",
                                "type": "Tools",
                                "keywords": "first",
                            },
                        ]
                    },
                )
            ],
        )
        cls.home.add_child(instance=cls.catalogue)
        cls.catalogue.save_revision().publish()

    def test_parent_page_type_restriction(self):
        """Test that only HomePage can be a parent of CataloguePage."""
        self.assertEqual(CataloguePage.parent_page_types, ["cms.HomePage"])

    def test_subpage_type_restriction(self):
        """Test that only CataloguePage can be added as a child."""
        self.assertEqual(CataloguePage.subpage_types, [])

    def test_cards_returns_sorted_cards(self):
        """Test that the cards property returns cards sorted by title."""
        cards = self.catalogue.cards

        self.assertEqual(len(cards), 2)
        self.assertEqual(cards[0]["title"], "Alpha")
        self.assertEqual(cards[1]["title"], "Bravo")

    def test_card_types_returns_unique_sorted_types(self):
        """Test that the card_types property returns unique, sorted types."""
        self.assertEqual(self.catalogue.card_types, ["Guides", "Tools"])

    @patch("cms.pages.catalogue.validate_filters")
    def test_get_context_without_filters(self, mock_validate_filters: MagicMock):
        """Test get_context returns all cards when no filters are applied."""
        mock_validate_filters.return_value = {}

        request = self.factory.get("/catalogue/")
        context = self.catalogue.get_context(request)

        self.assertEqual(context["catalogue_types"], ["Guides", "Tools"])
        self.assertEqual(len(context["catalogue_list"]), 2)

    @patch("cms.pages.catalogue.validate_filters")
    def test_get_context_filters_by_search(self, mock_validate_filters: MagicMock):
        """Test get_context filters cards based on search query."""
        mock_validate_filters.return_value = {
            "search": "alpha",
        }

        request = self.factory.get("/catalogue/?search=alpha")
        context = self.catalogue.get_context(request)

        self.assertEqual(len(context["catalogue_list"]), 1)
        self.assertEqual(context["catalogue_list"][0]["title"], "Alpha")

    @patch("cms.pages.catalogue.validate_filters")
    def test_get_context_filters_by_type(self, mock_validate_filters: MagicMock):
        """Test get_context filters cards based on type filter."""
        mock_validate_filters.return_value = {"type": ["guides"]}

        request = self.factory.get("/catalogue/?type=guides")
        context = self.catalogue.get_context(request)

        self.assertEqual(len(context["catalogue_list"]), 1)
        self.assertEqual(context["catalogue_list"][0]["title"], "Bravo")
        self.assertEqual(context["type_filter"], ["guides"])
