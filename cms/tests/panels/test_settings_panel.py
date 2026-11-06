"""Tests for the settings panel."""

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from cms.panels.settings_panel import EmailPasswordPanel, EmptyForm


class TestEmailPasswordPanel(SimpleTestCase):
    """Test the EmailPasswordPanel configuration and behaviour."""

    def test_panel_configuration(self):
        """Test the panel configuration."""
        self.assertEqual(EmailPasswordPanel.name, "email_password")
        self.assertEqual(EmailPasswordPanel.title, "Email and Password")
        self.assertEqual(EmailPasswordPanel.description, "Manage your email and password settings.")
        self.assertEqual(EmailPasswordPanel.order, 150)
        self.assertEqual(EmailPasswordPanel.form_class, EmptyForm)
        self.assertEqual(
            EmailPasswordPanel.template_name, "wagtailadmin/settings_panels/email_password.html"
        )

    def test_empty_form_has_no_fields(self):
        """Test the empty form has no fields."""
        form = EmptyForm()

        self.assertEqual(len(form.fields), 0)

    def test_empty_form_ignores_instance_argument(self):
        """Test the empty form ignores the instance argument."""
        form = EmptyForm(instance=object())

        self.assertEqual(len(form.fields), 0)

    def test_empty_form_save_does_nothing(self):
        """Test saving the empty form does nothing."""
        form = EmptyForm()

        self.assertIsNone(form.save())


class TestEmailPasswordPanelRendering(TestCase):
    """Test the EmailPasswordPanel rendering on the Wagtail account page."""

    def test_account_page_renders_email_and_password_links(self):
        """Test the account page renders the email and password links."""
        test_user = User.objects.create_superuser(username="testuser", password="password")  # noqa: S106
        self.client.force_login(test_user)
        response = self.client.get(reverse("wagtailadmin_account"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Manage email address")
        self.assertContains(response, "Change password")
        self.assertContains(response, f'href="{reverse("account_email")}"')
        self.assertContains(response, f'href="{reverse("account_change_password")}"')
