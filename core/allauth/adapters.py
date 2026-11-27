"""Allauth related code for the project."""

from functools import cached_property
from typing import TYPE_CHECKING

from allauth.account.adapter import DefaultAccountAdapter
from allauth.mfa.adapter import DefaultMFAAdapter
from cryptography.fernet import Fernet, MultiFernet
from django.conf import settings
from django.http import HttpRequest

if TYPE_CHECKING:
    from django.contrib.auth.models import User


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


class SppMFAAdapter(DefaultMFAAdapter):
    """Custom adapter for django-allauth MFA.

    This class extends the DefaultMFAAdapter from django-allauth to customize the
    behaviour of the MFA system.
    """

    def get_totp_issuer(self) -> str:
        """Return the TOTP issuer name displayed in the authenticator app."""

        return settings.WAGTAIL_SITE_NAME

    def get_totp_label(self, user: User) -> str:
        """Return the TOTP label displayed in the authenticator app."""

        return user.username

    def encrypt(self, text: str) -> str:
        """Encrypt the given text using the MultiFernet instance."""

        if not text:
            return text

        return self.fernet.encrypt(text.encode("utf-8")).decode("utf-8")

    def decrypt(self, encrypted_text: str) -> str:
        """Decrypt the given text using the MultiFernet instance."""

        if not encrypted_text:
            return encrypted_text

        return self.fernet.decrypt(encrypted_text.encode("utf-8")).decode("utf-8")

    @cached_property
    def fernet(self) -> MultiFernet:
        """Return a MultiFernet instance for encrypting/decrypting MFA secrets."""

        # The MFA_SECRET_KEY setting is list of 32-byte URL-safe base64-encoded secret keys.
        # Typically, it will contain a single key, but can contain multiple keys for key rotation.
        # If multiple keys are provided, the first key is used for encryption, and all keys are
        # tried for decryption of existing records.
        #
        # IMPORTANT: Old keys should not be removed from the list until all existing records
        # encrypted with those keys have been decrypted and re-encrypted with the new key.
        return MultiFernet([Fernet(key.strip().encode("utf-8")) for key in settings.MFA_SECRET_KEY])
