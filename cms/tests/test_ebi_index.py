"""Tests for EBI index envelope settings (builder and public GET come later)."""

from django.test import TestCase

from cms.settings.ebi_index import (
    DEFAULT_CATALOGUE_NAME,
    DEFAULT_RELEASE,
    DEFAULT_RELEASE_DATE,
    EbiIndexSettings,
)


class EbiIndexSettingsTestCase(TestCase):
    """Envelope form on Wagtail Settings; no computed JSON fields."""

    def test_defaults(self) -> None:
        """Name, release, and date are prefilled; GitHub URL is empty."""
        settings = EbiIndexSettings.load()
        self.assertEqual(settings.name, DEFAULT_CATALOGUE_NAME)
        self.assertEqual(settings.release, DEFAULT_RELEASE)
        self.assertEqual(settings.release_date, DEFAULT_RELEASE_DATE)
        self.assertEqual(settings.github_releases_latest_url, "")

    def test_github_url_is_optional(self) -> None:
        """Editors may leave the GitHub latest-release URL blank."""
        field = EbiIndexSettings._meta.get_field("github_releases_latest_url")
        self.assertTrue(field.blank)

    def test_does_not_store_entry_count_or_entries(self) -> None:
        """entry_count and entries are computed later, not settings fields."""
        field_names = {field.name for field in EbiIndexSettings._meta.get_fields()}
        self.assertNotIn("entry_count", field_names)
        self.assertNotIn("entries", field_names)

    def test_admin_heading_is_ebi_index(self) -> None:
        """Settings form uses the EBI index heading."""
        self.assertEqual(EbiIndexSettings._meta.verbose_name, "EBI index")
        headings = [getattr(panel, "heading", None) for panel in EbiIndexSettings.panels]
        self.assertIn("EBI index", headings)
