"""Tests for the contact page (model, view, form, template, and preview path)."""

from __future__ import annotations

import re
import time
from typing import Any
from unittest.mock import patch

import structlog.testing
from django.conf import settings
from django.core import mail
from django.http import HttpResponse
from django.test import Client, RequestFactory, override_settings
from wagtail.models import Page, Site

from cms.forms.contact import (
    CONTACT_TS_SIGNER,
    MAX_TOKEN_AGE_SECONDS,
    MAX_URLS_ALLOWED,
    MIN_SUBMIT_SECONDS,
)
from cms.pages import ContactPage, HomePage
from cms.tests.test_navigation_menu import TestCaseWithSite

BEFORE_FORM_STREAM = [("text", "<p>Get in touch with the Portal team.</p>")]
AFTER_FORM_STREAM = [("text", "<p>We process your data lawfully under GDPR.</p>")]

NAME_LITERAL = "AliceUniqueAgentLiteral"
EMAIL_LITERAL = "alice.unique.literal@example.org"
MESSAGE_LITERAL = (
    "ZZZUNIQUEMESSAGELITERALZZZ this is a contact-form message body that is long enough."
)


def _flatten_log_value(value: object) -> str:
    """Return a flat string representation of a structlog event value.

    Walks dicts/lists/tuples recursively so nested kwargs cannot hide a leaked
    PII substring during the user-content-absent-from-logs assertion.

    Args:
        value: Any value pulled out of a captured structlog record.

    Returns:
        A single-line string concatenation of every leaf value.
    """
    if isinstance(value, dict):
        return " ".join(_flatten_log_value(v) for v in value.values())
    if isinstance(value, (list, tuple, set)):
        return " ".join(_flatten_log_value(v) for v in value)
    return str(value)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="Pathogens Portal Test <test@example.org>",
    CONTACT_RECIPIENT_EMAIL="contact-test@example.org",
)
class ContactPageTests(TestCaseWithSite):
    """End-to-end tests for ``ContactPage`` covering form, view, and preview."""

    def setUp(self) -> None:
        """Build a fresh ``HomePage`` + ``ContactPage`` tree under the site root."""
        super().setUp()
        for child in self.root.get_children():
            child.delete()
        self.root = Page.objects.get(id=1)

        self.home = HomePage(title="Home", slug="home")
        self.root.add_child(instance=self.home)
        self.home.save_revision().publish()

        self.page = ContactPage(
            title="Contact",
            slug="contact",
            before_form=BEFORE_FORM_STREAM,
            after_form=AFTER_FORM_STREAM,
        )
        self.home.add_child(instance=self.page)
        self.page.save_revision().publish()

        Site.objects.update_or_create(
            is_default_site=True,
            defaults={"hostname": "testserver", "root_page": self.home},
        )
        self.page_url = self.page.url
        self.client = Client()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_tokens_from_response(self, response: HttpResponse) -> tuple[str | None, str | None]:
        """Pull ``contact_ts`` and ``contact_dsc`` hidden values out of rendered HTML."""
        content = response.content.decode()
        ts_match = re.search(r'name="contact_ts" value="([^"]+)"', content)
        dsc_match = re.search(r'name="contact_dsc" value="([^"]+)"', content)
        ts = ts_match.group(1) if ts_match else None
        dsc = dsc_match.group(1) if dsc_match else None
        return ts, dsc

    def _get_fresh_tokens(self) -> tuple[str, str]:
        """GET the contact page and return the rendered ``(ts, dsc)`` token pair."""
        response = self.client.get(self.page_url)
        ts, dsc = self._get_tokens_from_response(response)
        if ts is None or dsc is None:
            self.fail("Contact form did not render anti-spam tokens.")
        return ts, dsc

    def _age_timestamp_token(self, _ts_token: str) -> str:
        """Re-sign a timestamp old enough to satisfy the ``MIN_SUBMIT_SECONDS`` gate."""
        now = int(time.time())
        aged_value = str(now - (MIN_SUBMIT_SECONDS + 1))
        return CONTACT_TS_SIGNER.sign(aged_value)

    def _build_post_data(
        self,
        ts: str,
        dsc: str,
        *,
        name: str = NAME_LITERAL,
        email: str = EMAIL_LITERAL,
        message: str = MESSAGE_LITERAL,
        category: list[str] | None = None,
        website: str = "",
    ) -> dict[str, Any]:
        """Return a baseline-valid POST payload for the contact form."""
        return {
            "name": name,
            "email": email,
            "message": message,
            "category": category if category is not None else ["suggestion"],
            "website": website,
            "contact_ts": ts,
            "contact_dsc": dsc,
        }

    def _filter_submit_logs(self, logs: list[dict[str, Any]], outcome: str) -> list[dict[str, Any]]:
        """Return only ``contact_submit`` records whose event matches ``outcome``."""
        marker = f"event=contact_submit outcome={outcome}"
        return [r for r in logs if r.get("event") == marker]

    def _assert_blocked(
        self,
        logs: list[dict[str, Any]],
        expected_reason: str,
    ) -> dict[str, Any]:
        """Assert exactly one ``outcome=blocked`` log with ``reason`` and ``duration_ms``."""
        blocked = self._filter_submit_logs(logs, "blocked")
        self.assertEqual(len(blocked), 1, blocked)
        record = blocked[0]
        self.assertEqual(record.get("reason"), expected_reason, record)
        self.assertIn("duration_ms", record)
        self.assertIsInstance(record["duration_ms"], int)
        return record

    # ------------------------------------------------------------------
    # GET render + cookie set
    # ------------------------------------------------------------------

    def test_get_renders_form_and_sets_dsc_cookie(self):
        """GET renders the form with hidden tokens and sets the ``contact_dsc`` cookie."""
        response = self.client.get(self.page_url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("contact_dsc", response.cookies)
        self.assertTrue(response.cookies["contact_dsc"]["httponly"])
        ts, dsc = self._get_tokens_from_response(response)
        self.assertIsNotNone(ts)
        self.assertIsNotNone(dsc)
        self.assertEqual(response.cookies["contact_dsc"].value, dsc)

    # ------------------------------------------------------------------
    # Happy-path send
    # ------------------------------------------------------------------

    def test_happy_post_sends_one_email_no_db_writes_and_success_log_has_no_reason(self):
        """Valid submission sends one email, leaves no DB row, logs success without reason."""
        ts, dsc = self._get_fresh_tokens()
        ts = self._age_timestamp_token(ts)
        post = self._build_post_data(ts, dsc)

        contact_count_before = ContactPage.objects.count()
        with structlog.testing.capture_logs() as logs:
            response = self.client.post(self.page_url, data=post, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, "[Contact] Contact and suggestions form")
        self.assertEqual(ContactPage.objects.count(), contact_count_before)

        success = self._filter_submit_logs(logs, "success")
        self.assertEqual(len(success), 1)
        record = success[0]
        self.assertNotIn("reason", record)
        self.assertIn("duration_ms", record)
        self.assertIsInstance(record["duration_ms"], int)
        self.assertEqual(self._filter_submit_logs(logs, "blocked"), [])
        self.assertEqual(self._filter_submit_logs(logs, "error"), [])

    # ------------------------------------------------------------------
    # Reason-code coverage
    # ------------------------------------------------------------------

    def test_honeypot_blocks(self):
        """A non-empty honeypot ``website`` field blocks with reason ``HONEYPOT_HIT``."""
        ts, dsc = self._get_fresh_tokens()
        ts = self._age_timestamp_token(ts)
        post = self._build_post_data(ts, dsc, website="bot-was-here")

        with structlog.testing.capture_logs() as logs:
            response = self.client.post(self.page_url, data=post)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mail.outbox, [])
        self._assert_blocked(logs, "HONEYPOT_HIT")

    def test_honeypot_precedes_other_anti_spam_checks(self):
        """Honeypot fires first even when token, cookie, AND timing would also fail.

        Pins the ``ContactForm.clean()`` ordering (honeypot → token signature
        → cookie → timing). The request below trips every layer simultaneously:
        the honeypot is filled, the signed timestamp is malformed, the
        double-submit cookie is missing, and the timestamp is fresh
        (under ``MIN_SUBMIT_SECONDS``). A regression that re-orders the checks
        would emit ``TOKEN_BAD_SIGNATURE``, ``TOKEN_MISMATCH``, or
        ``TOO_FAST`` instead of ``HONEYPOT_HIT`` and trip ``_assert_blocked``.
        """
        # Mint a cookie via GET, then drop it so the double-submit check fails.
        self._get_fresh_tokens()
        self.client.cookies.pop("contact_dsc", None)

        post = self._build_post_data(
            ts="not-a-real-signed-token",
            dsc="any-hidden-value-not-matching-cookie",
            website="bot-was-here",
        )

        with structlog.testing.capture_logs() as logs:
            response = self.client.post(self.page_url, data=post)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mail.outbox, [])
        self._assert_blocked(logs, "HONEYPOT_HIT")

    def test_too_fast_blocks_after_cookie_ok(self):
        """Posting under ``MIN_SUBMIT_SECONDS`` after mint is blocked as ``TOO_FAST``."""
        ts, dsc = self._get_fresh_tokens()
        post = self._build_post_data(ts, dsc)

        with structlog.testing.capture_logs() as logs:
            response = self.client.post(self.page_url, data=post)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mail.outbox, [])
        self._assert_blocked(logs, "TOO_FAST")

    def test_token_mismatch_blocks(self):
        """Missing cookie, missing hidden, or mismatched values all yield ``TOKEN_MISMATCH``."""
        with self.subTest("missing cookie"):
            ts, dsc = self._get_fresh_tokens()
            self.client.cookies.pop("contact_dsc", None)
            post = self._build_post_data(ts, dsc)
            with structlog.testing.capture_logs() as logs:
                response = self.client.post(self.page_url, data=post)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(mail.outbox, [])
            self._assert_blocked(logs, "TOKEN_MISMATCH")

        with self.subTest("missing hidden"):
            self.client = Client()
            ts, dsc = self._get_fresh_tokens()
            post = self._build_post_data(ts, dsc)
            post["contact_dsc"] = ""
            with structlog.testing.capture_logs() as logs:
                response = self.client.post(self.page_url, data=post)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(mail.outbox, [])
            self._assert_blocked(logs, "TOKEN_MISMATCH")

        with self.subTest("mismatched"):
            self.client = Client()
            ts, _dsc = self._get_fresh_tokens()
            post = self._build_post_data(ts, "definitely-not-the-cookie")
            with structlog.testing.capture_logs() as logs:
                response = self.client.post(self.page_url, data=post)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(mail.outbox, [])
            self._assert_blocked(logs, "TOKEN_MISMATCH")

    def test_token_bad_signature_blocks(self):
        """Malformed or expired timestamp tokens yield ``TOKEN_BAD_SIGNATURE``."""
        with self.subTest("malformed signature"):
            _ts, dsc = self._get_fresh_tokens()
            post = self._build_post_data("not-a-real-signed-token", dsc)
            with structlog.testing.capture_logs() as logs:
                response = self.client.post(self.page_url, data=post)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(mail.outbox, [])
            self._assert_blocked(logs, "TOKEN_BAD_SIGNATURE")

        with self.subTest("expired token"):
            self.client = Client()
            _ts, dsc = self._get_fresh_tokens()
            past_time = int(time.time()) - MAX_TOKEN_AGE_SECONDS - 100
            with patch("django.core.signing.time.time", return_value=past_time):
                expired_ts = CONTACT_TS_SIGNER.sign(str(past_time))
            post = self._build_post_data(expired_ts, dsc)
            with structlog.testing.capture_logs() as logs:
                response = self.client.post(self.page_url, data=post)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(mail.outbox, [])
            self._assert_blocked(logs, "TOKEN_BAD_SIGNATURE")

    def test_validation_error_blocks(self):
        """Field-level errors yield ``VALIDATION_ERROR`` with empty outbox."""
        cases = {
            "empty_message": {"message": ""},
            "over_cap_length": {"message": "x" * 5001},
            "html_tag": {"message": "<b>hi there everyone</b> please help"},
            "header_injection": {"email": "evil@example.org\nBcc: attacker@example.org"},
            "blank_name": {"name": ""},
            "blank_email": {"email": ""},
            "no_category": {"category": []},
            "invalid_category": {"category": ["nope-not-a-real-choice"]},
        }

        for label, override in cases.items():
            with self.subTest(label):
                self.client = Client()
                ts, dsc = self._get_fresh_tokens()
                ts = self._age_timestamp_token(ts)
                post = self._build_post_data(ts, dsc, **override)
                with structlog.testing.capture_logs() as logs:
                    response = self.client.post(self.page_url, data=post)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(mail.outbox, [])
                self._assert_blocked(logs, "VALIDATION_ERROR")

    def test_too_many_urls_blocks_submission(self):
        """Posting more than ``MAX_URLS_ALLOWED`` URLs blocks as ``VALIDATION_ERROR``.

        Beyond the original outbox-empty / blocked-log asserts, this also pins
        two regression surfaces: (a) the re-rendered ``form.errors["message"]``
        carries the URL-cap error string so a regression that drops or relabels
        the cap is caught here rather than leaking through ``clean_message``,
        and (b) ``ContactPage.objects.count()`` is unchanged across the POST,
        proving the blocked path performs no DB writes against the page table.
        """
        ts, dsc = self._get_fresh_tokens()
        ts = self._age_timestamp_token(ts)
        message = " ".join(f"https://{i}.example.org/path" for i in range(MAX_URLS_ALLOWED + 1))
        post = self._build_post_data(ts, dsc, message=message)

        contact_count_before = ContactPage.objects.count()

        with structlog.testing.capture_logs() as logs:
            response = self.client.post(self.page_url, data=post)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mail.outbox, [])
        self._assert_blocked(logs, "VALIDATION_ERROR")

        self.assertEqual(ContactPage.objects.count(), contact_count_before)

        form = response.context["form"]
        self.assertIn("message", form.errors)
        self.assertIn("Too many links in the message.", form.errors["message"])

    def test_email_send_error_path(self):
        """Backend ``.send()`` failure logs ``EMAIL_SEND_ERROR`` and re-renders with feedback."""
        ts, dsc = self._get_fresh_tokens()
        ts = self._age_timestamp_token(ts)
        post = self._build_post_data(ts, dsc)

        with (
            patch(
                "cms.views.contact.EmailMessage.send",
                side_effect=Exception("backend boom secret"),
            ) as mock_send,
            structlog.testing.capture_logs() as logs,
        ):
            response = self.client.post(self.page_url, data=post)

        mock_send.assert_called_once()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mail.outbox, [])
        self.assertContains(response, "Sorry, we couldn")

        self.assertNotIn(b"backend boom secret", response.content)
        self.assertNotIn(b"Traceback", response.content)
        self.assertNotIn(b"Exception(", response.content)

        error_logs = self._filter_submit_logs(logs, "error")
        self.assertEqual(len(error_logs), 1)
        record = error_logs[0]
        self.assertEqual(record.get("reason"), "EMAIL_SEND_ERROR")
        self.assertIn("duration_ms", record)
        self.assertIsInstance(record["duration_ms"], int)

        ts2, dsc2 = self._get_tokens_from_response(response)
        self.assertIsNotNone(ts2)
        self.assertIsNotNone(dsc2)
        cookie = response.cookies.get("contact_dsc")
        self.assertIsNotNone(cookie)
        self.assertEqual(cookie.value, dsc2)

    # ------------------------------------------------------------------
    # CSRF + cookie + token rotation
    # ------------------------------------------------------------------

    def test_csrf_enforced(self):
        """POST without a CSRF token returns 403 with empty outbox and no submit log."""
        client = Client(enforce_csrf_checks=True)
        client.get(self.page_url)
        with structlog.testing.capture_logs() as logs:
            response = client.post(self.page_url, data={})

        self.assertEqual(response.status_code, 403)
        self.assertEqual(mail.outbox, [])
        self.assertEqual(self._filter_submit_logs(logs, "success"), [])
        self.assertEqual(self._filter_submit_logs(logs, "blocked"), [])
        self.assertEqual(self._filter_submit_logs(logs, "error"), [])

    def test_head_request_does_not_log_or_send(self):
        """HEAD is routed through the GET render path: no email, no submit log."""
        with (
            patch("cms.views.contact.EmailMessage.send") as mock_send,
            structlog.testing.capture_logs() as logs,
        ):
            response = self.client.head(self.page_url)

        self.assertEqual(response.status_code, 200)
        mock_send.assert_not_called()
        self.assertEqual(mail.outbox, [])
        self.assertEqual(self._filter_submit_logs(logs, "success"), [])
        self.assertEqual(self._filter_submit_logs(logs, "blocked"), [])
        self.assertEqual(self._filter_submit_logs(logs, "error"), [])
        submit_logs = [r for r in logs if "contact_submit" in str(r.get("event", ""))]
        self.assertEqual(submit_logs, [])

    def test_disallowed_methods_return_405_without_send_or_log(self):
        """OPTIONS / TRACE / PUT / DELETE / PATCH never reach handle_post.

        Wagtail's ``before_serve_page`` hook checks the request method
        against ``Page.allowed_http_methods`` and short-circuits with a 405
        + Allow header before ``serve()`` runs. With ``allowed_http_methods``
        pinned to ``[GET, HEAD, POST]`` on :class:`cms.pages.contact.ContactPage`
        every other method is rejected up-front, so ``handle_post()`` is
        never invoked with an empty ``request.POST`` and no
        ``contact_submit`` log line is emitted.
        """
        expected_allow = {"GET", "HEAD", "POST"}
        for method in ("OPTIONS", "TRACE", "PUT", "DELETE", "PATCH"):
            with self.subTest(method=method):
                with (
                    patch("cms.views.contact.EmailMessage.send") as mock_send,
                    structlog.testing.capture_logs() as logs,
                ):
                    response = self.client.generic(method, self.page_url)

                self.assertEqual(response.status_code, 405, method)
                allow = {m.strip() for m in response["Allow"].split(",")}
                self.assertEqual(allow, expected_allow, (method, allow))
                mock_send.assert_not_called()
                self.assertEqual(mail.outbox, [])
                submit_logs = [r for r in logs if "contact_submit" in str(r.get("event", ""))]
                self.assertEqual(submit_logs, [], (method, submit_logs))

    def test_cookie_secure_under_https_get(self):
        """An HTTPS GET marks the ``contact_dsc`` cookie as ``Secure``."""
        response = self.client.get(self.page_url, secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("contact_dsc", response.cookies)
        self.assertTrue(response.cookies["contact_dsc"]["secure"])
        self.assertTrue(response.cookies["contact_dsc"]["httponly"])

    @override_settings(SESSION_COOKIE_SECURE=True)
    def test_cookie_secure_under_session_cookie_secure_setting(self):
        """A plain-HTTP GET still marks the cookie ``Secure`` when the setting is on."""
        response = self.client.get(self.page_url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("contact_dsc", response.cookies)
        self.assertTrue(response.cookies["contact_dsc"]["secure"])
        self.assertTrue(response.cookies["contact_dsc"]["httponly"])

    def test_token_regenerated_per_get(self):
        """Each GET issues fresh ``(ts, dsc)`` values."""
        ts1, dsc1 = self._get_fresh_tokens()
        # Force a second fully fresh request so the signed timestamp differs.
        time.sleep(1.05)
        self.client = Client()
        ts2, dsc2 = self._get_fresh_tokens()
        self.assertNotEqual(dsc1, dsc2)
        self.assertNotEqual(ts1, ts2)

    def test_resubmit_after_error_succeeds(self):
        """After a validation error the refreshed tokens + cookie allow a successful retry."""
        ts1, dsc1 = self._get_fresh_tokens()
        ts1_aged = self._age_timestamp_token(ts1)
        bad_post = self._build_post_data(ts1_aged, dsc1, message="too short")
        bad_response = self.client.post(self.page_url, data=bad_post)
        self.assertEqual(bad_response.status_code, 200)
        self.assertEqual(mail.outbox, [])

        ts2, dsc2 = self._get_tokens_from_response(bad_response)
        self.assertIsNotNone(ts2)
        self.assertIsNotNone(dsc2)
        cookie = bad_response.cookies.get("contact_dsc")
        self.assertIsNotNone(cookie)
        self.assertEqual(cookie.value, dsc2)

        ts2_aged = self._age_timestamp_token(ts2)
        good_post = self._build_post_data(ts2_aged, dsc2)
        good_response = self.client.post(self.page_url, data=good_post, follow=True)
        self.assertEqual(good_response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)

    # ------------------------------------------------------------------
    # Outgoing mail field contracts
    # ------------------------------------------------------------------

    def test_outgoing_from_email_matches_default_from_email(self):
        """``mail.outbox[0].from_email`` mirrors ``settings.DEFAULT_FROM_EMAIL``."""
        ts, dsc = self._get_fresh_tokens()
        ts = self._age_timestamp_token(ts)
        post = self._build_post_data(ts, dsc)
        self.client.post(self.page_url, data=post)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].from_email, settings.DEFAULT_FROM_EMAIL)

    def test_recipient_matches_contact_recipient_email(self):
        """``mail.outbox[0].to`` and ``recipients()`` match ``CONTACT_RECIPIENT_EMAIL`` only."""
        ts, dsc = self._get_fresh_tokens()
        ts = self._age_timestamp_token(ts)
        post = self._build_post_data(ts, dsc)
        self.client.post(self.page_url, data=post)
        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertEqual(sent.to, [settings.CONTACT_RECIPIENT_EMAIL])
        self.assertEqual(sent.recipients(), [settings.CONTACT_RECIPIENT_EMAIL])
        self.assertEqual(sent.cc, [])
        self.assertEqual(sent.bcc, [])

    # ------------------------------------------------------------------
    # Editor-content rendering
    # ------------------------------------------------------------------

    def test_admin_editable_streamfields_render(self):
        """The rendered GET body contains text-block content from both StreamFields."""
        response = self.client.get(self.page_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Get in touch with the Portal team.")
        self.assertContains(response, "We process your data lawfully under GDPR.")

    def test_admin_form_exposes_before_and_after_form(self):
        """The Wagtail edit handler exposes ``before_form`` and ``after_form`` fields."""
        edit_handler = ContactPage.get_edit_handler()
        form_class = edit_handler.get_form_class()
        self.assertIn("before_form", form_class.base_fields)
        self.assertIn("after_form", form_class.base_fields)

    # ------------------------------------------------------------------
    # Wagtail preview path
    # ------------------------------------------------------------------

    def test_preview_render_does_not_set_dsc_cookie_or_log(self):
        """``make_preview_request`` renders without cookie, log, or email side effects."""
        factory = RequestFactory()
        request = factory.get(self.page_url)

        mail.outbox = []
        with (
            patch("cms.views.contact.EmailMessage.send") as mock_send,
            structlog.testing.capture_logs() as logs,
        ):
            response = self.page.make_preview_request(request)

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("contact_dsc", response.cookies)
        mock_send.assert_not_called()
        self.assertEqual(mail.outbox, [])

        submit_logs = [r for r in logs if "contact_submit" in str(r.get("event", ""))]
        self.assertEqual(submit_logs, [])

        body = response.content if hasattr(response, "content") else b""
        if not body and hasattr(response, "render"):
            response.render()
            body = response.content
        self.assertIn(b"contact_ts", body)
        self.assertIn(b"contact_dsc", body)

    # ------------------------------------------------------------------
    # No user content in any logged event
    # ------------------------------------------------------------------

    def test_user_content_absent_from_logs(self):
        """Submitted name/email/message literals never appear in any captured log payload."""
        sentinels = (NAME_LITERAL, EMAIL_LITERAL, MESSAGE_LITERAL)

        scenarios: list[tuple[str, dict[str, object]]] = []

        def record(label: str, **kwargs: object) -> None:
            scenarios.append((label, kwargs))

        record("success")
        record("HONEYPOT_HIT", website="bot-was-here")
        record("TOO_FAST", skip_aging=True)
        record("TOKEN_MISMATCH", drop_cookie=True)
        record("TOKEN_BAD_SIGNATURE_malformed", ts_override="not-a-real-signed-token")
        record("TOKEN_BAD_SIGNATURE_expired", expire_token=True)
        # Trigger VALIDATION_ERROR via an invalid category while keeping the
        # default sentinel name/email/message payload, so a regression that
        # leaks MESSAGE_LITERAL into the logged event surfaces here too.
        record("VALIDATION_ERROR", category=["nope-not-a-real-choice"])
        record("EMAIL_SEND_ERROR", patch_send=True)
        # Regression guard for the `exc_info=True` removal: even when the
        # backend exception text echoes submitted name/email/message values,
        # the captured structlog payload must not contain those sentinels.
        record(
            "EMAIL_SEND_ERROR_sentinel_in_exc",
            exc_text=(
                f"backend rejected message from {NAME_LITERAL} <{EMAIL_LITERAL}>: {MESSAGE_LITERAL}"
            ),
        )

        for label, kwargs in scenarios:
            with self.subTest(label):
                self.client = Client()
                ts, dsc = self._get_fresh_tokens()

                if kwargs.get("drop_cookie"):
                    self.client.cookies.pop("contact_dsc", None)

                if kwargs.get("expire_token"):
                    past_time = int(time.time()) - MAX_TOKEN_AGE_SECONDS - 100
                    with patch("django.core.signing.time.time", return_value=past_time):
                        ts = CONTACT_TS_SIGNER.sign(str(past_time))
                elif "ts_override" in kwargs:
                    ts = kwargs["ts_override"]
                elif not kwargs.get("skip_aging"):
                    ts = self._age_timestamp_token(ts)

                post_kwargs: dict[str, Any] = {}
                if "website" in kwargs:
                    post_kwargs["website"] = kwargs["website"]
                if "message" in kwargs:
                    post_kwargs["message"] = kwargs["message"]
                if "category" in kwargs:
                    post_kwargs["category"] = kwargs["category"]
                post = self._build_post_data(ts, dsc, **post_kwargs)

                if "exc_text" in kwargs:
                    cm = patch(
                        "cms.views.contact.EmailMessage.send",
                        side_effect=Exception(kwargs["exc_text"]),
                    )
                elif kwargs.get("patch_send"):
                    cm = patch(
                        "cms.views.contact.EmailMessage.send",
                        side_effect=Exception("boom"),
                    )
                else:
                    cm = patch("cms.views.contact.EmailMessage.send")

                with cm, structlog.testing.capture_logs() as logs:
                    self.client.post(self.page_url, data=post)

                submit_logs = [r for r in logs if "contact_submit" in str(r.get("event", ""))]
                self.assertGreaterEqual(len(submit_logs), 1, label)

                for submit_record in submit_logs:
                    msg = f"{label}: contact_submit leaked exception payload: {submit_record!r}"
                    self.assertNotIn("exc_info", submit_record, msg)
                    self.assertNotIn("exception", submit_record, msg)

                for record_dict in logs:
                    flat = _flatten_log_value(record_dict)
                    for sentinel in sentinels:
                        self.assertNotIn(
                            sentinel,
                            flat,
                            f"{label}: log leaked sentinel {sentinel!r}: {record_dict!r}",
                        )

                mail.outbox = []
