"""Shared helper functions for fetching and caching data from external JSON APIs."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import structlog
from django.core.cache import cache

LOGGER = structlog.get_logger(__name__)

# Reused across requests for connection pooling.
CLIENT = httpx.Client(timeout=10)


def fetch_json(url: str, params: dict[str, Any]) -> dict[str, Any] | None:
    """GET `url` with `params` and parse the response body as JSON.

    Returns None if the request times out, fails, or returns invalid JSON.
    """
    try:
        response = CLIENT.get(url, params=params)
        response.raise_for_status()
        return response.json()
    except httpx.TimeoutException as e:
        LOGGER.error("external_apis.fetch_timeout", url=url, error=str(e), exc_info=False)
    except httpx.HTTPError as e:
        LOGGER.error("external_apis.fetch_http_error", url=url, error=str(e), exc_info=True)
    except json.JSONDecodeError as e:
        LOGGER.error("external_apis.fetch_invalid_json", url=url, error=str(e), exc_info=True)
    return None


def cache_get_or_set(key: str, timeout: int, compute: Callable[[], Any | None]) -> Any | None:  # noqa: ANN401
    """Return the cached value for a given `key` or compute and cache it if missing.

    `compute` is a function to calculate the value if it's not in the cache.
    It should return None to indicate "don't cache this result"
    E.G.: a failed fetch should return None and not raise or return False etc...
    """
    cached = cache.get(key)
    if cached is not None:
        return cached
    try:
        value = compute()
        if value is not None:
            cache.set(key, value, timeout)
        return value
    except (TypeError, AttributeError, KeyError, IndexError) as e:
        LOGGER.error("external_apis.cache_compute_error", key=key, error=str(e), exc_info=True)
        return None
