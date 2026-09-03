"""Tests for the external link handler."""

from django.test import SimpleTestCase
from wagtail.rich_text import expand_db_html

from cms.handlers.external_link import ExternalLinkNewTabHandler


class TestExternalLinkNewTabHandler(SimpleTestCase):
    """Tests for the ExternalLinkNewTabHandler."""

    def test_identifier(self):
        """Test that the identifier is set correctly."""
        self.assertEqual(ExternalLinkNewTabHandler.identifier, "external")

    def test_expand_db_attributes(self):
        """Test that the expand_db_attributes method returns the correct HTML."""
        attrs = {"href": "https://example.com"}
        result = ExternalLinkNewTabHandler.expand_db_attributes(attrs)

        self.assertTrue(result.startswith("<a "))
        self.assertTrue(result.endswith(">"))
        self.assertIn('href="https://example.com"', result)
        self.assertIn('target="_blank"', result)
        self.assertIn('rel="noopener noreferrer"', result)

    def test_expand_db_attributes_preserves_existing_rel_tokens(self):
        """It should preserve existing rel tokens while appending required ones."""
        attrs = {"href": "https://example.com", "rel": "nofollow"}

        result = ExternalLinkNewTabHandler.expand_db_attributes(attrs)

        self.assertIn('rel="nofollow noopener noreferrer"', result)

    def test_expand_db_attributes_deduplicates_rel_tokens(self):
        """It should not duplicate noopener/noreferrer if already present."""
        attrs = {"href": "https://example.com", "rel": "noopener noreferrer"}

        result = ExternalLinkNewTabHandler.expand_db_attributes(attrs)

        # should still contain them once, not duplicated
        self.assertIn('rel="noopener noreferrer"', result)
        self.assertNotIn("noopener noreferrer noopener noreferrer", result)

    def test_expand_db_attributes_escapes_href(self):
        """Test that the expand_db_attributes method escapes the href attribute."""
        attrs = {"href": "'><script>alert('xss')</script>"}

        result = ExternalLinkNewTabHandler.expand_db_attributes(attrs)

        self.assertIn("&lt;script&gt;", result)
        self.assertNotIn("<script>", result)

    def test_expand_db_attributes_prevents_attribute_breakout(self):
        """It should escape quotes to prevent HTML attribute injection."""
        attrs = {"href": 'https://example.com" onclick="alert(1)'}

        result = ExternalLinkNewTabHandler.expand_db_attributes(attrs)

        # Ensure quotes are escaped so attributes cannot break out
        self.assertIn("&quot;", result)
        self.assertNotIn('onclick="', result)

    def test_expand_db_attributes_requires_href(self):
        """Test that the expand_db_attributes method raises a KeyError if href is missing."""
        with self.assertRaises(KeyError):
            ExternalLinkNewTabHandler.expand_db_attributes({})

    def test_expand_db_html_uses_registered_external_link_handler(self):
        """Test that the expand_db_html function uses the registered external link handler."""
        html = expand_db_html('<p><a href="https://example.com">link</a></p>')

        self.assertIn('href="https://example.com"', html)
        self.assertIn('target="_blank"', html)
        self.assertIn('rel="noopener noreferrer"', html)

    def test_expand_db_html_leaves_internal_relative_links_untouched(self):
        """Test that internal relative links are not modified by the external link handler."""
        html = expand_db_html('<p><a href="/about">about</a></p>')

        self.assertIn('href="/about"', html)
        self.assertNotIn('target="_blank"', html)
        self.assertNotIn('rel="noopener noreferrer"', html)
