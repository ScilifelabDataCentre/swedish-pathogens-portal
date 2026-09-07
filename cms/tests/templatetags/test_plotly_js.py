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
