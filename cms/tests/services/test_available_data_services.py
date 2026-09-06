"""Tests for the Available Data page's service layer."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase

from cms.services.available_data import (
    build_page_context,
    fetch_ebi_hit_count,
    fetch_priority_pathogen_taxon_ids,
)


class TestFetchPriorityPathogenTaxonIds(SimpleTestCase):
    """Tests for fetch_priority_pathogen_taxon_ids against a mocked fetch_json."""

    def setUp(self):
        """Clear the cache so each test starts uncached."""
        cache.clear()

    @patch("cms.services.available_data.fetch_json")
    def test_successful_response_returns_taxon_ids(self, mock_fetch_json: MagicMock):
        """Test entries with a TAXONOMY field are parsed into a list of taxon ids."""
        mock_fetch_json.return_value = {
            "entries": [
                {"fields": {"TAXONOMY": ["11320"]}},
                {"fields": {"TAXONOMY": ["694009"]}},
            ]
        }
        self.assertEqual(fetch_priority_pathogen_taxon_ids(), ["11320", "694009"])

    @patch("cms.services.available_data.fetch_json")
    def test_entries_missing_taxonomy_are_skipped(self, mock_fetch_json: MagicMock):
        """Test entries without a TAXONOMY field don't produce a taxon id."""
        mock_fetch_json.return_value = {
            "entries": [{"fields": {"TAXONOMY": ["11320"]}}, {"fields": {}}]
        }
        self.assertEqual(fetch_priority_pathogen_taxon_ids(), ["11320"])

    @patch("cms.services.available_data.fetch_json")
    def test_successful_response_is_cached(self, mock_fetch_json: MagicMock):
        """Test a second call doesn't hit fetch_json again."""
        mock_fetch_json.return_value = {"entries": [{"fields": {"TAXONOMY": ["11320"]}}]}

        first = fetch_priority_pathogen_taxon_ids()
        second = fetch_priority_pathogen_taxon_ids()

        self.assertEqual(first, second)
        mock_fetch_json.assert_called_once()

    @patch("cms.services.available_data.fetch_json")
    def test_no_entries_falls_back_to_default_and_is_not_cached(self, mock_fetch_json: MagicMock):
        """Test a response with no usable entries falls back ["0"] and is not cached."""
        mock_fetch_json.return_value = {"entries": []}

        first = fetch_priority_pathogen_taxon_ids()
        second = fetch_priority_pathogen_taxon_ids()

        self.assertEqual(first, ["0"])
        self.assertEqual(second, ["0"])
        self.assertEqual(mock_fetch_json.call_count, 2)

    @patch("cms.services.available_data.fetch_json")
    def test_failed_fetch_falls_back_to_default(self, mock_fetch_json: MagicMock):
        """Test fetch_json returning None (any fetch/parse failure) falls back to the default."""
        mock_fetch_json.return_value = None
        first = fetch_priority_pathogen_taxon_ids()
        second = fetch_priority_pathogen_taxon_ids()

        self.assertEqual(first, ["0"])
        self.assertEqual(second, ["0"])
        self.assertEqual(mock_fetch_json.call_count, 2)


