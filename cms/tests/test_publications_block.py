"""Unit tests for PathogenBlock and PublicationsBlock."""

from django.test import SimpleTestCase
from wagtail.blocks import StructBlockValidationError

from cms.blocks.publications import PublicationsBlock


class TestPublicationsandPathogensBlocks(SimpleTestCase):
    """Tests for the PublicationsBlock and underlying PathogenBlock validation."""

    def setUp(self):
        """Set up test data."""
        self.block = PublicationsBlock()

    def test_valid_data_passes_validation(self):
        """Test that valid data passes validation."""
        value = self.block.to_python(
            {
                "pathogens": [
                    {"name": "Influenza", "search_terms": ["Influenza"]},
                    {"name": "AMR", "search_terms": ["antibiotic resistance", "AMR"]},
                ]
            }
        )
        result = self.block.clean(value)

        pathogens = result["pathogens"]
        self.assertEqual(len(pathogens), 2)
        self.assertEqual(pathogens[0]["name"], "Influenza")
        self.assertEqual(pathogens[1]["name"], "AMR")

    def test_pathogens_is_required(self):
        """Test that at least one pathogen is required."""
        value = self.block.to_python({"pathogens": []})
        with self.assertRaises(StructBlockValidationError) as context:
            self.block.clean(value)
        self.assertIn("pathogens", context.exception.block_errors)

    def test_search_terms_are_required_for_each_pathogen(self):
        """Test that each pathogen must have at least one search term."""
        value = self.block.to_python(
            {
                "pathogens": [
                    {"name": "Influenza", "search_terms": []},
                    {"name": "AMR", "search_terms": ["antibiotic resistance", "AMR"]},
                ]
            }
        )
        with self.assertRaises(StructBlockValidationError) as context:
            self.block.clean(value)
        self.assertIn("pathogens", context.exception.block_errors)
