"""Tests for the portal data summary helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase

from portal_data.summary import build_portal_data_summary, filter_by_country, get_summary_counts

ITEMS = [
    {"id": "MTBLS1", "country": "Sweden", "technology": "mass spectrometry", "year": "2023"},
    {"id": "MTBLS2", "country": "sweden ", "technology": "mass spectrometry", "year": "2024"},
    {"id": "MTBLS3", "country": "Norway", "technology": "NMR spectroscopy", "year": "2024"},
    {"id": "MTBLS4", "country": "", "technology": "NMR spectroscopy", "year": "2022"},
    {"id": "MTBLS5", "country": "", "technology": "mass spectrometry", "year": "2024"},
]


class FilterByCountryTests(SimpleTestCase):
    """Tests for ``filter_by_country``."""

    def test_blank_country_returns_all_items(self) -> None:
        """A blank country means no filtering."""
        self.assertEqual(filter_by_country(ITEMS, ""), ITEMS)
        self.assertEqual(filter_by_country(ITEMS, "  "), ITEMS)

    def test_country_match_is_case_and_whitespace_insensitive(self) -> None:
        """Only items from the given country are kept, ignoring case and whitespace."""
        result = filter_by_country(ITEMS, "SWEDEN")
        self.assertEqual([it["id"] for it in result], ["MTBLS1", "MTBLS2"])


@patch("portal_data.summary.load_all_items", return_value=ITEMS)
class GetSummaryCountsTests(SimpleTestCase):
    """Tests for ``get_summary_counts``."""

    def setUp(self) -> None:
        """Start each test with an empty cache."""
        cache.clear()

    def test_counts_total_and_buckets(self, mock_load: MagicMock) -> None:
        """Count all items and group them by the requested facet."""
        counts = get_summary_counts(datatype="metabolomics", facet="technology")

        self.assertEqual(counts["total"], 5)
        self.assertEqual(
            counts["buckets"],
            [
                {"value": "NMR spectroscopy", "count": 2},
                {"value": "mass spectrometry", "count": 3},
            ],
        )

    def test_counts_respect_country_filter(self, mock_load: MagicMock) -> None:
        """Only items from the given country are counted."""
        counts = get_summary_counts(datatype="metabolomics", facet="technology", country="Sweden")

        self.assertEqual(counts["total"], 2)
        self.assertEqual(counts["buckets"], [{"value": "mass spectrometry", "count": 2}])

    def test_counts_are_cached(self, mock_load: MagicMock) -> None:
        """A second call with the same arguments doesn't reload the items."""
        get_summary_counts(datatype="metabolomics", facet="year")
        get_summary_counts(datatype="metabolomics", facet="year")

        mock_load.assert_called_once_with("metabolomics")


@patch("portal_data.summary.load_all_items", return_value=ITEMS)
class BuildPortalDataSummaryTests(SimpleTestCase):
    """Tests for ``build_portal_data_summary``."""

    def setUp(self) -> None:
        """Start each test with an empty cache."""
        cache.clear()

    def test_builds_section_with_filtered_listing_links(self, mock_load: MagicMock) -> None:
        """Rows are sorted by count and link to the listing filtered on that value."""
        section = build_portal_data_summary(
            datatype="metabolomics", listing_url="/portal-data/", facet="technology"
        )

        self.assertEqual(section["title"], "Metabolomics")
        self.assertEqual(section["total_count"], 5)
        self.assertEqual(section["total_url"], "/portal-data/")
        self.assertTrue(section["internal"])
        self.assertEqual(
            [(r["display_label"], r["count"], r["url"]) for r in section["rows"]],
            [
                ("mass spectrometry", 3, "/portal-data/?technology=mass+spectrometry"),
                ("NMR spectroscopy", 2, "/portal-data/?technology=NMR+spectroscopy"),
            ],
        )

    def test_year_rows_keep_most_recent_first(self, mock_load: MagicMock) -> None:
        """Year rows are ordered by year, not by count."""
        section = build_portal_data_summary(
            datatype="metabolomics", listing_url="/portal-data/", facet="year"
        )

        self.assertEqual([r["label"] for r in section["rows"]], ["2024", "2023", "2022"])

    def test_title_and_max_rows_are_applied(self, mock_load: MagicMock) -> None:
        """A custom title is used and rows are capped at ``max_rows``."""
        section = build_portal_data_summary(
            datatype="metabolomics",
            listing_url="/portal-data/",
            facet="year",
            title="Metabolomics studies",
            max_rows=1,
        )

        self.assertEqual(section["title"], "Metabolomics studies")
        self.assertEqual(len(section["rows"]), 1)

    def test_unknown_datatype_returns_none(self, mock_load: MagicMock) -> None:
        """An unsupported datatype gives no section."""
        self.assertIsNone(
            build_portal_data_summary(datatype="proteomics", listing_url="/x/", facet="year")
        )
