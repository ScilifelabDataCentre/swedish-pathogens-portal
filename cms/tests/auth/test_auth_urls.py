"""Test for authentication related urls."""

from allauth.account import urls as allauth_urls
from django.conf import settings
from django.test import SimpleTestCase
from wagtail.admin import urls as wagtailadmin_urls


class TestAuthUrlsRedirect(SimpleTestCase):
    """Test that Wagtail authentication URLs redirect to django-allauth."""

    def test_wagtail_auth_urls_exist(self):
        """Test that the original Wagtail authentication URLs exist."""
        url_patterns = ("login/", "logout/", "password_reset/")
        wagtail_patterns = {str(pattern.pattern) for pattern in wagtailadmin_urls.urlpatterns}

        for url in url_patterns:
            with self.subTest(url=url):
                self.assertIn(url, wagtail_patterns)

    def test_allauth_auth_urls_exist(self):
        """Test that the destination allauth authentication URLs exist."""
        urls = ("login/", "logout/", "password/reset/")
        allauth_patterns = {str(pattern.pattern) for pattern in allauth_urls.urlpatterns}

        for url in urls:
            with self.subTest(url=url):
                self.assertIn(url, allauth_patterns)

    def test_login_redirect(self):
        """Test that Wagtail login redirects to allauth login."""
        response = self.client.get(f"/{settings.WAGTAILADMIN_URL}login/")
        self.assertRedirects(
            response, f"/{settings.ALLAUTH_BASE_URL}login/", fetch_redirect_response=False
        )

    def test_logout_redirect(self):
        """Test that Wagtail logout redirects to allauth logout."""
        response = self.client.get(f"/{settings.WAGTAILADMIN_URL}logout/")
        self.assertRedirects(
            response, f"/{settings.ALLAUTH_BASE_URL}logout/", fetch_redirect_response=False
        )

    def test_password_reset_redirect(self):
        """Test that Wagtail password reset redirects to allauth password reset."""
        response = self.client.get(f"/{settings.WAGTAILADMIN_URL}password_reset/")
        self.assertRedirects(
            response, f"/{settings.ALLAUTH_BASE_URL}password/reset/", fetch_redirect_response=False
        )
