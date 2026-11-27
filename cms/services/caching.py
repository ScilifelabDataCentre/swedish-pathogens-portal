"""Shared helper functions for caching data."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import structlog
from django.core.cache import cache
from django.utils import timezone

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
        LOGGER.error("caching.cache_compute_error", key=key, error=str(e), exc_info=True)
        return None


@dataclass(frozen=True)
class FallbackResult:
    """A value from ``cache_get_or_set_with_fallback``.

    Attributes:
        value: The fresh or cached value, a last good copy, or None.
        saved_at: When ``value`` was fetched, if it is a last good copy served
            because fetching a fresh one failed; otherwise None.
    """

    value: Any | None
    saved_at: datetime | None = None

    @property
    def is_fallback(self) -> bool:
        """Return whether ``value`` is an older copy rather than a fresh one."""
        return self.saved_at is not None


def cache_get_or_set_with_fallback(
    key: str, timeout: int, fallback_timeout: int, compute: Callable[[], Any | None]
) -> FallbackResult:
    """Like ``cache_get_or_set``, but fall back to the last good value if computing fails.

    Every successfully computed value is also kept, with the time it was fetched,
    under a second key for ``fallback_timeout`` seconds (much longer than
    ``timeout``). When the value isn't cached and ``compute`` fails (returns None),
    that last good copy is returned instead, so an outage of an external API
    doesn't empty the page for anything fetched recently.
    """
    fallback_key = f"{key}:last-good"

    def compute_and_keep() -> Any | None:  # noqa: ANN401
        """Compute the value and keep a timestamped copy of it as the last good value."""
        value = compute()
        if value is not None:
            cache.set(fallback_key, (value, timezone.now()), fallback_timeout)
        return value

    value = cache_get_or_set(key=key, timeout=timeout, compute=compute_and_keep)
    if value is not None:
        return FallbackResult(value)

    stored = cache.get(fallback_key)
    if stored is None:
        return FallbackResult(None)
    last_good, saved_at = stored
    LOGGER.warning("caching.serving_fallback", key=key, saved_at=saved_at.isoformat())
    return FallbackResult(last_good, saved_at)
