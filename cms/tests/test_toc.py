"""Tests for the table of contents functionality."""

from unittest.mock import MagicMock, patch

from django.template import Context, Template
from django.test import TestCase

from cms.templatetags.toc import content_with_toc, get_toc_and_updated_content


class TestGetTocAndUpdatedContent(TestCase):
    """Unit tests for the get_toc_and_updated_content function."""

    def test_returns_empty_toc_when_no_headings_exist(self):
        """If there are no headings, the TOC should be empty and content unchanged."""
        result = get_toc_and_updated_content("<p>Hello world</p>")

        self.assertEqual(result["toc"], [])
        self.assertIn("<p>Hello world</p>", result["content"])

    def test_generates_toc_for_h2_and_h3_headings(self):
        """Headings should be extracted into the TOC with correct IDs and levels."""
        html = """
        <h2>Introduction</h2>
        <p>Content</p>
        <h3>Details</h3>
        """

        result = get_toc_and_updated_content(html)

        self.assertEqual(
            result["toc"],
            [
                {"id": "introduction", "text": "Introduction", "level": "h2"},
                {"id": "details", "text": "Details", "level": "h3"},
            ],
        )
        self.assertIn('id="introduction"', result["content"])
        self.assertIn('id="details"', result["content"])

    def test_preserves_existing_heading_id(self):
        """If a heading already has an ID, it should be used instead of generating a new one."""
        html = '<h2 id="custom-id">Introduction</h2>'

        result = get_toc_and_updated_content(html)

        self.assertEqual(
            result["toc"], [{"id": "custom-id", "text": "Introduction", "level": "h2"}]
        )
        self.assertIn('id="custom-id"', result["content"])

    def test_generates_unique_ids_for_duplicate_headings(self):
        """If multiple headings have the same text, generated IDs should be unique."""
        html = """
        <h2>Introduction</h2>
        <h2>Introduction</h2>
        <h3>Introduction</h3>
        """

        result = get_toc_and_updated_content(html)

        self.assertEqual(
            result["toc"],
            [
                {"id": "introduction", "text": "Introduction", "level": "h2"},
                {"id": "introduction-1", "text": "Introduction", "level": "h2"},
                {"id": "introduction-2", "text": "Introduction", "level": "h3"},
            ],
        )
        self.assertIn('id="introduction"', result["content"])
        self.assertIn('id="introduction-1"', result["content"])
        self.assertIn('id="introduction-2"', result["content"])

    def test_skips_headings_marked_to_ignore(self):
        """Headings with the data-ignore-in-toc attribute should not be included in the TOC."""
        html = """
        <h2>Visible</h2>
        <h2 data-ignore-in-toc>Hidden</h2>
        """

        result = get_toc_and_updated_content(html)

        self.assertEqual(result["toc"], [{"id": "visible", "text": "Visible", "level": "h2"}])
        self.assertNotIn("Hidden", [item["text"] for item in result["toc"]])

    def test_skips_empty_headings(self):
        """Headings with no text should be ignored in the TOC."""
        html = """
        <h2></h2>
        <h3>   </h3>
        <h2>Real Heading</h2>
        """

        result = get_toc_and_updated_content(html)

        self.assertEqual(
            result["toc"], [{"id": "real-heading", "text": "Real Heading", "level": "h2"}]
        )


