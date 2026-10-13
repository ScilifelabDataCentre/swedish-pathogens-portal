"""Tests for card, card grid, and child-page card StreamField blocks."""

from django.test import TestCase
from wagtail.blocks import StructBlockValidationError

from cms.blocks.cards import (
    ALLOWED_CARD_DESCRIPTION_FEATURES,
    CardBlock,
    CardGridBlock,
    CatalogueCardBlock,
    CatalogueCardGridBlock,
)
from cms.tests.utils import create_test_image

#######################################################################
########################   CardBlock tests   ##########################
#######################################################################


class TestCardBlock(TestCase):
    """Tests for the CardBlock."""

    def setUp(self):
        """Set up test data."""
        self.block = CardBlock()

    def test_valid_card_data(self):
        """Test that valid data is accepted by the block."""
        image = create_test_image(title="Test image", file_name="test.jpg")
        value = self.block.to_python(
            {
                "image": image.id,
                "title": "Test title",
                "description": "Test <strong>description</strong>",
                "url": "https://example.com",
            }
        )

        result = self.block.clean(value)

        self.assertEqual(result["title"], "Test title")
        self.assertEqual(result["image"].title, "Test image")
        self.assertEqual(result["description"].source, "Test <strong>description</strong>")
        self.assertEqual(result["url"], "https://example.com")

    def test_missing_required_fields(self):
        """Test that missing required fields raise validation errors."""
        value = self.block.to_python({})

        with self.assertRaises(StructBlockValidationError) as ctx:
            self.block.clean(value)

        errors = ctx.exception.block_errors
        self.assertIn("image", errors)
        self.assertIn("title", errors)
        self.assertIn("description", errors)
        self.assertIn("url", errors)

    def test_description_only_allows_configured_features(self):
        """Test that only the configured rich-text features are enabled."""
        description_block = self.block.child_blocks["description"]

        self.assertEqual(description_block.features, ALLOWED_CARD_DESCRIPTION_FEATURES)

        # some false positives to check that other features are not enabled
        self.assertNotIn("h2", description_block.features)
        self.assertNotIn("ul", description_block.features)


#######################################################################
######################   CardGridBlock tests   ########################
#######################################################################


class TestCardGridBlock(TestCase):
    """Tests for the CardGridBlock."""

    def setUp(self):
        """Set up test data."""
        self.block = CardGridBlock()

    def test_min_num_enforced(self):
        """Test that the minimum number of cards is enforced."""
        value = self.block.to_python(
            {
                "cards": [],
            }
        )

        with self.assertRaises(StructBlockValidationError) as ctx:
            self.block.clean(value)

        errors = ctx.exception.block_errors
        self.assertIn("cards", errors)

    def test_valid_card_grid_data(self):
        """Test that valid card grid data is accepted by the block."""
        image1 = create_test_image(title="Image 1", file_name="image1.jpg")
        image2 = create_test_image(title="Image 2", file_name="image2.jpg")

        value = self.block.to_python(
            {
                "cards": [
                    {
                        "image": image1.id,
                        "title": "Card 1",
                        "description": "Description for card 1",
                        "url": "https://example.com/card1",
                    },
                    {
                        "image": image2.id,
                        "title": "Card 2",
                        "description": "<p>Description for card 2</p>",
                        "url": "https://example.com/card2",
                    },
                ]
            }
        )

        result = self.block.clean(value)

        self.assertEqual(len(result["cards"]), 2)
        self.assertEqual(result["cards"][0]["title"], "Card 1")
        self.assertEqual(result["cards"][0]["image"].title, "Image 1")
        self.assertEqual(result["cards"][0]["description"].source, "Description for card 1")
        self.assertEqual(result["cards"][0]["url"], "https://example.com/card1")
        self.assertEqual(result["cards"][1]["title"], "Card 2")
        self.assertEqual(result["cards"][1]["image"].title, "Image 2")
        self.assertEqual(result["cards"][1]["description"].source, "<p>Description for card 2</p>")
        self.assertEqual(result["cards"][1]["url"], "https://example.com/card2")


