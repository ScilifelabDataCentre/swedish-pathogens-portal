"""Tests for the custom allauth adapter."""

from django.test import RequestFactory, SimpleTestCase
from django.urls import reverse

from core.allauth import SppAllauthAdapter


class TestSppAllauthAdapter(SimpleTestCase):
    """Test the custom allauth adapter."""

    def setUp(self):
        """Set up the test case."""
        self.adapter = SppAllauthAdapter()
        self.request = RequestFactory().get(reverse("account_signup"))

    def test_signup_is_disabled(self):
        """Test that the signup is disabled."""
        self.assertFalse(self.adapter.is_open_for_signup(self.request))