class TestContentWithToc(TestCase):
    """Unit tests for the content_with_toc template tag."""

    def test_returns_content_unchanged_when_not_renderable(self):
        """If content cannot be rendered, it should be returned unchanged with an empty TOC."""
        content = object()

        result = content_with_toc(Context(), content)

        self.assertEqual(result["toc"], [])
        self.assertIs(result["content"], content)

    def test_streamfield_render_is_called_and_parsed(self):
        """The template tag should call render_as_block on the StreamField and parse the result."""
        mock_stream_field = MagicMock()
        mock_stream_field.render_as_block.return_value = """
            <h2>Intro</h2>
            <p>Body</p>
        """

        result = content_with_toc(Context(), mock_stream_field)

        mock_stream_field.render_as_block.assert_called_once()
        self.assertEqual(len(result["toc"]), 1)
        self.assertEqual(result["toc"][0]["text"], "Intro")
        self.assertEqual(result["toc"][0]["id"], "intro")

    def test_template_tag_renders_toc_and_content(self):
        """The content_with_toc tag should render the content and include the generated TOC."""

        class MockStreamField:
            def render_as_block(self, context: dict) -> str:
                html = """
                    <h2>Hello</h2>
                    <h3 data-ignore-in-toc>Hidden</h3>
                """
                return html

        template = Template(
            """
            {% load toc %}
            {% content_with_toc content %}
            """
        )

        rendered = template.render(Context({"content": MockStreamField()}))

        self.assertIn('id="hello"', rendered)
        self.assertNotIn('id="hidden"', rendered)

    @patch("cms.templatetags.toc.cache")
    def test_uses_cached_result_when_available(self, mock_cache: MagicMock):
        """If a cached TOC exists for the page, it should be used instead of rendering again."""
        cached_result = {
            "toc": [{"text": "Cached", "id": "cached", "level": "h2"}],
            "content": '<h2 id="cached">Cached</h2>',
        }
        mock_cache.get.return_value = cached_result

        page = MagicMock()
        page.id = 123
        page.last_published_at.strftime.return_value = "20260604074153"

        streamfield = MagicMock()

        result = content_with_toc(Context({"page": page}), streamfield)

        self.assertEqual(result, cached_result)
        streamfield.render_as_block.assert_not_called()
        mock_cache.get.assert_called_once()
        cache_key = mock_cache.get.call_args[0][0]
        self.assertEqual(cache_key, "toc:123:20260604074153")

    @patch("cms.templatetags.toc.cache")
    def test_source_file_hash_changes_cache_key(self, mock_cache: MagicMock):
        """A new Dashboard Data file must miss TOC HTML cache without republishing."""
        mock_cache.get.return_value = None
        page = MagicMock()
        page.id = 123
        page.last_published_at.strftime.return_value = "20260604074153"
        streamfield = MagicMock()
        streamfield.render_as_block.return_value = "<h2>Intro</h2>"

        content_with_toc(
            Context({"page": page, "source_file_hash": "abc"}),
            streamfield,
        )
        content_with_toc(
            Context({"page": page, "source_file_hash": "def"}),
            streamfield,
        )

        keys = [call.args[0] for call in mock_cache.get.call_args_list]
        self.assertEqual(keys[0], "toc:123:20260604074153:abc")
        self.assertEqual(keys[1], "toc:123:20260604074153:def")
        self.assertEqual(streamfield.render_as_block.call_count, 2)

    @patch("cms.templatetags.toc.cache")
    def test_pages_without_source_file_hash_keep_original_cache_key(
        self, mock_cache: MagicMock
    ):
        """Topic and basic pages must keep toc:{id}:{published} (no extra segment)."""
        mock_cache.get.return_value = None
        page = MagicMock()
        page.id = 123
        page.last_published_at.strftime.return_value = "20260604074153"
        streamfield = MagicMock()
        streamfield.render_as_block.return_value = "<h2>Intro</h2>"

        content_with_toc(Context({"page": page}), streamfield)

        cache_key = mock_cache.get.call_args[0][0]
        self.assertEqual(cache_key, "toc:123:20260604074153")

    @patch("cms.templatetags.toc.cache")
    def test_empty_source_file_hash_keeps_original_cache_key(self, mock_cache: MagicMock):
        """Historic JSON-only rows set source_file_hash to '' and must not change the key."""
        mock_cache.get.return_value = None
        page = MagicMock()
        page.id = 123
        page.last_published_at.strftime.return_value = "20260604074153"
        streamfield = MagicMock()
        streamfield.render_as_block.return_value = "<h2>Intro</h2>"

        content_with_toc(
            Context({"page": page, "source_file_hash": ""}),
            streamfield,
        )

        cache_key = mock_cache.get.call_args[0][0]
        self.assertEqual(cache_key, "toc:123:20260604074153")

    @patch("cms.templatetags.toc.cache")
    def test_historic_dashboard_context_does_not_change_cache_key_shape(
        self, mock_cache: MagicMock
    ):
        """data_status and figures are unused; only a non-empty source_file_hash is appended."""
        mock_cache.get.return_value = None
        page = MagicMock()
        page.id = 42
        page.last_published_at.strftime.return_value = "20200101000000"
        streamfield = MagicMock()
        streamfield.render_as_block.return_value = "<h2>Intro</h2>"

        historic_context = Context(
            {
                "page": page,
                "figures": {"old_chart": {"data": [], "layout": {}}},
                "data_status": "historic",
                "source_file_hash": "abc123",
            }
        )
        content_with_toc(historic_context, streamfield)

        cache_key = mock_cache.get.call_args[0][0]
        self.assertEqual(cache_key, "toc:42:20200101000000:abc123")

    @patch("cms.templatetags.toc.cache")
    def test_cache_miss_renders_and_sets_cache(self, mock_cache: MagicMock):
        """If no cached TOC exists, it should render the content and set the cache."""
        mock_cache.get.return_value = None

        page = MagicMock()
        page.id = 123
        page.last_published_at.strftime.return_value = "20260604074153"

        streamfield = MagicMock()
        streamfield.render_as_block.return_value = "<h2>Intro</h2>"

        result = content_with_toc(Context({"page": page}), streamfield)

        streamfield.render_as_block.assert_called_once()
        mock_cache.set.assert_called_once()

        args, kwargs = mock_cache.set.call_args
        self.assertEqual(args[1], result)

    @patch("cms.templatetags.toc.cache")
    def test_preview_mode_skips_cache(self, mock_cache: MagicMock):
        """In preview mode, the cache should be bypassed and content should be rendered fresh."""
        request = MagicMock()
        request.is_preview = True

        page = MagicMock()
        page.id = 123
        page.last_published_at.strftime.return_value = "20260604074153"

        streamfield = MagicMock()
        streamfield.render_as_block.return_value = "<h2>Intro</h2>"

        result = content_with_toc(Context({"page": page, "request": request}), streamfield)

        mock_cache.get.assert_not_called()
        mock_cache.set.assert_not_called()
        streamfield.render_as_block.assert_called_once()

        self.assertEqual(result["toc"], [{"id": "intro", "text": "Intro", "level": "h2"}])
        self.assertIn('id="intro"', result["content"])

    @patch("cms.templatetags.toc.cache")
    def test_no_page_skips_cache(self, mock_cache: MagicMock):
        """If no page is in context, caching should be skipped and content should be rendered."""
        streamfield = MagicMock()
        streamfield.render_as_block.return_value = "<h2>Intro</h2>"

        content_with_toc(Context(), streamfield)

        mock_cache.get.assert_not_called()
        mock_cache.set.assert_not_called()
