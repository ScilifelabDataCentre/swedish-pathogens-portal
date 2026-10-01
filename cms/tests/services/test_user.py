"""Tests for users related service functions."""

from django.contrib.auth.models import AnonymousUser, Group, User
from django.test import TestCase

from cms.services.user import is_internal_user


class TestIsInternalUser(TestCase):
    """Tests for is_internal_user function."""

    def setUp(self) -> None:
        """Create users and groups for tests."""

        self.editors = Group.objects.get(name="Editors")
        self.researchers = Group.objects.create(name="researchers")

        self.superuser = User.objects.create_superuser(username="admin", password="password")  # noqa: S106

        self.editor = User.objects.create_user(username="editor", password="password")  # noqa: S106
        self.editor.groups.add(self.editors)

        self.researcher = User.objects.create_user(username="researcher", password="password")  # noqa: S106
        self.researcher.groups.add(self.researchers)

        self.unauthenticated_user = AnonymousUser()

    def test_superuser_is_internal_user(self) -> None:
        """Test that returns True for super user."""
        self.assertTrue(is_internal_user(self.superuser))

    def test_editor_is_internal_user(self) -> None:
        """Test that returns True for editor."""
        self.assertTrue(is_internal_user(self.editor))

    def test_researcher_is_not_internal_user(self) -> None:
        """Test that returns False for other user."""
        self.assertFalse(is_internal_user(self.researcher))

    def test_unauthenticated_user_is_not_internal_user(self) -> None:
        """Test that returns False for unauthenticated user."""
        self.assertFalse(is_internal_user(self.unauthenticated_user))

    def test_none_returns_false(self) -> None:
        """Test that returns False for passed None."""
        self.assertFalse(is_internal_user(None))
