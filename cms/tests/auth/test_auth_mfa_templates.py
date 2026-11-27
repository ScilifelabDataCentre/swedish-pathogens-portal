"""Tests for the authentication 'mfa' templates."""

from allauth.mfa.adapter import get_adapter
from allauth.mfa.models import Authenticator
from django.conf import settings
from django.contrib.auth.models import User
from django.template.loader import get_template
from django.template.loader_tags import ExtendsNode
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from cms.tests.utils import find_nodes, get_url_names_from_template


class TestSppMfaBaseTemplate(SimpleTestCase):
    """Test custom spp mfa base template."""

    def test_base_wagtail_admin_template_is_extended(self):
        """Test that the right Wagtail admin template is extended."""
        login_template = get_template("mfa/spp_mfa_base.html")
        extends_node = next(find_nodes(login_template.template.nodelist, ExtendsNode))

        self.assertEqual(extends_node.parent_name.var, "wagtailadmin/base.html")


class TestMfaIndexTemplate(TestCase):
    """Test the mfa index template."""

    def test_mfa_index_template_extends_spp_mfa_base_template(self):
        """Test that the mfa index template extends the spp mfa base template."""
        login_template = get_template("mfa/index.html")
        extends_node = next(find_nodes(login_template.template.nodelist, ExtendsNode))

        self.assertEqual(extends_node.parent_name.var, "mfa/spp_mfa_base.html")

    def test_mfa_index_template_contains_expected_url_names(self):
        """Test that the mfa index template contains the expected url names."""
        expected_url_names = {
            "mfa_activate_totp",
            "mfa_deactivate_totp",
            "mfa_view_recovery_codes",
            "mfa_download_recovery_codes",
            "mfa_generate_recovery_codes",
            "wagtailadmin_account",
        }
        url_names = get_url_names_from_template("mfa/index.html")

        self.assertEqual(expected_url_names, url_names)
        for url_name in url_names:
            with self.subTest(url_name=url_name):
                self.assertTrue(reverse(url_name))

    def test_mfa_index_template_expected_context_names(self):
        """Test that the mfa index template contains the expected context names."""
        test_user = User.objects.create_user(username="testuser", password="password")  # noqa: S106
        self.client.force_login(test_user)
        response = self.client.get(f"/{settings.ALLAUTH_BASE_URL}2fa/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("MFA_SUPPORTED_TYPES", response.context)
        self.assertIn("authenticators", response.context)

    def test_mfa_index_template_is_used(self):
        """Test that the MFA index template is used."""
        test_user = User.objects.create_user(username="testuser", password="password")  # noqa: S106
        self.client.force_login(test_user)
        response = self.client.get(f"/{settings.ALLAUTH_BASE_URL}2fa/")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "mfa/index.html")


class TestMfaTotpActivateFormTemplate(TestCase):
    """Test the mfa totp activate form template."""

    def test_mfa_totp_activate_form_template_extends_spp_mfa_base_template(self):
        """Test that the mfa totp activate form template extends the spp mfa base template."""
        login_template = get_template("mfa/totp/activate_form.html")
        extends_node = next(find_nodes(login_template.template.nodelist, ExtendsNode))

        self.assertEqual(extends_node.parent_name.var, "mfa/spp_mfa_base.html")

    def test_mfa_totp_activate_form_template_contains_expected_url_names(self):
        """Test that the mfa totp activate form template contains the expected url names."""
        expected_url_names = {
            "mfa_activate_totp",
            "mfa_index",
            "wagtailadmin_account",
        }
        url_names = get_url_names_from_template("mfa/totp/activate_form.html")

        self.assertEqual(expected_url_names, url_names)
        for url_name in url_names:
            with self.subTest(url_name=url_name):
                self.assertTrue(reverse(url_name))

    @override_settings(MFA_REAUTHENTICATION_REQUIRED=False)
    def test_mfa_totp_activate_form_template_expected_context_names(self):
        """Test that the mfa totp activate form template contains the expected context names."""
        test_user = User.objects.create_user(username="testuser", password="password")  # noqa: S106
        self.client.force_login(test_user)
        response = self.client.get(f"/{settings.ALLAUTH_BASE_URL}2fa/totp/activate/")
        form = response.context["form"]

        self.assertEqual(response.status_code, 200)
        self.assertTrue(hasattr(form, "secret"))
        self.assertIn("code", form.fields)
        self.assertIn("totp_svg_data_uri", response.context)

    @override_settings(MFA_REAUTHENTICATION_REQUIRED=False)
    def test_mfa_activate_form_template_is_used(self):
        """Test that the MFA activate template is used."""
        test_user = User.objects.create_user(username="testuser", password="password")  # noqa: S106
        self.client.force_login(test_user)
        response = self.client.get(f"/{settings.ALLAUTH_BASE_URL}2fa/totp/activate/")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "mfa/totp/activate_form.html")


