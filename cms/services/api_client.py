"""Shared helper functions for fetching data from external JSON APIs."""

from __future__ import annotations

import json
from typing import Any

import httpx
import structlog

LOGGER = structlog.get_logger(__name__)

# Reused across requests for connection pooling.
CLIENT = httpx.Client(timeout=10)


def fetch_json(url: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """GET `url` with `params` and parse the response body as JSON.

    `params` is optional: `url` may already include its own query string
    (e.g. "example.com/endpoint?foo=bar"), in which case pass no `params` at
    all. Passing `params` (even `{}`) overrides any query string in `url`,
    since that's how httpx.Client.get handles the two together.

    Returns None if the request times out, fails, or returns invalid JSON.
    """
    try:
        response = CLIENT.get(url, params=params)
        response.raise_for_status()
        return response.json()
    except httpx.TimeoutException as e:
        LOGGER.error("api_client.fetch_timeout", url=url, error=str(e), exc_info=False)
    except httpx.HTTPError as e:
        LOGGER.error("api_client.fetch_http_error", url=url, error=str(e), exc_info=True)
    except json.JSONDecodeError as e:
        LOGGER.error("api_client.fetch_invalid_json", url=url, error=str(e), exc_info=True)
    return None
