"""Tests for the authentication middleware."""

from html import unescape
from importlib import reload

from allauth.mfa.models import Authenticator
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.models import AnonymousUser, User
from django.contrib.messages.storage.cookie import CookieStorage
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import clear_url_caches, reverse

from core import urls as core_urls
from core.allauth.middleware import RequireMFASetupMiddleware


@override_settings(MFA_ENFORCE=True, DEBUG=True, INCLUDE_DJANGO_ADMIN=True)
class TestRequireMFASetupMiddlewareConfiguration(SimpleTestCase):
    """Test MFA middleware configuration."""

    def setUp(self):
        """Set up the middleware instance for testing."""
        reload(core_urls)
        self.addCleanup(reload, core_urls)

        clear_url_caches()
        self.addCleanup(clear_url_caches)

        self.middleware = RequireMFASetupMiddleware(lambda request: None)

    def test_protected_paths_are_configured_correctly(self):
        """Test the middleware protects the expected paths."""
        expected_paths = (
            f"/{settings.ALLAUTH_BASE_URL.strip('/')}/",
            f"/{settings.WAGTAILADMIN_URL.strip('/')}/",
            f"/{settings.DJANGO_ADMIN_URL.strip('/')}/",
        )

        self.assertEqual(self.middleware.protected_paths, expected_paths)

    def test_exempted_paths_are_configured_correctly(self):
        """Test the middleware exempts the expected paths."""
        expected_paths = (
            reverse("mfa_index"),
            reverse("account_logout"),
            reverse("account_reauthenticate"),
            reverse("wagtailadmin_javascript_catalog"),
            reverse("wagtailadmin_sprite"),
            reverse("wagtailadmin_logout"),
            reverse("admin:logout"),
            settings.STATIC_URL,
            settings.MEDIA_URL,
            "__reload__",
        )
        expected_paths = tuple(f"/{path.strip('/')}/" for path in expected_paths)

        self.assertEqual(self.middleware.exempted_paths, expected_paths)

    @override_settings(MFA_ENFORCE=False)
    def test_mfa_configuration_is_skipped_when_enforcement_is_disabled(self):
        """Test that MFA configuration is skipped when enforcement is disabled."""
        middleware = RequireMFASetupMiddleware(lambda request: None)

        self.assertFalse(hasattr(middleware, "mfa_adapter"))
        self.assertFalse(hasattr(middleware, "protected_paths"))
        self.assertFalse(hasattr(middleware, "exempted_paths"))


