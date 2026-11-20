"""Test for authentication related urls."""

from importlib import reload

from allauth.account import urls as allauth_urls
from django.conf import settings
from django.contrib import admin
from django.test import TestCase, override_settings
from django.urls import clear_url_caches
from wagtail import urls as wagtail_urls
from wagtail.admin import urls as wagtailadmin_urls

from core import urls as core_urls


class TestAuthUrlsRedirect(TestCase):
    """Test that Wagtail authentication URLs redirect to django-allauth."""

    def reload_urlconf(self):
        """Reload the urlconf to apply the settings changes."""
        reload(core_urls)
        self.addCleanup(reload, core_urls)

        clear_url_caches()
        self.addCleanup(clear_url_caches)

    def test_wagtail_auth_urls_exist(self):
        """Test that the wagtail authentication URLs exist."""
        url_patterns = ("_util/login/",)
        wagtail_patterns = {str(pattern.pattern) for pattern in wagtail_urls.urlpatterns}

        for url in url_patterns:
            with self.subTest(url=url):
                self.assertIn(url, wagtail_patterns)

    def test_wagtailadmin_auth_urls_exist(self):
        """Test that the wagtail admin authentication URLs exist."""
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

    @override_settings(INCLUDE_DJANGO_ADMIN=True)
    def test_django_admin_auth_urls_exist(self):
        """Test that the django admin authentication URLs exist."""
        url_patterns = ("login/", "logout/")
        admin_urlpatterns, _, _ = admin.site.urls
        admin_patterns = {str(pattern.pattern) for pattern in admin_urlpatterns}

        for url in url_patterns:
            with self.subTest(url=url):
                self.assertIn(url, admin_patterns)

    def test_util_login_redirect(self):
        """Test that Wagtail util login redirects to allauth login."""
        response = self.client.get("/_util/login/")
        self.assertRedirects(
            response, f"/{settings.ALLAUTH_BASE_URL}login/", fetch_redirect_response=False
        )

    def test_wagtail_admin_login_redirect(self):
        """Test that Wagtail login redirects to allauth login."""
        response = self.client.get(f"/{settings.WAGTAILADMIN_URL}login/")
        self.assertRedirects(
            response, f"/{settings.ALLAUTH_BASE_URL}login/", fetch_redirect_response=False
        )

    def test_wagtail_admin_logout_redirect(self):
        """Test that Wagtail logout redirects to allauth logout."""
        response = self.client.get(f"/{settings.WAGTAILADMIN_URL}logout/")
        self.assertRedirects(
            response, f"/{settings.ALLAUTH_BASE_URL}logout/", fetch_redirect_response=False
        )

    def test_wagtail_admin_password_reset_redirect(self):
        """Test that Wagtail password reset redirects to allauth password reset."""
        response = self.client.get(f"/{settings.WAGTAILADMIN_URL}password_reset/")
        self.assertRedirects(
            response, f"/{settings.ALLAUTH_BASE_URL}password/reset/", fetch_redirect_response=False
        )

    @override_settings(INCLUDE_DJANGO_ADMIN=True)
    def test_django_admin_login_redirect(self):
        """Test that Django admin login redirects to allauth login."""
        self.reload_urlconf()
        response = self.client.get(f"/{settings.DJANGO_ADMIN_URL}login/")
        self.assertRedirects(
            response, f"/{settings.ALLAUTH_BASE_URL}login/", fetch_redirect_response=False
        )

    @override_settings(INCLUDE_DJANGO_ADMIN=True)
    def test_django_admin_logout_redirect(self):
        """Test that Django admin logout redirects to allauth logout."""
        self.reload_urlconf()
        response = self.client.get(f"/{settings.DJANGO_ADMIN_URL}logout/")
        self.assertRedirects(
            response, f"/{settings.ALLAUTH_BASE_URL}logout/", fetch_redirect_response=False
        )
