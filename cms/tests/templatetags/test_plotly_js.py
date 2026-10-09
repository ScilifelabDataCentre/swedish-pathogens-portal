"""Tests for Plotly.js CDN helpers."""

from django.template import Context, Template
from django.test import SimpleTestCase


class TestPlotlyJsTemplateTag(SimpleTestCase):
    """Tests for the plotlyjs_once template tag."""

    def test_plotlyjs_once_includes_script_only_once(self) -> None:
        """Test that plotlyjs_once emits one script tag per render context."""
        template = Template("{% load plotly_js %}{% plotlyjs_once %}{% plotlyjs_once %}")
        rendered = template.render(Context())

        self.assertEqual(rendered.count("<script"), 1)
        self.assertIn("cdn.plot.ly", rendered)


class TestPlotlyHtmlFromJsonTemplateTag(SimpleTestCase):
    """Tests for the plotly_html_from_json template tag."""

    def test_plotly_html_from_json_renders_div(self) -> None:
        """Test that plotly_html_from_json renders a div with the given JSON."""
        json_data = '{"data": [{"x": [1, 2, 3], "y": [4, 5, 6]}]}'
        template = Template('{% load plotly_js %}{% plotly_html_from_json data height="400px" %}')
        rendered = template.render(Context({"data": json_data}))

        self.assertIn("plotly", rendered)
        self.assertIn("height:400px;", rendered)