@override_settings(MFA_ENFORCE=True)
class TestRequireMFASetupMiddleware(TestCase):
    """Test cases for the RequireMFASetupMiddleware."""

    def setUp(self):
        """Set up test data and middleware instance."""
        self.user = User.objects.create_user(username="testuser", password="password")  # noqa: S106
        self.middleware = self.get_middleware()
        self.factory = RequestFactory()

    def get_middleware(self):
        """Return an instance of the RequireMFASetupMiddleware."""
        return RequireMFASetupMiddleware(lambda request: HttpResponse("OK"))

    def make_request(self, path: str, user: User | None = None):
        """Create a request with the given user."""
        request = self.factory.get(path)
        request.user = user or self.user
        request._messages = CookieStorage(request)
        return request

    def enable_mfa(self, user: User):
        """Create a real TOTP authenticator for the given user."""
        return Authenticator.objects.create(
            user=user, type=Authenticator.Type.TOTP, data={"secret": "12345678901234567890"}
        )

    def reload_urlconf(self):
        """Reload the urlconf to apply the settings changes."""
        reload(core_urls)
        self.addCleanup(reload, core_urls)

        clear_url_caches()
        self.addCleanup(clear_url_caches)

    def test_authenticated_user_with_mfa_can_access_admin(self):
        """Test authenticated users with MFA can access admin."""
        self.enable_mfa(self.user)
        request = self.make_request(reverse("wagtailadmin_home"))
        response = self.middleware(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"OK")

    def test_authenticated_user_without_mfa_is_redirected(self):
        """Test authenticated users without MFA are redirected."""
        request = self.make_request(reverse("wagtailadmin_home"))
        response = self.middleware(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("mfa_index"))

    def test_authenticated_user_without_mfa_sees_warning_message(self):
        """Test authenticated users without MFA see a warning message."""
        request = self.make_request(reverse("wagtailadmin_home"))
        response = self.middleware(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("mfa_index"))

        # Check that the warning message is set
        stored_messages = list(request._messages)

        self.assertEqual(len(stored_messages), 1)
        self.assertEqual(stored_messages[0].level, messages.WARNING)
        self.assertIn("You don't have MFA enabled", unescape(str(stored_messages[0])))

    @override_settings(MFA_ENFORCE=False)
    def test_mfa_enforcement_can_be_disabled(self):
        """Test MFA enforcement can be disabled through settings."""
        request = self.make_request(reverse("wagtailadmin_home"))
        response = self.middleware(request)

        self.assertEqual(response.status_code, 200)

    def test_unauthenticated_user_is_not_redirected_to_mfa(self):
        """Test unauthenticated users are not redirected to MFA setup."""
        request = self.make_request(reverse("wagtailadmin_login"), user=AnonymousUser())
        response = self.middleware(request)

        self.assertEqual(response.status_code, 200)

    def test_non_protected_path_does_not_enforce_mfa(self):
        """Test non-protected paths do not enforce MFA."""
        request = self.make_request("/dashboard/")
        response = self.middleware(request)

        self.assertEqual(response.status_code, 200)

    def test_allauth_paths_are_protected(self):
        """Test allauth paths are protected by MFA enforcement."""
        request = self.make_request(reverse("account_email"))
        response = self.middleware(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("mfa_index"))

    def test_allauth_paths_with_mfa_enabled_are_accessible(self):
        """Test allauth paths are accessible when MFA is enabled."""
        self.enable_mfa(self.user)
        request = self.make_request(reverse("account_email"))
        response = self.middleware(request)

        self.assertEqual(response.status_code, 200)

    @override_settings(INCLUDE_DJANGO_ADMIN=True)
    def test_django_admin_path_is_protected(self):
        """Test Django admin paths are protected by MFA enforcement."""
        self.reload_urlconf()
        middleware = self.get_middleware()
        request = self.make_request(reverse("admin:index"))
        response = middleware(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("mfa_index"))

    @override_settings(INCLUDE_DJANGO_ADMIN=True)
    def test_django_admin_user_with_mfa_can_access_admin(self):
        """Test users with MFA can access Django admin."""
        self.reload_urlconf()
        middleware = self.get_middleware()
        self.enable_mfa(self.user)
        request = self.make_request(reverse("admin:index"))
        response = middleware(request)

        self.assertEqual(response.status_code, 200)

    @override_settings(INCLUDE_DJANGO_ADMIN=True)
    def test_django_admin_logout_path_is_exempted(self):
        """Test Django logout is exempted from MFA enforcement."""
        self.reload_urlconf()
        middleware = self.get_middleware()
        request = self.make_request(reverse("admin:logout"))
        response = middleware(request)

        self.assertEqual(response.status_code, 200)

    def test_account_logout_path_is_exempted(self):
        """Test account logout is exempted from MFA enforcement."""
        request = self.make_request(reverse("account_logout"))
        response = self.middleware(request)

        self.assertEqual(response.status_code, 200)

    def test_wagtail_logout_path_is_exempted(self):
        """Test Wagtail logout is exempted from MFA enforcement."""
        request = self.make_request(reverse("wagtailadmin_logout"))
        response = self.middleware(request)

        self.assertEqual(response.status_code, 200)

    def test_mfa_setup_path_is_exempted(self):
        """Test MFA setup paths are exempted from enforcement."""
        request = self.make_request(reverse("mfa_index"))
        response = self.middleware(request)

        self.assertEqual(response.status_code, 200)

    def test_account_reauthentication_path_is_exempted(self):
        """Test account reauthentication is exempted from MFA enforcement."""
        request = self.make_request(reverse("account_reauthenticate"))
        response = self.middleware(request)

        self.assertEqual(response.status_code, 200)

    def test_wagtail_javascript_catalog_is_exempted(self):
        """Test Wagtail JavaScript catalog is exempted from MFA enforcement."""
        request = self.make_request(reverse("wagtailadmin_javascript_catalog"))
        response = self.middleware(request)

        self.assertEqual(response.status_code, 200)

    def test_wagtail_sprite_is_exempted(self):
        """Test Wagtail sprite is exempted from MFA enforcement."""
        request = self.make_request(reverse("wagtailadmin_sprite"))
        response = self.middleware(request)

        self.assertEqual(response.status_code, 200)

    def test_static_files_are_not_blocked(self):
        """Test static files are accessible without MFA."""
        request = self.make_request(f"/{settings.STATIC_URL}css/example.css")
        response = self.middleware(request)

        self.assertEqual(response.status_code, 200)

    def test_media_files_are_not_blocked(self):
        """Test media files are accessible without MFA."""
        request = self.make_request(f"/{settings.MEDIA_URL}example.jpg")
        response = self.middleware(request)

        self.assertEqual(response.status_code, 200)

    @override_settings(DEBUG=True)
    def test_debug_reload_path_is_exempted(self):
        """Test development reload paths are exempted from MFA."""
        self.reload_urlconf()
        middleware = self.get_middleware()
        request = self.make_request("/__reload__/")
        response = middleware(request)

        self.assertEqual(response.status_code, 200)
