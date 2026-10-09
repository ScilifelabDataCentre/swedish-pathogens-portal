"""Tests for Plotly.js CDN helpers."""

import json

import plotly.graph_objects as go
from django.test import SimpleTestCase

from dashboard_visualisation.utils.plotly import (
    figure_to_json,
    get_plotlyjs_cdn_param,
    plot_html_from_json,
)


class TestPlotlyCdn(SimpleTestCase):
    """Tests for get_plotlyjs_cdn_param."""

    def test_returns_cdn_url(self) -> None:
        """Test that the CDN URL is extracted from Plotly's HTML output."""
        url = get_plotlyjs_cdn_param("url")
        self.assertIsNotNone(url)
        self.assertIn("cdn.plot.ly", url or "")
        self.assertTrue((url or "").endswith(".js"))

    def test_returns_integrity_hash(self) -> None:
        """Test that the SRI hash is extracted from Plotly's HTML output."""
        integrity = get_plotlyjs_cdn_param("hash")
        self.assertIsNotNone(integrity)
        self.assertTrue((integrity or "").startswith("sha256-"))

    def test_invalid_param_returns_none(self) -> None:
        """Test that unknown parameter names return None."""
        self.assertIsNone(get_plotlyjs_cdn_param("invalid"))


class TestFigureToJson(SimpleTestCase):
    """Test conversion of Plotly figures to PostgreSQL-safe JSON."""

    def test_returns_dict(self):
        """Test that a Plotly figure is converted to a dictionary."""
        figure = go.Figure()
        result = figure_to_json(figure)

        self.assertIsInstance(result, dict)

    def test_preserves_normal_values(self):
        """Test that normal numeric and string values are preserved."""
        figure = go.Figure(data=[go.Scatter(x=[1, 2, 3], y=[10.0, 20.0, 30.0], name="Test")])
        result = figure_to_json(figure)

        self.assertEqual(result["data"][0]["x"], [1, 2, 3])
        self.assertEqual(result["data"][0]["y"], [10.0, 20.0, 30.0])
        self.assertEqual(result["data"][0]["name"], "Test")

    def test_replaces_nan_with_none(self):
        """Test that NaN values are converted to None."""
        figure = go.Figure(data=[go.Scatter(x=[1, 2, 3], y=[10.0, float("nan"), 30.0])])
        result = figure_to_json(figure)

        self.assertEqual(result["data"][0]["y"], [10.0, None, 30.0])

    def test_replaces_positive_and_negative_infinity_with_none(self):
        """Test that positive and negative infinity are converted to None."""
        figure = go.Figure(data=[go.Scatter(x=[1, 2, 3], y=[float("inf"), float("-inf"), 30.0])])
        result = figure_to_json(figure)

        self.assertEqual(result["data"][0]["y"], [None, None, 30.0])

    def test_sanitizes_nested_values(self):
        """Test that non-finite values are replaced inside nested structures."""
        figure = go.Figure(
            data=[
                go.Scatter(
                    x=[1, 2],
                    y=[10.0, 20.0],
                    customdata=[{"value": float("nan")}, {"value": {"nested": float("inf")}}],
                )
            ]
        )
        result = figure_to_json(figure)
        customdata = result["data"][0]["customdata"]

        self.assertEqual(customdata[0]["value"], None)
        self.assertEqual(customdata[1]["value"]["nested"], None)

    def test_does_not_replace_finite_floats(self):
        """Test that finite floats are left unchanged."""
        figure = go.Figure(data=[go.Scatter(y=[0.0, 1.5, -2.75])])
        result = figure_to_json(figure)

        self.assertEqual(result["data"][0]["y"], [0.0, 1.5, -2.75])


class TestPlotHtmlFromJson(SimpleTestCase):
    """Test conversion of Plotly JSON to HTML."""

    def test_returns_html_for_dict_input(self):
        """Test that a figure dictionary is converted to an HTML fragment."""
        data = {
            "data": [{"type": "scatter", "x": [1, 2], "y": [3, 4]}],
            "layout": {"title": "Test plot"},
        }
        result = plot_html_from_json(data)

        self.assertIsInstance(result, str)
        self.assertIn("<div", result)
        self.assertIn("plotly", result.lower())

    def test_returns_html_for_json_string_input(self):
        """Test that a JSON string is converted to an HTML fragment."""
        data = json.dumps(
            {
                "data": [{"type": "scatter", "x": [1, 2], "y": [3, 4]}],
                "layout": {"title": "Test plot"},
            }
        )
        result = plot_html_from_json(data)

        self.assertIsInstance(result, str)
        self.assertIn("<div", result)
        self.assertIn("plotly", result.lower())

    def test_returns_none_for_none_input(self):
        """Test that None input returns None."""
        result = plot_html_from_json(None)

        self.assertIsNone(result)

    def test_returns_none_for_invalid_json(self):
        """Test that invalid JSON returns None."""
        result = plot_html_from_json("{invalid json}")

        self.assertIsNone(result)

    def test_returns_none_for_invalid_figure_data(self):
        """Test that invalid Plotly figure data returns None."""
        result = plot_html_from_json({"not": "a valid plotly figure"})

        self.assertIsNone(result)

    def test_applies_height(self):
        """Test that the requested height is applied to the generated HTML."""
        data = {"data": [{"type": "scatter", "x": [1, 2], "y": [3, 4]}], "layout": {}}
        result = plot_html_from_json(data, height=500)

        self.assertIsInstance(result, str)
        self.assertIn("height:500px", result)

    def test_includes_plotlyjs_src(self):
        """Test that Plotly.js can be included when requested."""
        data = {"data": [{"type": "scatter", "x": [1, 2], "y": [3, 4]}], "layout": {}}
        result = plot_html_from_json(data, include_plotlyjs=True)

        self.assertIsInstance(result, str)
        self.assertIn("module.exports", result)

    def test_hides_modebar_when_requested(self):
        """Test that the modebar can be disabled."""
        data = {"data": [{"type": "scatter", "x": [1, 2], "y": [3, 4]}], "layout": {}}
        result = plot_html_from_json(data, display_modebar=False)

        self.assertIsInstance(result, str)
        self.assertIn('"displayModeBar": false', result)
