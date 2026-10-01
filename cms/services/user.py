"""User related service functions that can used across the CMS."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from django.contrib.auth.models import User


def is_internal_user(user: User | None) -> bool:
    """Return True if the user is internal.

    An internal user is defined as either a superuser or a member of the "Editors" group.

    Args:
        user: The user object to check.

    Returns:
        True if the user is internal, False otherwise.
        Also returns False if the user is None or not authenticated.
    """

    if not user or not getattr(user, "is_authenticated", False):
        return False
    return user.is_superuser or user.groups.filter(name="Editors").exists()
