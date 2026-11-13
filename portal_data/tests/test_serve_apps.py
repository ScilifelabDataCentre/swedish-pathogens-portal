"""Tests for the SciLifeLab Serve client used by the Models and apps page."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase

from portal_data.serve_apps import (
    SERVE_PUBLIC_APPS_URL,
    SERVE_TIMEOUT_SECONDS,
    ServeApp,
    fetch_public_apps,
    find_keywords,
    relevant_apps,
)


def serve_item(app_id: int = 1, **fields: object) -> dict:
    """Build one public-apps item, as Serve returns it, with any fields replaced."""
    item = {
        "id": app_id,
        "name": f"App {app_id}",
        "url": f"https://app{app_id}.serve.scilifelab.se",
        "description": "Explore malaria parasite proteomics.",
        "created_on": "2026-11-07T15:09:52.410Z",
        "updated_on": "2026-11-08T21:44:01.055Z",
        "access": "public",
        "latest_user_action": "Changing",
        "k8s_user_app_status": "Running",
        "app_status": "Running",
        "app_type": "Shiny App",
        "table_field": {"url": f"https://app{app_id}.serve.scilifelab.se"},
    }
    item.update(fields)
    return item


class TestServeAppFromApi(SimpleTestCase):
    """Parsing one item of the public-apps list."""

    def test_parses_fields(self):
        """Parses fields."""
        app = ServeApp.from_api(serve_item(5))
        self.assertEqual(app.id, 5)
        self.assertEqual(app.name, "App 5")
        self.assertEqual(app.url, "https://app5.serve.scilifelab.se")
        self.assertEqual(app.app_type, "Shiny App")
        self.assertEqual(app.updated_on, datetime(2026, 11, 8, 21, 44, 1, 55000, tzinfo=UTC))
        self.assertEqual(app.keywords, ("malaria", "parasite"))
        self.assertTrue(app.is_pathogen_related)

    def test_missing_optional_fields_get_defaults(self):
        """Missing optional fields get defaults."""
        app = ServeApp.from_api(
            serve_item(description=None, app_type="", created_on=None, updated_on="not a date")
        )
        self.assertEqual(app.description, "")
        self.assertEqual(app.app_type, "Other")
        self.assertIsNone(app.created_on)
        self.assertIsNone(app.updated_on)

    def test_unlistable_items_are_skipped(self):
        """Unlistable items are skipped."""
        for fields in (
            {"id": None},
            {"id": "5"},
            {"name": "  "},
            {"url": None},
            {"url": "javascript:alert(1)"},
            {"access": "private"},
            {"k8s_user_app_status": "Deleted"},
            {"app_status": "deleted"},
        ):
            with self.subTest(fields=fields):
                self.assertIsNone(ServeApp.from_api(serve_item(**fields)))

    def test_http_urls_are_allowed(self):
        """Http urls are allowed."""
        self.assertIsNotNone(ServeApp.from_api(serve_item(url="http://example.org")))


class TestKeywords(SimpleTestCase):
    """Matching the pathogen keywords."""

    def test_keywords_use_the_list_spelling_and_are_deduplicated(self):
        """Keywords use the list spelling and are deduplicated."""
        self.assertEqual(
            find_keywords("Malaria and malaria, then Bacteria"), ("malaria", "bacteria")
        )

    def test_underscores_in_names_separate_words(self):
        """Underscores in names separate words."""
        app = ServeApp.from_api(serve_item(name="malaria_crispr2024", description="CRISPR screen"))
        self.assertEqual(app.keywords, ("malaria",))

    def test_abbreviations_match_case_sensitively(self):
        """Abbreviations match case sensitively."""
        self.assertIn("AMR", find_keywords("An AMR knowledge graph"))
        self.assertNotIn("AMR", find_keywords("amr"))

    def test_weak_keywords_alone_are_not_pathogen_related(self):
        """Weak keywords alone are not pathogen related."""
        app = ServeApp.from_api(
            serve_item(name="PlasPredict", description="Predicts plasmid host range")
        )
        self.assertEqual(app.keywords, ("host",))
        self.assertFalse(app.is_pathogen_related)

    def test_unrelated_app_has_no_keywords(self):
        """Unrelated app has no keywords."""
        app = ServeApp.from_api(serve_item(description="Flower image classification"))
        self.assertEqual(app.keywords, ())
        self.assertFalse(app.is_pathogen_related)


class TestRelevantApps(SimpleTestCase):
    """Keeping the pathogen-related apps, with the editors' inclusions and exclusions."""

    def setUp(self):
        """Build the apps used by the tests."""
        self.related = ServeApp.from_api(serve_item(1))
        self.unrelated = ServeApp.from_api(serve_item(2, description="Flower classification"))
        self.apps = [self.related, self.unrelated]

    def test_keeps_pathogen_related_apps(self):
        """Keeps pathogen related apps."""
        self.assertEqual(relevant_apps(self.apps), [self.related])

    def test_included_ids_are_added(self):
        """Included ids are added."""
        self.assertEqual(relevant_apps(self.apps, include_ids=frozenset({2})), self.apps)

    def test_excluded_ids_are_removed_even_if_included(self):
        """Excluded ids are removed even if included."""
        self.assertEqual(
            relevant_apps(self.apps, include_ids=frozenset({2}), exclude_ids=frozenset({1, 2})), []
        )


class TestFetchPublicApps(SimpleTestCase):
    """Fetching (and caching) the public-apps list."""

    def setUp(self):
        """Clear the cache so Serve results don't leak between tests."""
        cache.clear()

    @patch("portal_data.serve_apps.fetch_json")
    def test_fetches_parses_and_caches(self, mock_fetch: MagicMock):
        """Fetches parses and caches."""
        mock_fetch.return_value = {"data": [serve_item(1), serve_item(2, access="private"), "junk"]}

        apps = fetch_public_apps()
        self.assertEqual([app.id for app in apps], [1])
        mock_fetch.assert_called_once_with(SERVE_PUBLIC_APPS_URL, timeout=SERVE_TIMEOUT_SECONDS)

        self.assertEqual(fetch_public_apps(), apps)
        mock_fetch.assert_called_once()

    @patch("portal_data.serve_apps.fetch_json")
    def test_failures_return_none_and_are_not_cached(self, mock_fetch: MagicMock):
        """Failures return none and are not cached."""
        for response in (None, {"error": "oops"}, {"data": "oops"}, ["not", "a", "dict"]):
            with self.subTest(response=response):
                mock_fetch.return_value = response
                self.assertIsNone(fetch_public_apps())
        self.assertEqual(mock_fetch.call_count, 4)

    @patch("portal_data.serve_apps.fetch_json")
    def test_empty_catalogue_is_cached(self, mock_fetch: MagicMock):
        """Empty catalogue is cached."""
        mock_fetch.return_value = {"data": []}
        self.assertEqual(fetch_public_apps(), [])
        self.assertEqual(fetch_public_apps(), [])
        mock_fetch.assert_called_once()
