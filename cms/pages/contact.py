"""Singleton contact page model with anti-spam tokens and an editor-managed intro."""

from __future__ import annotations

from http import HTTPMethod
from typing import Any

from django.http import HttpRequest, HttpResponse, HttpResponseNotAllowed
from django.shortcuts import render
from wagtail.admin.panels import FieldPanel
from wagtail.fields import RichTextField
from wagtail.models import Page

from cms.forms.contact import ContactForm
from cms.views.contact import generate_tokens, set_dsc_cookie


class ContactPage(Page):
    """Singleton contact page rendering a moderated form under ``HomePage``.

    The page is a thin Wagtail wrapper over :class:`cms.forms.contact.ContactForm`.
    Submissions are never persisted — the (Task 4) POST handler emails one
    message via the configured email backend and re-renders the bound form on
    validation or send errors. Editors manage two RichText fields (``intro`` and
    ``gdpr_notice``) to localise the surrounding copy without touching code.

    Attributes:
        intro (RichTextField): Editor-managed introduction shown above the form.
        gdpr_notice (RichTextField): Editor-managed GDPR / privacy notice shown
            alongside the form.
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

    intro = RichTextField(features=["bold", "italic", "link"], blank=True)
    gdpr_notice = RichTextField(features=["bold", "italic", "link"], blank=True)

    content_panels = Page.content_panels + [
        FieldPanel("intro"),
        FieldPanel("gdpr_notice"),
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
            A context dict containing ``form``, ``signed_ts``, ``dsc_token``,
            ``intro``, and ``gdpr_notice``.
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
            "intro": self.intro,
            "gdpr_notice": self.gdpr_notice,
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
            A context dict containing ``form``, ``signed_ts``, ``dsc_token``,
            ``intro``, and ``gdpr_notice``.
        """
        del mode_name  # Single-mode preview — kwarg required by Wagtail's API.
        return self._build_get_context(request)
