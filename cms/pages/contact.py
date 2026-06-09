"""Singleton contact page model with anti-spam tokens and editor-managed streams."""

from __future__ import annotations

from http import HTTPMethod
from typing import Any

from django.http import HttpRequest, HttpResponse, HttpResponseNotAllowed
from django.shortcuts import render
from wagtail import blocks
from wagtail.admin.panels import FieldPanel
from wagtail.fields import StreamField
from wagtail.models import Page

from cms.blocks import AlertBlock
from cms.forms.contact import ContactForm
from cms.views.contact import generate_tokens, set_dsc_cookie


class ContactPage(Page):
    """Singleton contact page rendering a moderated form under ``HomePage``.

    The page is a thin Wagtail wrapper over :class:`cms.forms.contact.ContactForm`.
    Submissions are never persisted — the POST handler emails one message via
    the configured email backend and re-renders the bound form on validation or
    send errors. Editors manage two StreamFields surrounding the form
    (``before_form`` and ``after_form``); both accept ``text`` (rich text) and
    ``alert`` (styled callout) blocks. The form's position is fixed in the
    middle of the template.

    Attributes:
        before_form (StreamField): Editor-managed content rendered above the
            form. Accepts ``text`` and ``alert`` blocks.
        after_form (StreamField): Editor-managed content rendered below the
            form. Accepts ``text`` and ``alert`` blocks (e.g. GDPR / privacy
            notice).
    """

    template = "cms/pages/contact.html"
    parent_page_types = ["cms.HomePage"]
    subpage_types: list[str] = []
    max_count = 1
    # Wagtail's before_serve_page hook denies non-listed methods with a 405 +
    # Allow header before serve() is reached. Limiting to GET / HEAD / POST
    # stops OPTIONS / TRACE / PUT / DELETE / PATCH from ever invoking
    # handle_post() with an empty request.POST and emitting a blocked
    # contact_submit log.
    allowed_http_methods = [HTTPMethod.GET, HTTPMethod.HEAD, HTTPMethod.POST]

    before_form = StreamField(
        [
            ("text", blocks.RichTextBlock(features=["bold", "italic", "link"])),
            ("alert", AlertBlock()),
        ],
        blank=True,
    )
    after_form = StreamField(
        [
            ("text", blocks.RichTextBlock(features=["bold", "italic", "link"])),
            ("alert", AlertBlock()),
        ],
        blank=True,
    )

    content_panels = Page.content_panels + [
        FieldPanel("before_form"),
        FieldPanel("after_form"),
    ]

    def _build_get_context(self, request: HttpRequest) -> dict[str, Any]:
        """Mint fresh tokens and assemble the GET / preview render context.

        Reused by :meth:`serve` (GET branch) and :meth:`get_preview_context`
        so every render path issues a fresh ``(signed_ts, dsc_token)`` pair,
        keeping the rendered hidden inputs in lock-step with the cookie the
        caller is about to set (or, in the preview path, deliberately not set).

        Args:
            request: The active ``HttpRequest`` (forwarded into the form so
                its ``clean()`` step can read the ``contact_dsc`` cookie).

        Returns:
            A context dict containing ``page``, ``form``, ``signed_ts``, and
            ``dsc_token``. The two ``StreamField`` streams are reached through
            ``page.before_form`` / ``page.after_form`` in the template.
        """
        signed_ts, dsc_token = generate_tokens()
        form = ContactForm(request=request)
        form.initial["contact_ts"] = signed_ts
        form.initial["contact_dsc"] = dsc_token
        return {
            "page": self,
            "form": form,
            "signed_ts": signed_ts,
            "dsc_token": dsc_token,
        }

    def serve(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        """Route GET / HEAD / preview to the form render and POST to ``handle_post``.

        Preview requests (``request.is_preview`` truthy) are forced down the
        GET path so a future custom preview that POSTs against a draft never
        triggers an email send. HEAD requests are routed identically to GET so
        link-checkers and HTTP probes cannot reach :func:`handle_post` — which
        would otherwise attempt to validate an empty form, emit a
        ``contact_submit`` log line, and in the limit instantiate an
        ``EmailMessage``. The cookie is still attached so the preview/HEAD
        response looks identical to a live render — except
        :meth:`get_preview_context` also has an override that skips the cookie
        when Wagtail goes through its own ``PreviewableMixin.serve_preview``
        path. Any other method (``OPTIONS``, ``TRACE``, ``PUT``, ``DELETE``,
        ``PATCH``) returns a 405 with an explicit ``Allow`` header instead of
        falling through to the POST handler — which would validate an empty
        form, emit a ``blocked`` contact_submit log, and respond 200.

        Args:
            request: The incoming ``HttpRequest``.
            *args: Forwarded to the POST handler when applicable.
            **kwargs: Forwarded to the POST handler when applicable.

        Returns:
            Rendered ``HttpResponse`` for the contact form (GET / HEAD /
            preview), the result of :func:`handle_post` for POST, or a 405
            ``HttpResponseNotAllowed`` for any other method.
        """
        if getattr(request, "is_preview", False) or request.method in {"GET", "HEAD"}:
            context = self._build_get_context(request)
            response = render(request, self.template, context)
            set_dsc_cookie(response, context["dsc_token"], request)
            return response

        if request.method == "POST":
            from cms.views.contact import handle_post

            return handle_post(self, request)

        return HttpResponseNotAllowed(["GET", "HEAD", "POST"])

    def get_preview_context(self, request: HttpRequest, mode_name: str) -> dict[str, Any]:
        """Return the GET render context for Wagtail's preview without side effects.

        The preview path MUST NOT set the ``contact_dsc`` cookie, emit any
        ``contact_submit`` log, or instantiate any ``EmailMessage``. Reusing
        :meth:`_build_get_context` guarantees all three: the cookie is set by
        the caller of ``_build_get_context``, never by ``_build_get_context``
        itself; no log is emitted by token generation; and no email is sent
        because the POST branch is never reached.

        Args:
            request: The Wagtail preview request.
            mode_name: The preview mode name (unused but required by Wagtail's
                ``PreviewableMixin`` contract).

        Returns:
            The dict produced by :meth:`_build_get_context` (see its
            ``Returns`` for the exact shape).
        """
        del mode_name  # Single-mode preview — kwarg required by Wagtail's API.
        return self._build_get_context(request)