class TestFetchEbiHitCount(SimpleTestCase):
    """Tests for fetch_ebi_hit_count against a mocked fetch_json."""

    def setUp(self):
        """Clear the cache so each test starts uncached."""
        cache.clear()

    @patch("cms.services.available_data.fetch_json")
    def test_successful_response_returns_hit_count(self, mock_fetch_json: MagicMock):
        """Test a successful response returns the parsed hit count."""
        mock_fetch_json.return_value = {"hitCount": 12803}
        self.assertEqual(fetch_ebi_hit_count("sra-experiment", "(tag:pathogen)"), 12803)

    @patch("cms.services.available_data.fetch_json")
    def test_successful_response_is_cached(self, mock_fetch_json: MagicMock):
        """Test a second call with the same index/query doesn't hit fetch_json again."""
        mock_fetch_json.return_value = {"hitCount": 12803}

        first = fetch_ebi_hit_count("sra-experiment", "(tag:pathogen)")
        second = fetch_ebi_hit_count("sra-experiment", "(tag:pathogen)")

        self.assertEqual(first, second)
        mock_fetch_json.assert_called_once()

    @patch("cms.services.available_data.fetch_json")
    def test_different_queries_are_cached_separately(self, mock_fetch_json: MagicMock):
        """Test different queries against the same index don't share a cache entry."""
        mock_fetch_json.return_value = {"hitCount": 1}

        fetch_ebi_hit_count("sra-experiment", "(tag:pathogen)")
        fetch_ebi_hit_count("sra-experiment", "(tag:covid19)")

        self.assertEqual(mock_fetch_json.call_count, 2)

    @patch("cms.services.available_data.fetch_json")
    def test_failed_fetch_returns_zero(self, mock_fetch_json: MagicMock):
        """Test fetch_json returning None (a fetch/parse failure) returns 0 rather than raising."""
        mock_fetch_json.return_value = None
        self.assertEqual(fetch_ebi_hit_count("sra-experiment", "(tag:pathogen)"), 0)


class TestBuildPageContext(SimpleTestCase):
    """Tests for build_page_context assembling the Outbreaks/Pathogen Sequences sections."""

    @patch("cms.services.available_data.fetch_ebi_hit_count", return_value=5)
    @patch("cms.services.available_data.fetch_priority_pathogen_taxon_ids", return_value=["9606"])
    def test_context_has_both_sections(self, mock_taxon_ids: MagicMock, mock_hit_count: MagicMock):
        """Test the context has exactly the outbreaks and pathogens_sequences keys."""
        context = build_page_context()
        self.assertEqual(set(context), {"outbreaks", "pathogens_sequences"})

    @patch("cms.services.available_data.fetch_ebi_hit_count", return_value=5)
    @patch("cms.services.available_data.fetch_priority_pathogen_taxon_ids", return_value=["9606"])
    def test_outbreaks_section_has_six_rows_summing_to_total(
        self, mock_taxon_ids: MagicMock, mock_hit_count: MagicMock
    ):
        """Test "Outbreaks" has all six subcategories, including priority pathogens."""
        outbreaks = build_page_context()["outbreaks"]
        self.assertEqual(outbreaks["title"], "Outbreaks")
        self.assertEqual(
            [row["label"] for row in outbreaks["rows"]],
            ["priority pathogens", "sequences", "analysis", "raw reads", "samples", "assembly"],
        )
        self.assertEqual(outbreaks["total_count"], 5 * 6)

    @patch("cms.services.available_data.fetch_ebi_hit_count", return_value=5)
    @patch("cms.services.available_data.fetch_priority_pathogen_taxon_ids", return_value=["9606"])
    def test_pathogens_sequences_section_has_five_rows_summing_to_total(
        self, mock_taxon_ids: MagicMock, mock_hit_count: MagicMock
    ):
        """Test "Pathogen Sequences" has all five subcategories, including samples."""
        pathogens_sequences = build_page_context()["pathogens_sequences"]
        self.assertEqual(pathogens_sequences["title"], "Pathogen Sequences")
        self.assertEqual(
            [row["label"] for row in pathogens_sequences["rows"]],
            ["sequence", "analysis", "raw reads", "samples", "assembly"],
        )
        self.assertEqual(pathogens_sequences["total_count"], 5 * 5)

    @patch("cms.services.available_data.fetch_ebi_hit_count", return_value=5)
    @patch("cms.services.available_data.fetch_priority_pathogen_taxon_ids", return_value=["0"])
    def test_no_taxon_ids_still_builds_a_valid_context(
        self, mock_taxon_ids: MagicMock, mock_hit_count: MagicMock
    ):
        """Test an upstream fetch failure which returns ["0"] doesn't break the page."""
        context = build_page_context()
        self.assertEqual(context["outbreaks"]["total_count"], 5 * 6)
