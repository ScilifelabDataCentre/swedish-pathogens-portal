"""Tests for the custom allauth adapter."""

from cryptography.fernet import Fernet, InvalidToken
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import reverse

from core.allauth.adapters import SppAllauthAdapter, SppMFAAdapter


class TestSppAllauthAdapter(SimpleTestCase):
    """Test the custom allauth adapter."""

    def setUp(self):
        """Set up the test case."""
        self.adapter = SppAllauthAdapter()
        self.request = RequestFactory().get(reverse("account_signup"))

    def test_signup_is_disabled(self):
        """Test that the signup is disabled."""
        self.assertFalse(self.adapter.is_open_for_signup(self.request))


key_a = Fernet.generate_key().decode()
key_b = Fernet.generate_key().decode()


class TestSppMFAAdapter(SimpleTestCase):
    """Tests for MFA secret encryption and decryption."""

    def setUp(self):
        """Set up the test case."""
        self.adapter = SppMFAAdapter()

    @override_settings(WAGTAIL_SITE_NAME="My Wagtail Site")
    def test_get_totp_issuer(self):
        """Test that the TOTP issuer uses the Wagtail site name."""

        self.assertEqual(self.adapter.get_totp_issuer(), "My Wagtail Site")

    def test_get_totp_label(self):
        """Test that the TOTP label uses the user's username."""
        user = type("User", (), {"username": "testuser"})()

        self.assertEqual(self.adapter.get_totp_label(user), "testuser")

    @override_settings(MFA_SECRET_KEY=[])
    def test_encrypt_empty_string(self):
        """Test that encrypting an empty string returns an empty string."""

        self.assertEqual(self.adapter.encrypt(""), "")

    @override_settings(MFA_SECRET_KEY=[])
    def test_decrypt_empty_string(self):
        """Test that decrypting an empty string returns an empty string."""

        self.assertEqual(self.adapter.decrypt(""), "")

    @override_settings(MFA_SECRET_KEY=[key_a])
    def test_encrypt_and_decrypt(self):
        """Test that encrypted text can be decrypted to its original value."""
        plaintext = "my-secret-totp-key"
        encrypted = self.adapter.encrypt(plaintext)

        self.assertNotEqual(encrypted, plaintext)
        self.assertEqual(self.adapter.decrypt(encrypted), plaintext)

    @override_settings(MFA_SECRET_KEY=[key_b, key_a])
    def test_encrypt_uses_first_key(self):
        """Test that encryption uses the first configured Fernet key."""
        plaintext = "my-secret-totp-key"
        encrypted = self.adapter.encrypt(plaintext)
        key_b_fernet = Fernet(key_b.encode("utf-8"))

        self.assertEqual(key_b_fernet.decrypt(encrypted.encode("utf-8")).decode("utf-8"), plaintext)

    @override_settings(MFA_SECRET_KEY=[key_b, key_a])
    def test_decrypt_uses_previous_key(self):
        """Test that decryption supports data encrypted with an older key."""
        plaintext = "my-secret-totp-key"
        old_fernet = Fernet(key_a.encode("utf-8"))
        encrypted = old_fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")

        self.assertEqual(self.adapter.decrypt(encrypted), plaintext)

    @override_settings(MFA_SECRET_KEY=[key_a])
    def test_decrypt_invalid_token(self):
        """Test that decryption raises InvalidToken for invalid ciphertext."""

        with self.assertRaises(InvalidToken):
            self.adapter.decrypt("invalid-encrypted-value")

    @override_settings(MFA_SECRET_KEY=[key_a])
    def test_fernet_is_cached(self):
        """Test that the MultiFernet instance is cached."""
        first_instance = self.adapter.fernet
        second_instance = self.adapter.fernet

        self.assertIs(first_instance, second_instance)
