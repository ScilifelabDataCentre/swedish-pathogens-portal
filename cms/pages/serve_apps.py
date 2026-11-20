"""Models and apps page that lists pathogen-related apps and models on SciLifeLab Serve."""

from typing import Any

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils.functional import cached_property
from wagtail.admin.panels import FieldPanel
from wagtail.blocks import RichTextBlock
from wagtail.fields import StreamField
from wagtail.models import Page
from wagtail.search import index

from cms.blocks import AlertBlock, ServeAppsBlock
from cms.services.serve_apps import MAX_SEARCH_LENGTH, build_context_dict


class ServeAppsPage(Page):
    """Models and apps page that lists pathogen-related apps and models on SciLifeLab Serve.

    The apps come from Serve's open API, kept to those matching the portal's pathogen
    keywords, and can be searched, filtered by type and keyword, and sorted.

    Attributes:
        content (StreamField): StreamField with three content block types:
            - RichTextBlock: formatted text (headings, bold, italic, links, lists).
            - AlertBlock: callout/notice box.
            - ServeAppsBlock: the searchable apps listing.
    """

    template = "cms/pages/serve_apps/index.html"
    parent_page_types = ["cms.HomePage"]
    subpage_types = []
    max_count = 1

    content = StreamField(
        [
            ("text", RichTextBlock(features=["h2", "h3", "bold", "italic", "link", "ol", "ul"])),
            ("alert", AlertBlock()),
            ("serve_apps", ServeAppsBlock()),
        ],
        blank=False,
        block_counts={"serve_apps": {"min_num": 1, "max_num": 1}},
        help_text="Page content. Must include exactly one Serve apps block.",
    )
    search_fields = Page.search_fields + [
        index.SearchField("content"),
        index.AutocompleteField("content"),
        index.AutocompleteField("title"),
    ]
    content_panels = Page.content_panels + [FieldPanel("content")]

    class Meta:
        """Metadata options for the models and apps page."""

        verbose_name = "Models and apps page"

    def _block_ids(self, name: str) -> frozenset[int]:
        """Return the app IDs in the Serve apps block's ``name`` list, skipping blank entries."""
        for block in self.content:
            if block.block_type == "serve_apps":
                return frozenset(app_id for app_id in block.value[name] if app_id is not None)
        return frozenset()

    @cached_property
    def include_app_ids(self) -> frozenset[int]:
        """Serve IDs the editors want shown even without a keyword match."""
        return self._block_ids("include_app_ids")

    @cached_property
    def exclude_app_ids(self) -> frozenset[int]:
        """Serve IDs the editors want hidden even with a keyword match."""
        return self._block_ids("exclude_app_ids")

    def get_context(self, request: HttpRequest, *args: Any, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        """Add the lazy-load URL and the search box's current value to the context."""
        context = super().get_context(request, *args, **kwargs)
        context["serve_listing_url"] = request.get_full_path()
        context["serve_search_text"] = request.GET.get("q", "").strip()[:MAX_SEARCH_LENGTH]
        return context

    def serve(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:  # noqa: ANN401
        """Serve the models and apps page.

        HTMX requests get just the listing partial (facets and apps). Anything else,
        including HTMX history restores (which need a whole page), gets the full page.
        """
        if request.htmx and not request.htmx.history_restore_request:
            return render(
                request=request,
                template_name="cms/pages/serve_apps/partials/serve_listing.html",
                context=build_context_dict(request=request, page=self),
            )
        return super().serve(request, *args, **kwargs)