################################################################################
########################   CatalogueCardBlock tests   ##########################
################################################################################


class TestCatalogueCardBlock(TestCase):
    """Tests for the CatalogueCardBlock."""

    def setUp(self):
        """Set up test data."""
        self.block = CatalogueCardBlock()

    def test_valid_card_data(self):
        """Test that valid data is accepted by the block."""
        image = create_test_image(title="Test image", file_name="test.jpg")
        value = self.block.to_python(
            {
                "image": image.id,
                "title": "Test title",
                "description": "Test description",
                "url": "https://example.com",
                "type": "test-type",
                "keywords": "test, catalogue, card",
            }
        )

        result = self.block.clean(value)

        self.assertEqual(result["title"], "Test title")
        self.assertEqual(result["image"].title, "Test image")
        self.assertEqual(result["description"].source, "Test description")
        self.assertEqual(result["url"], "https://example.com")
        self.assertEqual(result["type"], "test-type")
        self.assertEqual(result["keywords"], "test, catalogue, card")

    def test_missing_required_fields(self):
        """Test that missing required fields raise validation errors."""
        value = self.block.to_python({})

        with self.assertRaises(StructBlockValidationError) as ctx:
            self.block.clean(value)

        errors = ctx.exception.block_errors
        self.assertIn("image", errors)
        self.assertIn("title", errors)
        self.assertIn("description", errors)
        self.assertIn("url", errors)
        self.assertIn("type", errors)
        self.assertNotIn("keywords", errors)


################################################################################
######################   CatalogueCardGridBlock tests   ########################
################################################################################


class TestCatalogueCardGridBlock(TestCase):
    """Tests for the CatalogueCardGridBlock."""

    def setUp(self):
        """Set up test data."""
        self.block = CatalogueCardGridBlock()

    def test_min_num_enforced(self):
        """Test that the minimum number of cards is enforced."""
        value = self.block.to_python(
            {
                "cards": [],
            }
        )

        with self.assertRaises(StructBlockValidationError) as ctx:
            self.block.clean(value)

        errors = ctx.exception.block_errors
        self.assertIn("cards", errors)

    def test_valid_card_grid_data(self):
        """Test that valid card grid data is accepted by the block."""
        image1 = create_test_image(title="Image 1", file_name="image1.jpg")
        image2 = create_test_image(title="Image 2", file_name="image2.jpg")

        value = self.block.to_python(
            {
                "cards": [
                    {
                        "image": image1.id,
                        "title": "Card 1",
                        "description": "<p>Description for card 1</p>",
                        "url": "https://example.com/card1",
                        "type": "type1",
                        "keywords": "keyword1, keyword2",
                    },
                    {
                        "image": image2.id,
                        "title": "Card 2",
                        "description": "Description for card 2",
                        "url": "https://example.com/card2",
                        "type": "type2",
                    },
                ]
            }
        )

        result = self.block.clean(value)

        self.assertEqual(len(result["cards"]), 2)
        self.assertEqual(result["cards"][0]["title"], "Card 1")
        self.assertEqual(result["cards"][0]["image"].title, "Image 1")
        self.assertEqual(result["cards"][0]["description"].source, "<p>Description for card 1</p>")
        self.assertEqual(result["cards"][0]["url"], "https://example.com/card1")
        self.assertEqual(result["cards"][0]["type"], "type1")
        self.assertEqual(result["cards"][0]["keywords"], "keyword1, keyword2")
        self.assertEqual(result["cards"][1]["title"], "Card 2")
        self.assertEqual(result["cards"][1]["image"].title, "Image 2")
        self.assertEqual(result["cards"][1]["description"].source, "Description for card 2")
        self.assertEqual(result["cards"][1]["url"], "https://example.com/card2")
        self.assertEqual(result["cards"][1]["type"], "type2")
        self.assertEqual(result["cards"][1]["keywords"], "")
