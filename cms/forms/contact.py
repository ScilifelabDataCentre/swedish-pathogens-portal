"""Contact form definitions and anti-spam validation.

This module defines the ``ContactForm`` used by the contact page. It includes
layered, user-transparent anti-spam checks (honeypot, submission timing, and
double-submit cookie) and content validation.

The form accepts ``request`` in its constructor to access cookies for the
double-submit verification.
"""

from __future__ import annotations

import re
import time
from typing import Any

from django import forms
from django.core import signing
from django.core.exceptions import ValidationError
from django.http import HttpRequest

# Rough URL detector used only for counting links in free-text messages.
# It intentionally ignores bare markers like "www." at the end of a sentence
# by requiring at least one word character after the marker.
URL_REGEX = re.compile(r"(https?://[^\s]+|www\.[^\s]+\.[^\s]+)", re.IGNORECASE)

# Validation and anti-spam constants
MIN_SUBMIT_SECONDS = 2
MAX_URLS_ALLOWED = 10  # TODO discuss this limit
MAX_TOKEN_AGE_SECONDS = 3600 * 4  # TODO discuss this limit
CONTACT_TS_SIGNER = signing.TimestampSigner(salt="contact-ts")


class ContactForm(forms.Form):
    """Contact form with layered anti-spam.

    Fields:
        name: Name of the sender (2-100 chars).
        email: Reply address, validated.
        message: Main text body, 20-5000 chars, with URL and HTML limits.
        category: Multi-select checkbox list, at least one option required.
        website: Honeypot field, must remain empty.
        contact_ts: Signed timestamp token to check submission timing.
        contact_dsc: Token that must match the cookie for double-submit check.

    Anti-spam strategy:
        - Honeypot rejects naive bots filling hidden fields.
        - TimestampSigner token rejects submissions that are too fast (<2s).
        - Double-submit cookie reduces scripted posts and replays.
    """

    name = forms.CharField(min_length=2, max_length=100, required=True)
    email = forms.EmailField(required=True)
    message = forms.CharField(min_length=20, max_length=5000, widget=forms.Textarea)
    category = forms.MultipleChoiceField(
        required=True,
        choices=[
            ("suggestion", "Suggestion for the Portal"),
            ("dm_support", "Request for help with data management or data sharing questions"),
            ("other", "Other"),
        ],
        widget=forms.CheckboxSelectMultiple(
            attrs={
                "class": (
                    "h-4 w-4 rounded border-gray-300 text-teal-600 "
                    "cursor-pointer focus:ring-2 focus:ring-teal-500"
                )
            }
        ),
        error_messages={"required": "Please select at least one alternative."},
    )
    # Anti-spam fields (Honeypot, TimestampSigner token, Double-submit cookie)
    website = forms.CharField(required=False, widget=forms.HiddenInput)
    contact_ts = forms.CharField(required=False, widget=forms.HiddenInput, strip=False)
    contact_dsc = forms.CharField(required=False, widget=forms.HiddenInput, strip=False)

    # Internal state for logging (not exposed to users)
    _blocked_reason: str | None = None

    def __init__(self, *args, request: HttpRequest | None = None, **kwargs) -> None:
        """Initialise the form.

        Args:
            *args: Positional form args.
            request: Optional ``HttpRequest`` to access cookies for token checks.
            **kwargs: Keyword form args.
        """
        super().__init__(*args, **kwargs)
        self.request = request

    def clean_email(self) -> str:
        """Validate email and prevent header injection.

        Returns:
            The sanitised email value.

        Raises:
            ValidationError: If CR/LF characters are present.
        """
        value = self.cleaned_data.get("email", "")
        if "\r" in value or "\n" in value:
            raise ValidationError("Enter a valid email address.")
        return value

    def clean_message(self) -> str:
        """Validate message content against HTML and URL constraints.

        Returns:
            The validated message content.

        Raises:
            ValidationError: If HTML-like tags are present or URL count exceeds
                the allowed threshold.
        """
        value = self.cleaned_data.get("message", "")
        # Reject HTML-like tags
        if re.search(r"</?[A-Za-z][^>]*>", value):
            raise ValidationError("Please remove HTML tags.")
        # Cap URLs
        url_count = len(URL_REGEX.findall(value))
        if url_count > MAX_URLS_ALLOWED:
            raise ValidationError("Too many links in the message.")
        return value

    def clean(self) -> dict[str, Any]:
        """Run form-level validation for honeypot, token, cookie, and timing checks.

        Returns:
            The cleaned data dictionary.

        Raises:
            ValidationError: On any anti-spam or category selection failure.
        """
        cleaned = super().clean()

        # Honeypot
        if cleaned.get("website"):
            self._blocked_reason = "HONEYPOT_HIT"
            raise ValidationError("We couldn't submit the form. Please try again in a moment.")

        # Timing token: verify signature and age, but defer "too fast" check
        # until after the double-submit cookie check so cookie mismatches are
        # consistently reported as TOKEN_MISMATCH.
        ts_token = cleaned.get("contact_ts") or ""
        try:
            ts_str = CONTACT_TS_SIGNER.unsign(ts_token, max_age=MAX_TOKEN_AGE_SECONDS)
            ts = float(ts_str)
        except (signing.BadSignature, ValueError) as err:
            self._blocked_reason = "TOKEN_BAD_SIGNATURE"
            raise ValidationError(
                "We couldn't submit the form. Please try again in a moment."
            ) from err

        # Double-submit cookie check
        posted_token = cleaned.get("contact_dsc") or ""
        cookie_token = None
        if hasattr(self, "request") and self.request is not None:
            cookie_token = self.request.COOKIES.get("contact_dsc")

        if not cookie_token or cookie_token != posted_token:
            self._blocked_reason = "TOKEN_MISMATCH"
            raise ValidationError("We couldn't submit the form. Please try again in a moment.")

        # Minimum submit duration check - only evaluated once the cookie
        # matches, so cookie-related failures are not masked by timing.
        now = time.time()
        if now - ts < MIN_SUBMIT_SECONDS:
            self._blocked_reason = "TOO_FAST"
            raise ValidationError("We couldn't submit the form. Please try again in a moment.")

        return cleaned
