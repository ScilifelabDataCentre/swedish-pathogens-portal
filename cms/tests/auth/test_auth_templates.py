"""Test for authentication templates."""

import re
from collections.abc import Iterator

from django.conf import settings
from django.contrib.auth.models import User
from django.core import mail
from django.template.base import Node, NodeList
from django.template.defaulttags import URLNode
from django.template.loader import get_template
from django.template.loader_tags import ExtendsNode, IncludeNode
from django.test import SimpleTestCase, TestCase
from django.urls import reverse


def find_nodes(nodelist: NodeList, node_type: type[Node]) -> Iterator[Node]:
    """Find template nodes recursively."""
    for node in nodelist:
        if isinstance(node, node_type):
            yield node

        if hasattr(node, "nodelist"):
            yield from find_nodes(node.nodelist, node_type)


def get_url_names_from_template(template_name: str) -> set[str]:
    """Get all URL names used in a template."""
    template = get_template(template_name)
    url_nodes = find_nodes(template.template.nodelist, URLNode)
    return {node.view_name.var for node in url_nodes}


def get_url_from_email(
    test_case: TestCase | SimpleTestCase, recipient: str, email_index: int = 0
) -> str:
    """Get a URL from an outgoing email sent to a specific recipient."""
    matching_emails = [email for email in mail.outbox if recipient in email.to]

    test_case.assertGreater(
        len(matching_emails), email_index, f"No email found for recipient {recipient}."
    )

    email_body = matching_emails[email_index].body
    match = re.search(r"https?://[^\s<>]+", email_body)

    test_case.assertIsNotNone(match, f"No URL found in email to {recipient}.")

    return match.group(0)


class TestLoginTemplate(SimpleTestCase):
    """Test custom django-allauth login template."""

    def test_base_wagtail_admin_template_is_extended(self):
        """Test that the right Wagtail admin template is extended."""
        login_template = get_template("account/login.html")
        extends_node = next(find_nodes(login_template.template.nodelist, ExtendsNode))

        self.assertEqual(extends_node.parent_name.var, "wagtailadmin/login.html")

    def test_login_template_includes_remember_me_checkbox(self):
        """Test that the login template includes Wagtail's remember me checkbox."""
        login_template = get_template("account/login.html")
        include_nodes = find_nodes(login_template.template.nodelist, IncludeNode)

        self.assertTrue(
            any(
                node.template.var == "wagtailadmin/shared/forms/single_checkbox.html"
                for node in include_nodes
            )
        )

    def test_urls_in_login_template(self):
        """Test that all URL names used in the login template exist."""
        expected_url_names = {"account_login", "wagtailadmin_home", "account_reset_password"}
        url_names = get_url_names_from_template("account/login.html")

        self.assertEqual(expected_url_names, url_names)
        for url_name in url_names:
            with self.subTest(url_name=url_name):
                self.assertTrue(reverse(url_name))

    def test_login_form_fields_exist(self):
        """Test that the allauth login form contains the expected fields."""
        response = self.client.get(f"/{settings.ALLAUTH_BASE_URL}login/")
        form = response.context["form"]

        self.assertIn("login", form.fields)
        self.assertRegex(response.content.decode(), r'<input\b[^>]*\bname="login"')
        self.assertIn("password", form.fields)
        self.assertRegex(response.content.decode(), r'<input\b[^>]*\bname="password"')

    def test_login_template_used(self):
        """Test that the custom allauth login template is rendered."""
        response = self.client.get(f"/{settings.ALLAUTH_BASE_URL}login/")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "account/login.html")


class TestLogoutTemplate(TestCase):
    """Test custom django-allauth logout template."""

    def test_urls_in_logout_template(self):
        """Test that all URL names used in the logout template exist."""
        expected_url_names = {"account_logout"}
        url_names = get_url_names_from_template("account/logout.html")

        self.assertEqual(expected_url_names, url_names)
        for url_name in url_names:
            with self.subTest(url_name=url_name):
                self.assertTrue(reverse(url_name))

    def test_logout_template_used(self):
        """Test that the custom allauth logout template is rendered."""
        test_user = User.objects.create_user(username="testuser", password="password")  # noqa: S106
        self.client.force_login(test_user)
        response = self.client.get(f"/{settings.ALLAUTH_BASE_URL}logout/")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "account/logout.html")
        self.assertRegex(response.content.decode(), r'<form\b[^>]*\bmethod="post"')
        self.assertContains(response, "document.getElementById('logout-form').submit();")

    def test_logout_without_confirmation(self):
        """Test that the user is logged out without confirmation."""
        user = User.objects.create_user(username="testuser", password="password")  # noqa: S106
        self.client.force_login(user)

        self.assertIn("_auth_user_id", self.client.session)

        response = self.client.post(reverse("account_logout"))

        self.assertEqual(response.status_code, 302)
        self.assertNotIn("_auth_user_id", self.client.session)


