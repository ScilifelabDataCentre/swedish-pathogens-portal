"""Test cases for Highlights and Editorials services."""

from unittest.mock import MagicMock

from django.test import SimpleTestCase

from cms.services.highlights_and_editorials import get_related_articles


class TestGetRelatedArticles(SimpleTestCase):
    """Tests for the get_related_articles service function."""

    def create_mock_article(
        self,
        *,
        article_id: int,
        keywords: str,
        article_type: str = "editorial",
        title: str = "Article",
    ) -> MagicMock:
        """Create a mock article with specified attributes."""
        article = MagicMock()
        article.id = article_id
        article.title = title
        article.article_type = article_type
        article.keywords = keywords
        article.keyword_list = [
            keyword.strip().lower() for keyword in keywords.split(",") if keyword.strip()
        ]

        return article

    def test_returns_empty_queryset_when_article_has_no_keywords(self) -> None:
        """Test that an empty queryset is returned when the article has no keywords."""
        article_model = MagicMock()

        article = MagicMock()
        article.specific.__class__ = article_model
        article.keyword_list = []

        empty_queryset = MagicMock()
        article_model.objects.none.return_value = empty_queryset

        result = get_related_articles(article)

        self.assertEqual(result, empty_queryset)
        article_model.objects.none.assert_called_once()

    def test_returns_empty_queryset_when_no_candidate_articles_exist(self) -> None:
        """Test that an empty queryset is returned when there are no candidate articles."""
        article_model = MagicMock()

        article = self.create_mock_article(
            article_id=1,
            keywords="covid-19, infectious diseases",
        )
        article.specific.__class__ = article_model

        queryset = MagicMock()
        queryset.exists.return_value = False

        (
            article_model.objects.live.return_value.public.return_value.filter.return_value.exclude.return_value.order_by.return_value
        ) = queryset

        empty_queryset = MagicMock()
        article_model.objects.none.return_value = empty_queryset

        result = get_related_articles(article)

        self.assertEqual(result, empty_queryset)
        queryset.exists.assert_called_once()

    def test_returns_related_articles_sorted_by_similarity(self) -> None:
        """Test that related articles are returned sorted by similarity score."""
        article_model = MagicMock()

        main_article = self.create_mock_article(
            article_id=1, keywords="covid-19, infectious diseases, vaccines"
        )
        main_article.specific.__class__ = article_model

        related_high = self.create_mock_article(
            article_id=2, keywords="covid-19, infectious diseases", title="High Similarity"
        )

        related_low = self.create_mock_article(
            article_id=3, keywords="covid-19", title="Low Similarity"
        )

        unrelated = self.create_mock_article(
            article_id=4, keywords="antibiotics", title="Unrelated"
        )

        queryset = MagicMock()
        queryset.exists.return_value = True
        queryset.iterator.return_value = [related_low, unrelated, related_high]

        (
            article_model.objects.live.return_value.public.return_value.filter.return_value.exclude.return_value.order_by.return_value
        ) = queryset

        result = get_related_articles(main_article, limit=2, threshold=0.1)

        self.assertEqual(result, [related_high, related_low])

    def test_excludes_articles_below_threshold(self) -> None:
        """Test that articles with similarity below the threshold are excluded."""
        article_model = MagicMock()

        main_article = self.create_mock_article(
            article_id=1, keywords="covid-19, infectious diseases, vaccines"
        )
        main_article.specific.__class__ = article_model

        weak_match = self.create_mock_article(article_id=2, keywords="covid-19, antibiotics")

        queryset = MagicMock()
        queryset.exists.return_value = True
        queryset.iterator.return_value = [weak_match]

        (
            article_model.objects.live.return_value.public.return_value.filter.return_value.exclude.return_value.order_by.return_value
        ) = queryset

        result = get_related_articles(main_article, threshold=0.9)

        self.assertEqual(result, [])

    def test_skips_articles_without_keywords(self) -> None:
        """Test that articles without keywords are skipped in similarity calculations."""
        article_model = MagicMock()

        main_article = self.create_mock_article(
            article_id=1, keywords="covid-19, infectious diseases"
        )
        main_article.specific.__class__ = article_model

        no_keywords_article = MagicMock()
        no_keywords_article.keywords = ""
        no_keywords_article.keyword_list = []

        queryset = MagicMock()
        queryset.exists.return_value = True
        queryset.iterator.return_value = [no_keywords_article]

        (
            article_model.objects.live.return_value.public.return_value.filter.return_value.exclude.return_value.order_by.return_value
        ) = queryset

        result = get_related_articles(main_article)

        self.assertEqual(result, [])

    def test_limits_number_of_results(self) -> None:
        """Test that the number of related articles returned does not exceed the specified limit."""
        article_model = MagicMock()

        main_article = self.create_mock_article(
            article_id=1,
            keywords="covid-19, infectious diseases, vaccines",
        )
        main_article.specific.__class__ = article_model

        article_1 = self.create_mock_article(
            article_id=2, keywords="covid-19, antibiotics, vaccines", title="A1"
        )

        article_2 = self.create_mock_article(
            article_id=3, keywords="covid-19, bacteria, vaccines", title="A2"
        )

        article_3 = self.create_mock_article(article_id=4, keywords="covid-19", title="A3")

        queryset = MagicMock()
        queryset.exists.return_value = True
        queryset.iterator.return_value = [article_1, article_2, article_3]

        (
            article_model.objects.live.return_value.public.return_value.filter.return_value.exclude.return_value.order_by.return_value
        ) = queryset

        result = get_related_articles(main_article, limit=2)

        self.assertEqual(len(result), 2)
        self.assertEqual(result, [article_1, article_2])