class TestMfaTotpDeactivateFormTemplate(TestCase):
    """Test the mfa totp deactivate form template."""

    def test_mfa_totp_deactivate_form_template_extends_spp_mfa_base_template(self):
        """Test that the mfa totp deactivate form template extends the spp mfa base template."""
        login_template = get_template("mfa/totp/deactivate_form.html")
        extends_node = next(find_nodes(login_template.template.nodelist, ExtendsNode))

        self.assertEqual(extends_node.parent_name.var, "mfa/spp_mfa_base.html")

    def test_mfa_totp_deactivate_form_template_contains_expected_url_names(self):
        """Test that the mfa totp deactivate form template contains the expected url names."""
        expected_url_names = {
            "mfa_deactivate_totp",
            "mfa_index",
            "wagtailadmin_account",
        }
        url_names = get_url_names_from_template("mfa/totp/deactivate_form.html")

        self.assertEqual(expected_url_names, url_names)
        for url_name in url_names:
            with self.subTest(url_name=url_name):
                self.assertTrue(reverse(url_name))

    @override_settings(MFA_REAUTHENTICATION_REQUIRED=False)
    def test_mfa_deactivate_form_template_is_used(self):
        """Test that the MFA deactivate template is used."""
        test_user = User.objects.create_user(username="testuser", password="password")  # noqa: S106
        self.client.force_login(test_user)
        Authenticator.objects.create(
            user=test_user, type=Authenticator.Type.TOTP, data={"secret": "12345678901234567890"}
        )
        response = self.client.get(f"/{settings.ALLAUTH_BASE_URL}2fa/totp/deactivate/")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "mfa/totp/deactivate_form.html")


class TestMfaAuthenticateTemplate(TestCase):
    """Test custom django-allauth MFA authenticate template."""

    def test_base_wagtail_admin_template_is_extended(self):
        """Test that the right Wagtail admin template is extended."""
        authenticate_template = get_template("mfa/authenticate.html")
        extends_node = next(find_nodes(authenticate_template.template.nodelist, ExtendsNode))

        self.assertEqual(extends_node.parent_name.var, "wagtailadmin/admin_base.html")

    def test_urls_in_mfa_authenticate_template(self):
        """Test that all URL names used in the MFA authenticate template exist."""
        expected_url_names = {"mfa_authenticate", "account_login", "account_logout"}
        url_names = get_url_names_from_template("mfa/authenticate.html")

        self.assertEqual(expected_url_names, url_names)
        for url_name in url_names:
            with self.subTest(url_name=url_name):
                self.assertTrue(reverse(url_name))

    def test_mfa_authenticate_template_form_and_context(self):
        """Test that the authenticate form and context values are used."""
        test_user = User.objects.create_user(username="testuser", password="password")  # noqa: S106
        Authenticator.objects.create(
            user=test_user, type=Authenticator.Type.TOTP, data={"secret": "12345678901234567890"}
        )
        response = self.client.post(
            reverse("account_login"), {"login": "testuser", "password": "password"}, follow=True
        )

        self.assertEqual(response.status_code, 200)

        form = response.context["form"]
        self.assertIn("code", form.fields)
        self.assertRegex(response.content.decode(), r'<input\b[^>]*\bname="code"')

    def test_mfa_authenticate_template_used(self):
        """Test that the custom allauth MFA authenticate template is rendered."""
        test_user = User.objects.create_user(username="testuser", password="password")  # noqa: S106
        Authenticator.objects.create(
            user=test_user, type=Authenticator.Type.TOTP, data={"secret": "12345678901234567890"}
        )
        response = self.client.post(
            reverse("account_login"), {"login": "testuser", "password": "password"}, follow=True
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "mfa/authenticate.html")


