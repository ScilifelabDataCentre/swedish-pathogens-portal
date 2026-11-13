"""Tests for the auth related wagtail hooks."""

from html import unescape

from allauth.account.models import EmailAddress
from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.messages.storage.cookie import CookieStorage
from django.test import RequestFactory, TestCase
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
        self.request = RequestFactory().get("/")
        self.request._messages = CookieStorage(self.request)

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

    def test_creates_lowercase_email_address(self):
        """The email address is stored in lowercase."""
        self.user.email = "TEST@EXAMPLE.COM"
        put_email_address_for_user(self.request, self.user)

        self.assertTrue(
            EmailAddress.objects.filter(user=self.user, email=self.user.email.lower()).exists()
        )

    def test_does_not_create_email_address_if_email_already_exists(self):
        """An existing email address prevents creating another record."""
        existing_user = User.objects.create_user(username="anotheruser", password="password")  # noqa: S106
        existing_email = EmailAddress.objects.create(
            user_id=existing_user.id, email=self.user.email, verified=False, primary=False
        )

        put_email_address_for_user(self.request, self.user)

        self.assertEqual(EmailAddress.objects.filter(email=self.user.email).count(), 1)
        self.assertTrue(EmailAddress.objects.filter(pk=existing_email.pk).exists())

    def test_displays_warning_if_email_already_exists(self):
        """A warning message is displayed if the email already exists."""
        existing_user = User.objects.create_user(username="anotheruser", password="password")  # noqa: S106
        EmailAddress.objects.create(
            user=existing_user, email=self.user.email, verified=True, primary=True
        )
        put_email_address_for_user(self.request, self.user)
        stored_messages = list(messages.get_messages(self.request))

        self.assertEqual(len(stored_messages), 1)
        self.assertEqual(stored_messages[0].level, messages.WARNING)
        self.assertIn(self.user.email, str(stored_messages[0]))
        self.assertIn(self.user.username, str(stored_messages[0]))


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

    def test_creating_user_with_existing_email_displays_warning(self):
        """Creating a user with an existing email displays a warning."""
        existing_user = User.objects.create_user(username="anotheruser", password="password")  # noqa: S106
        EmailAddress.objects.create(
            user=existing_user, email="existing@example.com", verified=True, primary=True
        )

        response = self.client.post(
            reverse("wagtailusers_users:add"),
            data={
                "username": "newuser",
                "email": "existing@example.com",
                "first_name": "New",
                "last_name": "User",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(User.objects.filter(username="newuser").exists())
        self.assertFalse(EmailAddress.objects.filter(user__username="newuser").exists())
        self.assertIn(
            "Email address 'existing@example.com' already exists in the system",
            unescape(response.content.decode()),
        )
