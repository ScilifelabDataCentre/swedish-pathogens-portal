"""Tests for the cache helper."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase

from cms.services.caching import cache_get_or_set, cache_get_or_set_with_fallback


class TestCacheGetOrSet(SimpleTestCase):
    """Tests for cache_get_or_set's cache hit/miss/error behaviour."""

    def setUp(self):
        """Clear the cache so each test starts uncached."""
        cache.clear()

    def test_cache_miss_computes_and_caches_value(self):
        """Test a cache miss calls compute and stores the result for next time."""
        compute = MagicMock(return_value="computed value")

        result = cache_get_or_set(key="test_key", timeout=60, compute=compute)

        self.assertEqual(result, "computed value")
        compute.assert_called_once()
        self.assertEqual(cache.get("test_key"), "computed value")

    def test_cache_hit_returns_cached_value_without_calling_compute(self):
        """Test a cache hit short-circuits and never calls compute."""
        cache.set("test_key", "cached value", 60)
        compute = MagicMock(return_value="computed value")

        result = cache_get_or_set(key="test_key", timeout=60, compute=compute)

        self.assertEqual(result, "cached value")
        compute.assert_not_called()

    def test_different_keys_are_cached_independently(self):
        """Test two distinct keys don't share a cache entry."""
        compute_a = MagicMock(return_value="a")
        compute_b = MagicMock(return_value="b")

        cache_get_or_set(key="key_a", timeout=60, compute=compute_a)
        cache_get_or_set(key="key_b", timeout=60, compute=compute_b)

        self.assertEqual(cache.get("key_a"), "a")
        self.assertEqual(cache.get("key_b"), "b")

    def test_compute_returning_none_is_not_cached(self):
        """Test compute returning None (e.g. a failed fetch) isn't cached and is retried."""
        compute = MagicMock(return_value=None)

        first = cache_get_or_set(key="test_key", timeout=60, compute=compute)
        second = cache_get_or_set(key="test_key", timeout=60, compute=compute)

        self.assertIsNone(first)
        self.assertIsNone(second)
        self.assertEqual(compute.call_count, 2)

    def test_compute_raising_expected_error_returns_none(self):
        """Test compute raising one of the expected parse errors is caught and returns None."""
        compute = MagicMock(side_effect=KeyError("missing"))
        with self.assertLogs("cms.services.caching", level="ERROR"):
            result = cache_get_or_set(key="test_key", timeout=60, compute=compute)
        self.assertIsNone(result)
        self.assertIsNone(cache.get("test_key"))


class TestCacheGetOrSetWithFallback(SimpleTestCase):
    """Tests for cache_get_or_set_with_fallback's last-good fallback behaviour."""

    def setUp(self):
        """Clear the cache so each test starts uncached."""
        cache.clear()

    def test_fresh_value_is_returned_and_kept_as_last_good(self):
        """Test a successful compute is returned as fresh and also kept as the fallback."""
        saved_at = datetime(2026, 11, 5, 9, 30, tzinfo=UTC)
        compute = MagicMock(return_value="fresh")

        with patch("cms.services.caching.timezone.now", return_value=saved_at):
            result = cache_get_or_set_with_fallback(
                key="test_key", timeout=60, fallback_timeout=600, compute=compute
            )

        self.assertEqual(result.value, "fresh")
        self.assertFalse(result.is_fallback)
        self.assertEqual(cache.get("test_key:last-good"), ("fresh", saved_at))

    def test_last_good_value_is_served_when_compute_fails(self):
        """Test the last good value and when it was saved are returned once compute fails."""
        saved_at = datetime(2026, 11, 5, 9, 30, tzinfo=UTC)
        cache.set("test_key:last-good", ("old", saved_at), 600)
        compute = MagicMock(return_value=None)

        with self.assertLogs("cms.services.caching", level="WARNING"):
            result = cache_get_or_set_with_fallback(
                key="test_key", timeout=60, fallback_timeout=600, compute=compute
            )

        compute.assert_called_once()
        self.assertEqual(result.value, "old")
        self.assertTrue(result.is_fallback)
        self.assertEqual(result.saved_at, saved_at)

    def test_fresh_cached_value_is_preferred_over_last_good(self):
        """Test an unexpired cached value is served without compute or the fallback."""
        cache.set("test_key", "cached", 60)
        cache.set("test_key:last-good", ("old", datetime(2026, 1, 1, tzinfo=UTC)), 600)
        compute = MagicMock(return_value=None)

        result = cache_get_or_set_with_fallback(
            key="test_key", timeout=60, fallback_timeout=600, compute=compute
        )

        compute.assert_not_called()
        self.assertEqual(result.value, "cached")
        self.assertFalse(result.is_fallback)

    def test_none_when_compute_fails_and_nothing_was_kept(self):
        """Test None is returned when compute fails and there is no last good value."""
        result = cache_get_or_set_with_fallback(
            key="test_key", timeout=60, fallback_timeout=600, compute=MagicMock(return_value=None)
        )
        self.assertIsNone(result.value)
        self.assertFalse(result.is_fallback)
