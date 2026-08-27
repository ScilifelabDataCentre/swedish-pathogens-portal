"""Tests for the API client helper."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx
from django.test import SimpleTestCase

from cms.services.api_client import fetch_json


class TestFetchJson(SimpleTestCase):
    """Tests for fetch_json against a mocked httpx client."""

    @patch("cms.services.api_client.CLIENT.get")
    def test_successful_response_returns_parsed_json(self, mock_get: MagicMock):
        """Test a 200 response with a JSON body is parsed and returned."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"hitCount": 42}
        mock_get.return_value = mock_response

        result = fetch_json(url="https://example.test/api", params={"query": "x"})

        self.assertEqual(result, {"hitCount": 42})
        mock_get.assert_called_once_with("https://example.test/api", params={"query": "x"})
        mock_response.raise_for_status.assert_called_once()

    @patch("cms.services.api_client.CLIENT.get")
    def test_url_with_query_string_returns_parsed_json(self, mock_get: MagicMock):
        """Test omitting `params` is supported for a url that embeds its own query string."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"ok": True}
        mock_get.return_value = mock_response

        result = fetch_json(url="https://example.test/api?foo=bar&zoo=zar")

        self.assertEqual(result, {"ok": True})
        mock_get.assert_called_once_with("https://example.test/api?foo=bar&zoo=zar", params=None)

    @patch("cms.services.api_client.CLIENT.get")
    def test_timeout_returns_none(self, mock_get: MagicMock):
        """Test a timeout is caught and returns None rather than raising."""
        mock_get.side_effect = httpx.TimeoutException("timed out")
        with self.assertLogs("cms.services.api_client", level="ERROR") as cm:
            self.assertIsNone(fetch_json(url="https://example.test/api", params={}))
        self.assertIn("api_client.fetch_timeout", cm.output[0])

    @patch("cms.services.api_client.CLIENT.get")
    def test_http_error_returns_none(self, mock_get: MagicMock):
        """Test a non-timeout HTTP error (e.g. connection failure) returns None."""
        mock_get.side_effect = httpx.ConnectError("connection failed")
        with self.assertLogs("cms.services.api_client", level="ERROR"):
            self.assertIsNone(fetch_json(url="https://example.test/api", params={}))

    @patch("cms.services.api_client.CLIENT.get")
    def test_error_status_response_returns_none(self, mock_get: MagicMock):
        """Test a HTTPStatusError raise from a failed request returns None."""
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "server error", request=MagicMock(), response=MagicMock()
        )
        mock_get.return_value = mock_response
        with self.assertLogs("cms.services.api_client", level="ERROR"):
            self.assertIsNone(fetch_json(url="https://example.test/api", params={}))

    @patch("cms.services.api_client.CLIENT.get")
    def test_invalid_json_returns_none(self, mock_get: MagicMock):
        """Test a response body that fails to parse as JSON returns None."""
        mock_response = MagicMock()
        mock_response.json.side_effect = json.JSONDecodeError("bad json", "doc", 0)
        mock_get.return_value = mock_response
        with self.assertLogs("cms.services.api_client", level="ERROR"):
            self.assertIsNone(fetch_json(url="https://example.test/api", params={}))
