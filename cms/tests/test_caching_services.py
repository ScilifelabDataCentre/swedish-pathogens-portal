"""Tests for the cache helper."""

from __future__ import annotations

from unittest.mock import MagicMock

from django.core.cache import cache
from django.test import SimpleTestCase

from cms.services.caching import cache_get_or_set


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
        result = cache_get_or_set(key="test_key", timeout=60, compute=compute)
        self.assertIsNone(result)
        self.assertIsNone(cache.get("test_key"))
