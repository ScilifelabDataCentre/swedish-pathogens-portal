"""Shared helper functions for caching data."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import structlog
from django.core.cache import cache

LOGGER = structlog.get_logger(__name__)


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
