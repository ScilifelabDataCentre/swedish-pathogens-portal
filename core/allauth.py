"""Allauth related code for the project."""

from allauth.account.adapter import DefaultAccountAdapter
from django.http import HttpRequest


class SppAllauthAdapter(DefaultAccountAdapter):
    """Custom adapter for django-allauth.

    This class extends the DefaultAccountAdapter from django-allauth to customize the
    behaviour of the authentication system.

    Currently, it only overrides the `is_open_for_signup` method to disable user signups.
    It can be extended in the future to include more custom behaviour as needed.
    """

    def is_open_for_signup(self, request: HttpRequest) -> bool:
        """Return False to disable signup."""
        return False
