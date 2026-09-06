"""Tests for the validation utility functions."""

from django.http import Http404, QueryDict
from django.test import SimpleTestCase

from cms.services.validators import SEARCH_MAX_LENGTH, validate_filters


class TestValidateFilters(SimpleTestCase):
    """Tests for the validate filters utility function."""

    def test_returns_empty_dict_for_empty_querydict(self):
        """Test that an empty QueryDict returns an empty dictionary."""
        self.assertEqual(validate_filters(QueryDict("")), {})

    def test_raises_error_for_unsupported_expected_keys(self):
        """Test that providing unsupported expected_keys raises a ValueError."""
        with self.assertRaisesMessage(ValueError, "Unsupported expected_keys"):
            validate_filters(QueryDict(""), expected_keys={"search", "foo"})

    def test_normalizes_search_value(self):
        """Test that the search value is stripped and lowercased."""
        querydict = QueryDict("search=  HeLLo World  ")

        result = validate_filters(querydict)

        self.assertEqual(result, {"search": "hello world"})

    def test_rejects_search_longer_than_max_length(self):
        """Test that a search query longer than the maximum length raises an Http404 error."""
        querydict = QueryDict(f"search={'x' * (SEARCH_MAX_LENGTH + 1)}")

        with self.assertRaisesMessage(Http404, "Search query too long"):
            validate_filters(querydict)

    def test_supports_custom_search_max_length(self):
        """Test that a custom search_max_length parameter is respected."""
        querydict = QueryDict("search=abcdef")

        with self.assertRaisesMessage(Http404, "Search query too long"):
            validate_filters(querydict, search_max_length=5)

    def test_validates_topic_and_type_values(self):
        """Test that topic and type values are validated against allowed lists."""
        querydict = QueryDict("type=news&type=feature&topic=technology&topic=science")

        result = validate_filters(
            querydict, valid_types=["News", "Feature"], valid_topics=["Technology", "Science"]
        )

        self.assertEqual(result, {"type": ["news", "feature"], "topic": ["technology", "science"]})

    def test_rejects_unexpected_query_parameter(self):
        """Test that an unexpected query parameter raises an Http404 error."""
        querydict = QueryDict("foo=bar")

        with self.assertRaisesMessage(Http404, "Invalid query parameter: foo"):
            validate_filters(querydict)

    def test_rejects_too_many_type_values(self):
        """Test that too many type values raises an Http404 error."""
        querydict = QueryDict("type=news&type=feature&type=extra")

        with self.assertRaisesMessage(Http404, "Too many type values selected"):
            validate_filters(querydict, valid_types=["News", "Feature"])

    def test_rejects_invalid_type_value(self):
        """Test that an invalid type value raises an Http404 error."""
        querydict = QueryDict("type=invalid")

        with self.assertRaisesMessage(Http404, "Invalid type value"):
            validate_filters(querydict, valid_types=["News", "Feature"])

    def test_rejects_too_many_topic_values(self):
        """Test that too many topic values raises an Http404 error."""
        querydict = QueryDict("topic=technology&topic=science&topic=extra")

        with self.assertRaisesMessage(Http404, "Too many topic values selected"):
            validate_filters(querydict, valid_topics=["Technology", "Science"])

    def test_rejects_invalid_topic_value(self):
        """Test that an invalid topic value raises an Http404 error."""
        querydict = QueryDict("topic=invalid")

        with self.assertRaisesMessage(Http404, "Invalid topic value"):
            validate_filters(querydict, valid_topics=["Technology", "Science"])

    def test_slugifies_valid_choices_before_comparison(self):
        """Test that valid choices are slugified before comparison for type filters."""
        querydict = QueryDict("type=long-form&topic=data-science")

        result = validate_filters(
            querydict, valid_types=["Long Form"], valid_topics=["Data Science"]
        )

        self.assertEqual(result, {"type": ["long-form"], "topic": ["data-science"]})
