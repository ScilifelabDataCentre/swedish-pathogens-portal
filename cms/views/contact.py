"""View-layer helpers for the contact page.

The ``ContactPage`` model in :mod:`cms.pages.contact` mints anti-spam tokens
on GET and re-mints them on every blocked/errored POST. The helpers in this
module centralise that logic so the page model and the (Task 4) POST handler
share a single implementation of token generation and the ``contact_dsc``
double-submit cookie.

Intentional hardening vs. the spp-django prototype: :func:`cookie_secure_flag`
returns ``True`` whenever EITHER ``request.is_secure()`` OR
``settings.SESSION_COOKIE_SECURE`` is true (the prototype consulted only the
first signal). This guarantees the cookie carries the ``Secure`` attribute on
HTTPS deployments and behind reverse proxies that terminate TLS.
"""

from __future__ import annotations

import secrets
import time
from typing import TYPE_CHECKING

import structlog
from django.conf import settings
from django.contrib import messages
from django.core.mail import EmailMessage
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render

from cms.forms.contact import CONTACT_TS_SIGNER, ContactForm

if TYPE_CHECKING:
    from cms.pages.contact import ContactPage

LOGGER = structlog.get_logger(__name__)


def generate_tokens() -> tuple[str, str]:
    """Mint a fresh ``(signed_ts, dsc_token)`` pair for one contact-form render.

    Returns:
        A two-tuple where ``signed_ts`` is the current unix epoch second signed
        by :data:`CONTACT_TS_SIGNER`, and ``dsc_token`` is a 16-byte URL-safe
        random string used for the double-submit cookie pattern.
    """
    signed_ts = CONTACT_TS_SIGNER.sign(str(int(time.time())))
    dsc_token = secrets.token_urlsafe(16)
    return signed_ts, dsc_token


def cookie_secure_flag(request: HttpRequest) -> bool:
    """Return whether the ``contact_dsc`` cookie must carry the ``Secure`` flag.

    The flag is set when either signal indicates a secure context: the request
    itself is HTTPS, or the deployment globally requires secure cookies via
    ``SESSION_COOKIE_SECURE``. Combining both keeps the cookie ``Secure`` behind
    TLS-terminating proxies that report ``http`` to Django but expose the
    cookie over HTTPS to the browser.

    Args:
        request: The active ``HttpRequest``.

    Returns:
        ``True`` if the cookie should be marked secure, else ``False``.
    """
    return request.is_secure() or getattr(settings, "SESSION_COOKIE_SECURE", False)


def set_dsc_cookie(response: HttpResponse, token: str, request: HttpRequest) -> None:
    """Attach the ``contact_dsc`` double-submit cookie to ``response``.

    The cookie is HttpOnly, scoped to the same ``SameSite`` policy as the
    project's session cookie (default ``Lax``), and lives for 30 minutes — long
    enough for a slow human to fill in the form, short enough that abandoned
    sessions cannot be replayed.

    Args:
        response: The outgoing response to mutate.
        token: The double-submit token value to mirror into the cookie.
        request: The active ``HttpRequest``, used to derive the ``Secure`` flag.
    """
    response.set_cookie(
        key="contact_dsc",
        value=token,
        max_age=30 * 60,
        httponly=True,
        secure=cookie_secure_flag(request),
        samesite=getattr(settings, "SESSION_COOKIE_SAMESITE", "Lax"),
    )


def _build_email_body(form: ContactForm, request: HttpRequest) -> str:
    """Compose the prototype's plain-text email body from a validated form.

    The body order — ``From``, ``Email``, ``Categories``, ``Origin URL``, blank
    line, free-text message — matches ``spp-django/pages/contact/views.py``
    verbatim so editors recognise the format from the legacy site.

    Args:
        form: A bound, validated :class:`ContactForm`.
        request: The active ``HttpRequest`` (used to derive ``Origin URL``).

    Returns:
        The plain-text email body sent to ``CONTACT_RECIPIENT_EMAIL``.
    """
    name = form.cleaned_data.get("name", "")
    user_email = form.cleaned_data.get("email", "")
    message = form.cleaned_data["message"]
    selected_categories = form.cleaned_data.get("category", [])
    choice_map = dict(form.fields["category"].choices)
    categories = [choice_map.get(key, key) for key in selected_categories]
    origin_url = request.build_absolute_uri(request.path)
    return (
        f"From: {name}\n"
        f"Email: {user_email}\n"
        f"Categories: {', '.join(categories) if categories else '—'}\n"
        f"Origin URL: {origin_url}\n\n"
        f"{message}"
    )


