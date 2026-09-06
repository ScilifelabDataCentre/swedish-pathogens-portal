"""Test cases for wagtailhooks.py."""

from django.test import SimpleTestCase
from wagtail.rich_text import features

from cms.handlers.external_link import ExternalLinkNewTabHandler

# -----------------------------------------------------------------------------
# Test external link feature registration
# -----------------------------------------------------------------------------


class TestExternalLinkFeature(SimpleTestCase):
    """Tests for the external link feature registration."""

    def test_register_external_link(self):
        """Test that the external link handler is registered as a rich text feature."""
        features_link_types = features.get_link_types()

        self.assertIn("external", features_link_types)
        self.assertIs(features_link_types["external"], ExternalLinkNewTabHandler)
