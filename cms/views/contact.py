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

import structlog
from django.conf import settings
from django.http import HttpRequest, HttpResponse

from cms.forms.contact import CONTACT_TS_SIGNER

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
