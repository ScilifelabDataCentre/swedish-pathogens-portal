"""Unit tests for ``LastUpdatedBlock`` rendering."""

from datetime import date

from django.test import SimpleTestCase

from cms.blocks.last_updated import LastUpdatedBlock


class TestLastUpdatedBlock(SimpleTestCase):
    """Tests for the LastUpdatedBlock."""

    def setUp(self) -> None:
        """Set up test data."""
        self.block = LastUpdatedBlock()

    def test_renders_formatted_date(self) -> None:
        """Test that the block renders the data freshness date from context."""
        value = self.block.to_python(
            {
                "label": "All data last updated",
                "suffix": "(no longer updating)",
            }
        )
        context = self.block.get_context(
            value,
            parent_context={"data_updated_at": date(2024, 3, 1)},
        )
        html = self.block.render(value, context=context)

        self.assertIn("All data last updated", html)
        self.assertIn("March 1, 2024", html)
        self.assertIn("no longer updating", html)
        self.assertIn('datetime="2024-03-01"', html)
        self.assertIn("text-pp-dark-grey", html)

    def test_renders_nothing_without_date(self) -> None:
        """Test that the block renders empty output when no date is set."""
        value = self.block.to_python({})
        context = self.block.get_context(value, parent_context={"data_updated_at": None})
        html = self.block.render(value, context=context)

        self.assertEqual(html.strip(), "")
