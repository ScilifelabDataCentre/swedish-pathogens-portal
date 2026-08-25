"""Tests for the Publications page's service layer."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase

from cms.services.publications import (
    Pathogen,
    Publication,
    _build_abstract_query,
    fetch_pathogen_publications,
    resolve_active_pathogen,
)


def mock_europe_pmc_json(results: list[dict] | None = None) -> dict:
    """Build a fake Europe PMC search response body to mock fetch_json's return value."""
    return {"resultList": {"result": results or []}}


class TestPublicationFromEuropePMCResult(SimpleTestCase):
    """Tests for Publication.from_europe_pmc_result parsing raw API records."""

    def test_full_record_is_parsed(self):
        """Test a complete record is parsed into matching Publication fields."""
        result = {
            "title": "A study of Influenza",
            "authorString": "Doe J, Smith A.",
            "journalInfo": {"journal": {"title": "Journal of Testing"}},
            "doi": "10.1234/abcd",
        }
        publication = Publication.from_europe_pmc_result(result)
        self.assertEqual(
            publication,
            Publication(
                title="A study of Influenza",
                authors="Doe J, Smith A.",
                journal="Journal of Testing",
                doi="10.1234/abcd",
                url="https://doi.org/10.1234/abcd",
            ),
        )

    def test_missing_fields_get_placeholder_defaults(self):
        """Test a record missing everything but doi falls back to placeholder text."""
        publication = Publication.from_europe_pmc_result({})
        self.assertEqual(publication.title, "title unknown")
        self.assertEqual(publication.authors, "authors unknown")
        self.assertEqual(publication.journal, "journal unknown")
        self.assertEqual(publication.doi, "doi unknown")
        self.assertIsNone(publication.url)

    def test_missing_doi_falls_back_to_full_text_url(self):
        """Test a record with no doi but a full text URL uses that as the url."""
        result = {
            "fullTextUrlList": {"fullTextUrl": [{"url": "https://example.test/paper.pdf"}]},
        }
        publication = Publication.from_europe_pmc_result(result)
        self.assertEqual(publication.doi, "doi unknown")
        self.assertEqual(publication.url, "https://example.test/paper.pdf")


class TestBuildAbstractQuery(SimpleTestCase):
    """Tests for _build_abstract_query."""

    def test_single_search_term(self):
        """Test a pathogen with one search term."""
        pathogen = Pathogen(name="Influenza", search_terms=["Influenza"])
        self.assertEqual(_build_abstract_query(pathogen), 'ABSTRACT:("Influenza")')

    def test_multiple_search_terms_are_or_joined(self):
        """Test multiple search terms are OR-joined inside a single closed group."""
        pathogen = Pathogen(
            name="AMR",
            search_terms=["antibiotic resistance", "AMR", "antimicrobial resistance"],
        )
        expected_query = 'ABSTRACT:("antibiotic resistance" OR "AMR" OR "antimicrobial resistance")'
        self.assertEqual(_build_abstract_query(pathogen), expected_query)


class TestResolveActivePathogen(SimpleTestCase):
    """Tests for resolve_active_pathogen's GET-param validation against page.pathogens."""

    def setUp(self):
        """Set up a request factory and some configured pathogens."""
        self.factory = RequestFactory()
        self.pathogens = [
            Pathogen(name="Influenza", search_terms=["Influenza"]),
            Pathogen(name="RSV", search_terms=["RSV"]),
            Pathogen(name="AMR", search_terms=["antibiotic resistance", "AMR"]),
        ]
        self.real_page = SimpleNamespace(pathogens=self.pathogens)
        self.empty_page = SimpleNamespace(pathogens=[])

    def test_no_pathogen_param_returns_first_configured(self):
        """Test the initial page load (no pathogen param) defaults to the first pathogen."""
        request = self.factory.get("/publications/")
        selected_pathogen = resolve_active_pathogen(self.real_page, request)
        self.assertEqual(selected_pathogen, self.pathogens[0])

    def test_matching_pathogen_name_is_returned(self):
        """Test a pathogen param matching a configured name returns that pathogen."""
        request = self.factory.get("/publications/", {"pathogen": "RSV"})
        self.assertEqual(resolve_active_pathogen(self.real_page, request), self.pathogens[1])

    def test_unrecognized_pathogen_name_returns_none(self):
        """Test a pathogen param that matches nothing configured returns None."""
        request = self.factory.get("/publications/", {"pathogen": "Nonexistent"})
        self.assertIsNone(resolve_active_pathogen(self.real_page, request))

    def test_no_pathogens_configured_returns_none(self):
        """Test a page with no pathogens configured returns None."""
        request = self.factory.get("/publications/")
        self.assertIsNone(resolve_active_pathogen(self.empty_page, request))


