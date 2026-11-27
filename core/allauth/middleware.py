"""Custom middleware for allauth."""

from collections.abc import Callable

from allauth.mfa.adapter import get_adapter
from django.conf import settings
from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from wagtail.admin import messages


class RequireMFASetupMiddleware:
    """Require authenticated users to have MFA enabled.

    This middleware checks if the user is authenticated and has MFA enabled. If not,
    it redirects them to the MFA setup page. It allows access to MFA setup and
    management pages, as well as logout, static files, and media files, to prevent
    redirect loops and ensure proper functionality.
    """

    def __init__(self, get_response: Callable[[WSGIRequest], HttpResponse]) -> None:
        """Initialize the middleware with the get_response callable and set the MFA URL."""
        self.get_response = get_response

        # If MFA enforcement is enabled, initialize the MFA adapter
        # and determine the protected and exempted paths.
        if settings.MFA_ENFORCE:
            self.mfa_adapter = get_adapter()
            self.protected_paths = self._get_protected_paths()
            self.exempted_paths = self._get_exempted_paths()

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """Process the incoming request and enforce MFA setup for authenticated users."""

        # If MFA enforcement is disabled, allow the request to proceed without checking for MFA.
        if not settings.MFA_ENFORCE:
            return self.get_response(request)

        # If the user is not authenticated, or the request path is not protected, or the
        # request path is exempted, allow the request to proceed without enforcing MFA.
        if (
            not request.user.is_authenticated
            or not request.path.startswith(self.protected_paths)
            or request.path.startswith(self.exempted_paths)
        ):
            return self.get_response(request)

        # If the user is authenticated and the request path is protected or not exempted,
        # check if MFA is enabled. If not, redirect to the MFA setup page.
        if not self.mfa_adapter.is_mfa_enabled(request.user):
            messages.warning(
                request,
                "You don't have MFA enabled, please set it up to access full admin services.",
            )
            return redirect(reverse("mfa_index"))

        return self.get_response(request)

    def _get_protected_paths(self) -> tuple[str]:
        """Return a tuple of paths that should be protected by MFA enforcement."""
        protected_paths = (
            settings.ALLAUTH_BASE_URL,
            settings.WAGTAILADMIN_URL,
        )

        if settings.INCLUDE_DJANGO_ADMIN:
            protected_paths += (settings.DJANGO_ADMIN_URL,)

        return tuple(f"/{path.strip('/')}/" for path in protected_paths)

    def _get_exempted_paths(self) -> tuple[str]:
        """Return a tuple of paths that should be exempted from MFA enforcement."""
        exempted_paths = (
            reverse("mfa_index"),
            reverse("account_logout"),
            reverse("account_reauthenticate"),
            reverse("wagtailadmin_javascript_catalog"),
            reverse("wagtailadmin_sprite"),
            reverse("wagtailadmin_logout"),
        )

        if settings.INCLUDE_DJANGO_ADMIN:
            exempted_paths += (reverse("admin:logout"),)

        if settings.STATIC_URL:
            exempted_paths += (settings.STATIC_URL,)

        if settings.MEDIA_URL:
            exempted_paths += (settings.MEDIA_URL,)

        if settings.DEBUG:
            exempted_paths += ("__reload__",)

        return tuple(f"/{path.strip('/')}/" for path in exempted_paths)