class TestEmailTemplate(TestCase):
    """Test custom django-allauth email template."""

    def test_base_wagtail_admin_template_is_extended(self):
        """Test that the right Wagtail admin template is extended."""
        password_reset_template = get_template("account/email.html")
        extends_node = next(find_nodes(password_reset_template.template.nodelist, ExtendsNode))

        self.assertEqual(extends_node.parent_name.var, "wagtailadmin/base.html")

    def test_urls_in_email_template(self):
        """Test that all URL names used in the email template exist."""
        expected_url_names = {"wagtailadmin_account", "account_email"}
        url_names = get_url_names_from_template("account/email.html")

        self.assertEqual(expected_url_names, url_names)
        for url_name in url_names:
            with self.subTest(url_name=url_name):
                self.assertTrue(reverse(url_name))

    def test_email_form_fields_and_context_values_exist(self):
        """Test that the allauth email form contains the expected fields and context values."""
        test_user = User.objects.create_user(
            username="testuser",
            password="password",  # noqa: S106
            email="testuser@example.com",
        )
        self.client.force_login(test_user)
        response = self.client.get(f"/{settings.ALLAUTH_BASE_URL}email/")
        form = response.context["form"]

        self.assertIn("email", form.fields)

        html_str = response.content.decode()
        email_inputs = re.findall(r'<input\b[^>]*\bname="email"', html_str)

        self.assertEqual(len(email_inputs), 2)
        self.assertIn("emailaddress_radios", response.context)

    def test_email_template_used(self):
        """Test that the custom allauth email template is rendered."""
        test_user = User.objects.create_user(username="testuser", password="password")  # noqa: S106
        self.client.force_login(test_user)
        response = self.client.get(f"/{settings.ALLAUTH_BASE_URL}email/")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "account/email.html")


class TestEmailConfirmTemplate(TestCase):
    """Test custom django-allauth email confirm template."""

    def test_base_wagtail_admin_template_is_extended(self):
        """Test that the right Wagtail admin template is extended."""
        password_reset_template = get_template("account/email_confirm.html")
        extends_node = next(find_nodes(password_reset_template.template.nodelist, ExtendsNode))

        self.assertEqual(extends_node.parent_name.var, "wagtailadmin/admin_base.html")

    def test_urls_in_email_confirm_template(self):
        """Test that all URL names used in the email confirm template exist."""
        expected_url_names = {"account_confirm_email", "account_email"}
        url_names = get_url_names_from_template("account/email_confirm.html")

        self.assertEqual(expected_url_names, url_names)
        for url_name in url_names:
            with self.subTest(url_name=url_name):
                if url_name == "account_confirm_email":
                    self.assertTrue(reverse(url_name, kwargs={"key": "dummy-key"}))
                else:
                    self.assertTrue(reverse(url_name))

    def test_email_confirm_template_used(self):
        """Test that the custom allauth email confirm template is rendered."""
        test_user = User.objects.create_user(
            username="testuser",
            password="password",  # noqa: S106
            email="testemailconfirm@example.com",
        )
        self.client.force_login(test_user)
        self.client.post(reverse("account_email"), {"email": test_user.email, "action_send": True})
        confirm_url = get_url_from_email(self, test_user.email)
        response = self.client.get(confirm_url, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "account/email_confirm.html")


class TestPasswordChangeTemplate(TestCase):
    """Test custom django-allauth password change template."""

    def test_base_wagtail_admin_template_is_extended(self):
        """Test that the right Wagtail admin template is extended."""
        password_reset_template = get_template("account/password_change.html")
        extends_node = next(find_nodes(password_reset_template.template.nodelist, ExtendsNode))

        self.assertEqual(extends_node.parent_name.var, "wagtailadmin/base.html")

    def test_urls_in_password_change_template(self):
        """Test that all URL names used in the password change template exist."""
        expected_url_names = {"wagtailadmin_account", "account_change_password"}
        url_names = get_url_names_from_template("account/password_change.html")

        self.assertEqual(expected_url_names, url_names)
        for url_name in url_names:
            with self.subTest(url_name=url_name):
                self.assertTrue(reverse(url_name))

    def test_password_change_form_fields_exist(self):
        """Test that the allauth password change form contains the expected fields."""
        test_user = User.objects.create_user(username="testuser", password="password")  # noqa: S106
        self.client.force_login(test_user)
        response = self.client.get(f"/{settings.ALLAUTH_BASE_URL}password/change/")
        form = response.context["form"]

        self.assertIn("oldpassword", form.fields)
        self.assertRegex(response.content.decode(), r'<input\b[^>]*\bname="oldpassword"')
        self.assertIn("password1", form.fields)
        self.assertRegex(response.content.decode(), r'<input\b[^>]*\bname="password1"')
        self.assertIn("password2", form.fields)
        self.assertRegex(response.content.decode(), r'<input\b[^>]*\bname="password2"')

    def test_password_change_template_used(self):
        """Test that the custom allauth password change template is rendered."""
        test_user = User.objects.create_user(username="testuser", password="password")  # noqa: S106
        self.client.force_login(test_user)
        response = self.client.get(f"/{settings.ALLAUTH_BASE_URL}password/change/")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "account/password_change.html")