class TestMfaReauthenticateTemplate(TestCase):
    """Test custom django-allauth MFA reauthenticate template."""

    def test_base_wagtail_admin_template_is_extended(self):
        """Test that the right Wagtail admin template is extended."""
        reauthenticate_template = get_template("mfa/reauthenticate.html")
        extends_node = next(find_nodes(reauthenticate_template.template.nodelist, ExtendsNode))

        self.assertEqual(extends_node.parent_name.var, "wagtailadmin/admin_base.html")

    def test_urls_in_reauthenticate_template(self):
        """Test that all URL names used in the reauthenticate template exist."""
        expected_url_names = {"mfa_reauthenticate"}
        url_names = get_url_names_from_template("mfa/reauthenticate.html")

        self.assertEqual(expected_url_names, url_names)
        for url_name in url_names:
            with self.subTest(url_name=url_name):
                self.assertTrue(reverse(url_name))

    def test_reauthenticate_template_form_and_context(self):
        """Test that the reauthenticate form and context values are used."""
        test_user = User.objects.create_user(username="testuser", password="password")  # noqa: S106
        self.client.force_login(test_user)
        Authenticator.objects.create(
            user=test_user, type=Authenticator.Type.TOTP, data={"secret": "12345678901234567890"}
        )
        response = self.client.get(reverse("mfa_reauthenticate"))

        self.assertEqual(response.status_code, 200)

        form = response.context["form"]
        self.assertIn("code", form.fields)
        self.assertRegex(response.content.decode(), r'<input\b[^>]*\bname="code"')
        self.assertIn("reauthentication_alternatives", response.context)

    def test_reauthenticate_template_used(self):
        """Test that the custom allauth reauthenticate template is rendered."""
        test_user = User.objects.create_user(username="testuser", password="password")  # noqa: S106
        self.client.force_login(test_user)
        Authenticator.objects.create(
            user=test_user, type=Authenticator.Type.TOTP, data={"secret": "12345678901234567890"}
        )
        response = self.client.get(reverse("mfa_reauthenticate"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "mfa/reauthenticate.html")


class TestMfaRecoveryCodesTemplate(TestCase):
    """Test custom django-allauth MFA recovery codes template."""

    def test_base_wagtail_admin_template_is_extended(self):
        """Test that the right Wagtail admin template is extended."""
        recovery_codes_template = get_template("mfa/recovery_codes/index.html")
        extends_node = next(find_nodes(recovery_codes_template.template.nodelist, ExtendsNode))

        self.assertEqual(extends_node.parent_name.var, "mfa/spp_mfa_base.html")

    def test_urls_in_recovery_codes_template(self):
        """Test that all URL names used in the recovery codes template exist."""
        expected_url_names = {
            "mfa_index",
            "mfa_download_recovery_codes",
            "mfa_generate_recovery_codes",
            "wagtailadmin_account",
        }
        url_names = get_url_names_from_template("mfa/recovery_codes/index.html")

        self.assertEqual(expected_url_names, url_names)
        for url_name in url_names:
            with self.subTest(url_name=url_name):
                self.assertTrue(reverse(url_name))

    @override_settings(MFA_REAUTHENTICATION_REQUIRED=False)
    def test_recovery_codes_template_expected_context_names(self):
        """Test that the recovery codes template contains the expected context names."""
        test_user = User.objects.create_user(username="testuser", password="password")  # noqa: S106
        self.client.force_login(test_user)
        Authenticator.objects.create(
            user=test_user, type=Authenticator.Type.TOTP, data={"secret": "12345678901234567890"}
        )
        Authenticator.objects.create(
            user=test_user,
            type=Authenticator.Type.RECOVERY_CODES,
            data={"migrated_codes": [get_adapter().encrypt("testcode1")]},
        )
        response = self.client.get(reverse("mfa_view_recovery_codes"))

        self.assertEqual(response.status_code, 200)
        self.assertIn("unused_codes", response.context)
        self.assertIn("total_count", response.context)
        self.assertIn("can_download_codes", response.context)
        self.assertIn("can_generate_codes", response.context)
        self.assertIn("can_view_codes", response.context)

    @override_settings(MFA_REAUTHENTICATION_REQUIRED=False)
    def test_recovery_codes_template_is_used(self):
        """Test that the recovery codes template is used."""
        test_user = User.objects.create_user(username="testuser", password="password")  # noqa: S106
        self.client.force_login(test_user)
        Authenticator.objects.create(
            user=test_user, type=Authenticator.Type.TOTP, data={"secret": "12345678901234567890"}
        )
        Authenticator.objects.create(
            user=test_user,
            type=Authenticator.Type.RECOVERY_CODES,
            data={"migrated_codes": [get_adapter().encrypt("testcode1")]},
        )
        response = self.client.get(reverse("mfa_view_recovery_codes"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "mfa/recovery_codes/index.html")


class TestMfaRecoveryCodesGenerateTemplate(TestCase):
    """Test custom django-allauth MFA recovery codes generate template."""

    def test_base_wagtail_admin_template_is_extended(self):
        """Test that the right Wagtail admin template is extended."""
        recovery_codes_generate_template = get_template("mfa/recovery_codes/generate.html")
        extends_node = next(
            find_nodes(recovery_codes_generate_template.template.nodelist, ExtendsNode)
        )

        self.assertEqual(extends_node.parent_name.var, "mfa/spp_mfa_base.html")

    def test_urls_in_recovery_codes_generate_template(self):
        """Test that all URL names used in the recovery codes generate template exist."""
        expected_url_names = {
            "mfa_index",
            "mfa_generate_recovery_codes",
            "mfa_view_recovery_codes",
            "wagtailadmin_account",
        }
        url_names = get_url_names_from_template("mfa/recovery_codes/generate.html")

        self.assertEqual(expected_url_names, url_names)
        for url_name in url_names:
            with self.subTest(url_name=url_name):
                self.assertTrue(reverse(url_name))

    @override_settings(MFA_REAUTHENTICATION_REQUIRED=False)
    def test_recovery_codes_generate_template_expected_context_names(self):
        """Test that the recovery codes generate template contains the expected context names."""
        test_user = User.objects.create_user(username="testuser", password="password")  # noqa: S106
        self.client.force_login(test_user)
        Authenticator.objects.create(
            user=test_user, type=Authenticator.Type.TOTP, data={"secret": "12345678901234567890"}
        )
        Authenticator.objects.create(
            user=test_user,
            type=Authenticator.Type.RECOVERY_CODES,
            data={"migrated_codes": [get_adapter().encrypt("testcode1")]},
        )
        response = self.client.get(reverse("mfa_generate_recovery_codes"))

        self.assertEqual(response.status_code, 200)
        self.assertIn("unused_code_count", response.context)

    @override_settings(MFA_REAUTHENTICATION_REQUIRED=False)
    def test_recovery_codes_generate_template_is_used(self):
        """Test that the recovery codes generate template is used."""
        test_user = User.objects.create_user(username="testuser", password="password")  # noqa: S106
        self.client.force_login(test_user)
        Authenticator.objects.create(
            user=test_user, type=Authenticator.Type.TOTP, data={"secret": "12345678901234567890"}
        )
        Authenticator.objects.create(
            user=test_user,
            type=Authenticator.Type.RECOVERY_CODES,
            data={"migrated_codes": [get_adapter().encrypt("testcode1")]},
        )
        response = self.client.get(reverse("mfa_generate_recovery_codes"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "mfa/recovery_codes/generate.html")