def _render_with_fresh_tokens(
    page: ContactPage,
    request: HttpRequest,
    form: ContactForm,
) -> HttpResponse:
    """Re-render ``page`` after a blocked or errored POST with new anti-spam tokens.

    Resets the ``contact_ts`` / ``contact_dsc`` hidden inputs on the bound form
    so the user can retry without reloading, and attaches a matching
    ``contact_dsc`` cookie to the response.

    Args:
        page: The :class:`ContactPage` instance being rendered.
        request: The active ``HttpRequest``.
        form: The bound form to redisplay (carrying validation errors).

    Returns:
        An ``HttpResponse`` with HTTP 200 carrying the re-rendered template.
    """
    signed_ts, dsc_token = generate_tokens()
    form.initial["contact_ts"] = signed_ts
    form.initial["contact_dsc"] = dsc_token
    try:
        data = form.data.copy()
        data["contact_ts"] = signed_ts
        data["contact_dsc"] = dsc_token
        form.data = data
    except AttributeError:
        pass

    context = {
        "page": page,
        "form": form,
        "signed_ts": signed_ts,
        "dsc_token": dsc_token,
        "intro": page.intro,
        "gdpr_notice": page.gdpr_notice,
    }
    response = render(request, page.template, context)
    set_dsc_cookie(response, dsc_token, request)
    return response


def handle_post(page: ContactPage, request: HttpRequest) -> HttpResponse:
    """Validate a contact-page POST and either email + redirect or re-render.

    The handler walks the ``ContactForm`` through three deterministic outcomes,
    each emitting exactly one structlog event with ``duration_ms`` in milliseconds
    measured against :func:`time.monotonic`:

    1. ``is_valid()`` true and email send succeeds → log
       ``event=contact_submit outcome=success duration_ms=<int>`` (no ``reason``
       kwarg), flash a success message, and PRG-redirect to ``page.url``.
    2. ``is_valid()`` true but ``EmailMessage.send`` raises → log
       ``event=contact_submit outcome=error reason=EMAIL_SEND_ERROR``
       ``duration_ms=<int>`` (the exception is intentionally NOT attached via
       ``exc_info`` because backend error messages can echo submitted
       ``name``/``email``/``message`` values and structlog would otherwise
       capture them in the log payload), attach a generic non-field error AND
       flash a generic error message (no exception details leak), and re-render
       the form with fresh tokens + cookie (HTTP 200, NOT a redirect).
    3. ``is_valid()`` false → log ``event=contact_submit outcome=blocked``
       ``reason=<CODE>`` ``duration_ms=<int>`` (the reason code is read from
       ``form._blocked_reason`` and falls back to ``"VALIDATION_ERROR"``), and
       re-render the form with fresh tokens + cookie.

    Submitted ``name``, ``email``, and ``message`` values are deliberately NOT
    placed into any structlog kwarg on any outcome path — only reason codes,
    durations, and counts are logged.

    Args:
        page: The :class:`ContactPage` instance serving the request.
        request: The POST ``HttpRequest`` (CSRF middleware has already accepted
            it; missing tokens return 403 before reaching this helper).

    Returns:
        Either a 302 ``HttpResponseRedirect`` to ``page.url`` (success) or a
        200 ``HttpResponse`` re-rendering the form (error or blocked).
    """
    start = time.monotonic()
    form = ContactForm(request.POST, request=request)

    if not form.is_valid():
        duration_ms = int((time.monotonic() - start) * 1000)
        reason = getattr(form, "_blocked_reason", None) or "VALIDATION_ERROR"
        LOGGER.warning(
            "event=contact_submit outcome=blocked",
            reason=reason,
            duration_ms=duration_ms,
        )
        return _render_with_fresh_tokens(page, request, form)

    user_email = form.cleaned_data.get("email", "")
    body = _build_email_body(form, request)
    headers = {"Reply-To": user_email} if user_email else None
    email = EmailMessage(
        subject="[Contact] Contact and suggestions form",
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[settings.CONTACT_RECIPIENT_EMAIL],
        headers=headers,
    )
    try:
        email.send(fail_silently=False)
    except Exception:  # noqa: BLE001 — backend failures must not leak to users.
        duration_ms = int((time.monotonic() - start) * 1000)
        LOGGER.error(
            "event=contact_submit outcome=error",
            reason="EMAIL_SEND_ERROR",
            duration_ms=duration_ms,
        )
        generic_error = "Sorry, we couldn't send your message right now. Please try again later."
        form.add_error(None, generic_error)
        messages.error(request, generic_error)
        return _render_with_fresh_tokens(page, request, form)

    duration_ms = int((time.monotonic() - start) * 1000)
    LOGGER.info("event=contact_submit outcome=success", duration_ms=duration_ms)
    messages.success(request, "Thanks! Your message was sent, we'll get back to you soon.")
    return HttpResponseRedirect(page.url)