class TestPasswordResetTemplate(SimpleTestCase):
    """Test custom django-allauth password reset template."""

    def test_base_wagtail_admin_template_is_extended(self):
        """Test that the right Wagtail admin template is extended."""
        password_reset_template = get_template("account/password_reset.html")
        extends_node = next(find_nodes(password_reset_template.template.nodelist, ExtendsNode))

        self.assertEqual(
            extends_node.parent_name.var, "wagtailadmin/account/password_reset/form.html"
        )

    def test_urls_in_password_reset_template(self):
        """Test that all URL names used in the password reset template exist."""
        expected_url_names = {"account_reset_password"}
        url_names = get_url_names_from_template("account/password_reset.html")

        self.assertEqual(expected_url_names, url_names)
        for url_name in url_names:
            with self.subTest(url_name=url_name):
                self.assertTrue(reverse(url_name))

    def test_password_reset_form_fields_exist(self):
        """Test that the allauth password reset form contains the expected fields."""
        response = self.client.get(f"/{settings.ALLAUTH_BASE_URL}password/reset/")
        form = response.context["form"]

        self.assertIn("email", form.fields)
        self.assertRegex(response.content.decode(), r'<input\b[^>]*\bname="email"')

    def test_password_reset_template_used(self):
        """Test that the custom allauth password reset template is rendered."""
        response = self.client.get(f"/{settings.ALLAUTH_BASE_URL}password/reset/")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "account/password_reset.html")


class TestPasswordResetDoneTemplate(SimpleTestCase):
    """Test custom django-allauth password reset done template."""

    def test_base_wagtail_admin_template_is_extended(self):
        """Test that the right Wagtail admin template is extended."""
        password_reset_done_template = get_template("account/password_reset_done.html")
        extends_node = next(find_nodes(password_reset_done_template.template.nodelist, ExtendsNode))

        self.assertEqual(
            extends_node.parent_name.var, "wagtailadmin/account/password_reset/done.html"
        )

    def test_password_reset_done_template_used(self):
        """Test that the custom allauth password reset done template is rendered."""
        response = self.client.get(f"/{settings.ALLAUTH_BASE_URL}password/reset/done/")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "account/password_reset_done.html")


class TestPasswordResetFromKeyTemplate(TestCase):
    """Test custom django-allauth password reset form key template."""

    def test_base_wagtail_admin_template_is_extended(self):
        """Test that the right Wagtail admin template is extended."""
        password_reset_form_key_template = get_template("account/password_reset_from_key.html")
        extends_node = next(
            find_nodes(password_reset_form_key_template.template.nodelist, ExtendsNode)
        )

        self.assertEqual(
            extends_node.parent_name.var, "wagtailadmin/account/password_reset/confirm.html"
        )

    def test_urls_in_password_reset_from_key_template(self):
        """Test that all URL names used in the password reset from key template exist."""
        expected_url_names = {"account_reset_password", "account_login", "account_logout"}
        url_names = get_url_names_from_template("account/password_reset_from_key.html")

        self.assertEqual(expected_url_names, url_names)
        for url_name in url_names:
            with self.subTest(url_name=url_name):
                self.assertTrue(reverse(url_name))

    def test_password_reset_from_key_form_and_template_are_used(self):
        """Test that the password reset from key form and template are used."""
        test_user = User.objects.create_user(
            username="testuser",
            password="password",  # noqa: S106
            email="testpasswordreset@example.com",
        )
        self.client.post(reverse("account_reset_password"), {"email": test_user.email})
        reset_url = get_url_from_email(self, test_user.email)
        response = self.client.get(reset_url, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "account/password_reset_from_key.html")

        form = response.context["form"]
        self.assertIn("password1", form.fields)
        self.assertRegex(response.content.decode(), r'<input\b[^>]*\bname="password1"')
        self.assertIn("password2", form.fields)
        self.assertRegex(response.content.decode(), r'<input\b[^>]*\bname="password2"')
        self.assertIn("action_url", response.context)


class TestPasswordResetFromKeyDoneTemplate(SimpleTestCase):
    """Test custom django-allauth password reset from key done template."""

    def test_base_wagtail_admin_template_is_extended(self):
        """Test that the right Wagtail admin template is extended."""
        password_reset_key_done_template = get_template("account/password_reset_from_key_done.html")
        extends_node = next(
            find_nodes(password_reset_key_done_template.template.nodelist, ExtendsNode)
        )

        self.assertEqual(
            extends_node.parent_name.var, "wagtailadmin/account/password_reset/complete.html"
        )

    def test_urls_in_password_reset_from_key_done_template(self):
        """Test that all URL names used in the password reset from key done template exist."""
        expected_url_names = {"account_login"}
        url_names = get_url_names_from_template("account/password_reset_from_key_done.html")

        self.assertEqual(expected_url_names, url_names)
        for url_name in url_names:
            with self.subTest(url_name=url_name):
                self.assertTrue(reverse(url_name))

    def test_password_reset_key_done_template_used(self):
        """Test that the custom allauth password reset template is rendered."""
        response = self.client.get(f"/{settings.ALLAUTH_BASE_URL}password/reset/key/done/")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "account/password_reset_from_key_done.html")
