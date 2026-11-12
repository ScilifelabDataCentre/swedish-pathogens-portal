"""Tests for the auth related wagtail hooks."""

from allauth.account.models import EmailAddress
from django.contrib.auth.models import User
from django.http import HttpRequest
from django.test import TestCase
from django.urls import reverse

from cms.wagtail_hooks import put_email_address_for_user


class TestPutEmailAddressForUserHook(TestCase):
    """Tests for the put_email_address_for_user hook."""

    def setUp(self):
        """Set up a test user and request object."""
        self.user = User.objects.create_user(
            username="testuser",
            password="password",  # noqa: S106
            email="test@example.com",
        )
        self.request = HttpRequest()

    def test_creates_email_address(self):
        """An EmailAddress object is created for the user."""
        put_email_address_for_user(self.request, self.user)

        self.assertTrue(EmailAddress.objects.filter(user=self.user, email=self.user.email).exists())

    def test_email_address_has_correct_attributes(self):
        """The email address has the expected values."""
        put_email_address_for_user(self.request, self.user)
        email_address = EmailAddress.objects.get(user=self.user)

        self.assertEqual(email_address.user_id, self.user.id)
        self.assertEqual(email_address.email, self.user.email)
        self.assertTrue(email_address.verified)
        self.assertTrue(email_address.primary)

    def test_does_not_create_duplicate_email_addresses(self):
        """Calling the hook multiple times does not create duplicates."""
        put_email_address_for_user(self.request, self.user)
        put_email_address_for_user(self.request, self.user)

        self.assertEqual(EmailAddress.objects.filter(user=self.user).count(), 1)

    def test_does_not_overwrite_existing_email_address(self):
        """An existing EmailAddress object is not overwritten."""
        existing_email = EmailAddress.objects.create(
            user=self.user, email=self.user.email, verified=False, primary=False
        )
        put_email_address_for_user(self.request, self.user)
        existing_email.refresh_from_db()

        self.assertFalse(existing_email.verified)
        self.assertFalse(existing_email.primary)
        self.assertEqual(EmailAddress.objects.filter(user=self.user).count(), 1)


class TestUserCreationPutsEmail(TestCase):
    """Test that creating a user through Wagtail admin triggers the hook."""

    def setUp(self):
        """Set up a superuser and log in."""
        self.admin_user = User.objects.create_superuser(
            username="admin",
            password="password",  # noqa: S106
            email="admin@example.com",
        )
        self.client.force_login(self.admin_user)

    def test_creating_user_through_wagtail_admin_creates_email_address(self):
        """Creating a user through Wagtail admin creates an email address."""
        response = self.client.post(
            reverse("wagtailusers_users:add"),
            data={
                "username": "newuser",
                "email": "newuser@example.com",
                "first_name": "New",
                "last_name": "User",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(User.objects.filter(username="newuser").exists())

        user = User.objects.get(username="newuser")

        self.assertTrue(EmailAddress.objects.filter(user_id=user.id).exists())

        email_address = EmailAddress.objects.get(user_id=user.id)

        self.assertEqual(email_address.email, "newuser@example.com")
        self.assertTrue(email_address.verified)
        self.assertTrue(email_address.primary)