class TestFetchPathogenPublications(SimpleTestCase):
    """Tests for fetch_pathogen_publications against a mocked fetch_json."""

    results = [
        {
            "title": "A study of Influenza",
            "authorString": "Doe J.",
            "journalInfo": {"journal": {"title": "Journal of Testing"}},
            "doi": "10.1234/abcd",
        },
        {
            "title": "Another Influenza study",
            "authorString": "Smith A.",
            "journalInfo": {"journal": {"title": "Journal of More Testing"}},
            "doi": "10.5678/efgh",
        },
    ]

    def setUp(self):
        """Use a fresh pathogen and clear the cache so each test starts uncached."""
        cache.clear()
        self.pathogen = Pathogen(name="Influenza", search_terms=["Influenza"])

    @patch("cms.services.publications.fetch_json")
    def test_successful_response_returns_parsed_publications(self, mock_fetch_json: MagicMock):
        """Test a successful response is parsed into a list of Publication objects."""
        mock_fetch_json.return_value = mock_europe_pmc_json(results=self.results)
        publications = fetch_pathogen_publications(self.pathogen)

        self.assertEqual(len(publications), 2)
        self.assertEqual(publications[0].title, self.results[0]["title"])
        self.assertEqual(publications[1].title, self.results[1]["title"])
        self.assertEqual(publications[0].url, "https://doi.org/10.1234/abcd")
        self.assertEqual(publications[1].url, "https://doi.org/10.5678/efgh")

    @patch("cms.services.publications.fetch_json")
    def test_successful_response_is_cached(self, mock_fetch_json: MagicMock):
        """Test a second call with the same pathogen is cached."""
        mock_fetch_json.return_value = mock_europe_pmc_json(results=self.results)

        first = fetch_pathogen_publications(self.pathogen)
        second = fetch_pathogen_publications(self.pathogen)

        self.assertEqual(first, second)
        mock_fetch_json.assert_called_once()

    @patch("cms.services.publications.fetch_json")
    def test_no_results_is_not_cached(self, mock_fetch_json: MagicMock):
        """Test an empty result list returns [] and isn't cached."""
        mock_fetch_json.return_value = mock_europe_pmc_json(results=[])

        first = fetch_pathogen_publications(self.pathogen)
        second = fetch_pathogen_publications(self.pathogen)

        self.assertEqual(first, [])
        self.assertEqual(second, [])
        self.assertEqual(mock_fetch_json.call_count, 2)

    @patch("cms.services.publications.fetch_json")
    def test_failed_fetch_returns_empty_list(self, mock_fetch_json: MagicMock):
        """Test fetch_json returning None (a fetch/parse failure) returns [] rather than raising."""
        mock_fetch_json.return_value = None
        self.assertEqual(fetch_pathogen_publications(self.pathogen), [])

    @patch("cms.services.publications.fetch_json")
    def test_unparseable_result_is_skipped(self, mock_fetch_json: MagicMock):
        """Test one bad result entry is skipped rather than failing the whole batch."""
        results = ["not-a-dict"] + self.results
        mock_fetch_json.return_value = mock_europe_pmc_json(results=results)
        publications = fetch_pathogen_publications(self.pathogen)
        self.assertEqual(len(publications), 2)
        self.assertEqual(publications[0].title, self.results[0]["title"])
        self.assertEqual(publications[1].title, self.results[1]["title"])
