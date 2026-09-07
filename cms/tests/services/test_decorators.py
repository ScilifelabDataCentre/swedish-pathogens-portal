"""Test decorator utilities."""

from unittest.mock import MagicMock, patch

from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory, SimpleTestCase

from cms.services.decorators import htmx_request_with_url_update


class DummyPage:
    """A dummy page class to test the htmx_request_with_url_update decorator."""

    def __init__(self) -> None:
        """Initialize the dummy page with a default HTMX template."""
        self.htmx_template = "test/template.html"

    def get_context(self, request: HttpRequest) -> dict:
        """Return a simple context for testing."""
        return {"foo": "bar"}

    @htmx_request_with_url_update()
    def serve(self, request: HttpRequest) -> HttpResponse:
        """Serve method to be decorated, returning a simple response."""
        return HttpResponse("original response")


class TestHtmxDecorator(SimpleTestCase):
    """Test cases for the htmx_request_with_url_update decorator."""

    def setUp(self):
        """Set up the test case with a request factory."""
        self.factory = RequestFactory()

    def test_non_htmx_returns_original_response(self):
        """Test that non-HTMX requests return the original response."""
        page = DummyPage()
        request = self.factory.get("/test/")
        request.htmx = False

        response = page.serve(request)

        self.assertEqual(response.content, b"original response")

    @patch("cms.services.decorators.render")
    def test_htmx_renders_template_and_sets_header(self, mock_render: MagicMock):
        """Test HTMX requests render the specified template and set the HX-Replace-Url header."""
        page = DummyPage()
        request = self.factory.get("/test/")
        request.htmx = True

        mock_render.return_value = HttpResponse("partial response")

        response = page.serve(request)

        self.assertEqual(response.content, b"partial response")
        self.assertIn("HX-Replace-Url", response)
        mock_render.assert_called_once()

    def test_htmx_removes_search_from_url(self):
        """Test that the decorator removes the 'search' parameter from the URL for HTMX requests."""
        page = DummyPage()
        request = self.factory.get("/test/?search=abc&type=article")
        request.htmx = True

        with patch(
            "cms.services.decorators.render", return_value=HttpResponse("ok")
        ) as mock_render:
            response = page.serve(request)

        called_request = mock_render.call_args[0][0]
        self.assertEqual(called_request.path, "/test/")

        # header check
        self.assertIn("type=article", response["HX-Replace-Url"])
        self.assertNotIn("search=", response["HX-Replace-Url"])

    @patch("cms.services.decorators.render")
    def test_htmx_uses_template_attribute(self, mock_render: MagicMock):
        """Test that the decorator uses the specified template attribute for rendering."""

        page = DummyPage()
        page.htmx_template = "custom/template.html"
        request = self.factory.get("/x/")
        request.htmx = True

        mock_render.return_value = HttpResponse("ok")

        page.serve(request)

        args, _ = mock_render.call_args
        self.assertEqual(args[1], "custom/template.html")

    @patch("cms.services.decorators.render")
    def test_htmx_calls_get_context(self, mock_render: MagicMock):
        """Test that the decorator calls the get_context method for rendering."""
        page = DummyPage()
        request = self.factory.get("/x/")
        request.htmx = True

        mock_render.return_value = HttpResponse("ok")

        page.serve(request)

        args, _ = mock_render.call_args
        context = args[2]

        self.assertEqual(context, {"foo": "bar"})
