"""Tests for card, card grid, and child-page card StreamField blocks."""

from django.test import TestCase
from wagtail.blocks import StructBlockValidationError
from wagtail.models import Page, Site

from cms.blocks.cards import (
    ALLOWED_DESCRIPTION_FEATURES,
    CardBlock,
    CardGridBlock,
    CatalogueCardBlock,
    CatalogueCardGridBlock,
    ChildPageCardBlock,
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

        self.assertEqual(description_block.features, ALLOWED_DESCRIPTION_FEATURES)

        # some false positives to check that other features are not enabled
        self.assertNotIn("h2", description_block.features)
        self.assertNotIn("ul", description_block.features)

    def test_get_context_defaults_truncate_text_to_true(self):
        """Test that truncate_text defaults to True."""
        image = create_test_image(title="Test image", file_name="test.jpg")
        value = self.block.to_python(
            {
                "image": image.id,
                "title": "Test title",
                "description": "Test description",
                "url": "https://example.com",
            }
        )

        context = self.block.get_context(value)

        self.assertTrue(context["truncate_text"])

        context = self.block.get_context(value, {})

        self.assertTrue(context["truncate_text"])

    def test_get_context_uses_parent_truncate_text(self):
        """Test that truncate_text is inherited from the parent context."""
        image = create_test_image(title="Test image", file_name="test.jpg")
        value = self.block.to_python(
            {
                "image": image.id,
                "title": "Test title",
                "description": "Test description",
                "url": "https://example.com",
            }
        )

        parent_context = {"value": {"truncate_text": False}}
        context = self.block.get_context(value, parent_context)

        self.assertFalse(context["truncate_text"])

        parent_context = {"value": {"truncate_text": True}}
        context = self.block.get_context(value, parent_context)

        self.assertTrue(context["truncate_text"])


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

    def test_truncate_text_defaults_to_true(self):
        """Test that truncate_text defaults to True."""
        value = self.block.to_python({})

        self.assertTrue(value["truncate_text"])

    def test_truncate_text_set_value(self):
        """Test that truncate_text can be set to True."""
        image = create_test_image(title="Image 1", file_name="image1.jpg")
        value = {
            "truncate_text": False,
            "cards": [
                {
                    "image": image.id,
                    "title": "Card 1",
                    "description": "Description for card 1",
                    "url": "https://example.com/card1",
                }
            ],
        }
        result = self.block.clean(self.block.to_python(value))

        self.assertFalse(result["truncate_text"])

        value["truncate_text"] = True
        result = self.block.clean(self.block.to_python(value))

        self.assertTrue(result["truncate_text"])

    def test_card_rendering_with_truncate_text(self):
        """Test that card text is truncated when truncate_text is enabled."""
        image = create_test_image(title="Test image", file_name="test.jpg")
        value = {
            "truncate_text": True,
            "cards": [
                {
                    "image": image.id,
                    "title": "Card 1",
                    "description": "Description for card 1",
                    "url": "https://example.com/card1",
                }
            ],
        }

        html1 = self.block.render(self.block.to_python(value))

        value["truncate_text"] = False
        html2 = self.block.render(self.block.to_python(value))

        # Tailwind's `line-clamp` class is used to truncate text
        self.assertIn("line-clamp", html1)
        self.assertNotIn("line-clamp", html2)


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

    def test_truncate_text_defaults_to_true(self):
        """Test that truncate_text defaults to True."""
        value = self.block.to_python({})

        self.assertTrue(value["truncate_text"])

    def test_truncate_text_set_value(self):
        """Test that truncate_text can be set to True."""
        image = create_test_image(title="Image 1", file_name="image1.jpg")
        value = {
            "truncate_text": False,
            "cards": [
                {
                    "image": image.id,
                    "title": "Card 1",
                    "description": "Description for card 1",
                    "url": "https://example.com/card1",
                    "type": "type1",
                }
            ],
        }
        result = self.block.clean(self.block.to_python(value))

        self.assertFalse(result["truncate_text"])

        value["truncate_text"] = True
        result = self.block.clean(self.block.to_python(value))

        self.assertTrue(result["truncate_text"])

    def test_card_rendering_with_truncate_text(self):
        """Test that card text is truncated when truncate_text is enabled."""
        image = create_test_image(title="Test image", file_name="test.jpg")
        value = {
            "truncate_text": True,
            "cards": [
                {
                    "image": image.id,
                    "title": "Card 1",
                    "description": "Description for card 1",
                    "url": "https://example.com/card1",
                    "type": "type1",
                }
            ],
        }

        html1 = self.block.render(self.block.to_python(value))

        value["truncate_text"] = False
        html2 = self.block.render(self.block.to_python(value))

        # Tailwind's `line-clamp` class is used to truncate text
        self.assertIn("line-clamp", html1)
        self.assertNotIn("line-clamp", html2)


#######################################################################
####################   ChildPageCardBlock tests   #####################
#######################################################################


class TestChildPageCardBlock(TestCase):
    """Tests for the ChildPageCardBlock."""

    def setUp(self):
        """Set up test data."""

        self.root = Page.objects.get(id=1)

        Site.objects.update_or_create(
            id=1,
            defaults={
                "hostname": "localhost",
                "root_page": self.root,
                "is_default_site": True,
            },
        )

        self.parent = self.root.add_child(instance=Page(title="Parent", slug="parent"))
        self.child_b = self.parent.add_child(instance=Page(title="B page", slug="b"))  # noqa: F841
        self.child_a = self.parent.add_child(instance=Page(title="A page", slug="a"))  # noqa: F841
        self.child_d = self.parent.add_child(instance=Page(title="D page", slug="d"))  # noqa: F841
        self.child_c = self.parent.add_child(instance=Page(title="C page", slug="c"))  # noqa: F841

        self.block = ChildPageCardBlock()

    def test_returns_all_children_by_default(self):
        """Test that all child pages are returned by default."""

        value = self.block.to_python(
            {
                "parent_page": self.parent.id,
            }
        )

        result = self.block.clean(value)
        context = self.block.get_context(result)

        self.assertEqual(len(context["child_pages"]), 4)

    def test_limits_to_3(self):
        """Test that the number of child pages can be limited to 3."""
        value = self.block.to_python(
            {
                "parent_page": self.parent.id,
                "num_children": "3",
            }
        )

        result = self.block.clean(value)
        context = self.block.get_context(result)

        self.assertLessEqual(len(context["child_pages"]), 3)

    def test_order_by_title(self):
        """Test that child pages can be ordered by title."""
        value = self.block.to_python(
            {
                "parent_page": self.parent.id,
                "order_by": "title",
            }
        )

        result = self.block.clean(value)
        context = self.block.get_context(result)

        titles = [p.title for p in context["child_pages"]]
        self.assertEqual(titles, sorted(titles))

    def test_order_by_created(self):
        """Test that child pages can be ordered by creation date."""
        self.child_e = self.parent.add_child(instance=Page(title="E page", slug="e"))
        self.child_e.save_revision().publish()

        value = self.block.to_python(
            {
                "parent_page": self.parent.id,
                "order_by": "created",
            }
        )

        result = self.block.clean(value)
        context = self.block.get_context(result)

        self.assertEqual(context["child_pages"][0].title, "E page")

    def test_parent_with_no_children_returns_empty_list(self):
        """Test that a parent page with no children returns an empty list."""
        empty_parent = self.root.add_child(instance=Page(title="Empty parent", slug="empty-parent"))

        value = self.block.to_python(
            {
                "parent_page": empty_parent.id,
                "num_children": "all",
                "order_by": "created",
            }
        )

        result = self.block.clean(value)
        context = self.block.get_context(result)

        self.assertEqual(list(context["child_pages"]), [])
