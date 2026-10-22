"""Genomic data page that lists Swedish pathogen records from ENA."""

from typing import Any

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from wagtail.admin.panels import FieldPanel
from wagtail.blocks import RichTextBlock
from wagtail.fields import StreamField
from wagtail.models import Page
from wagtail.search import index

from cms.blocks import AlertBlock, EnaDataBlock
from cms.services.genomic_data import MAX_SEARCH_LENGTH, build_context_dict


class GenomicDataPage(Page):
    """Genomic data page that lists Swedish pathogen records from ENA.

    Records are searched live in EBI Search's ENA pathogen indexes (the same
    source as the central Pathogens Portal), one page at a time, with facets,
    a search box, data type tabs and sortable columns.

    Attributes:
        content (StreamField): StreamField with three content block types:
            - RichTextBlock: formatted text (headings, bold, italic, links, lists).
            - AlertBlock: callout/notice box.
            - EnaDataBlock: the searchable records listing.
    """

    template = "cms/pages/genomic_data/index.html"
    parent_page_types = ["cms.HomePage"]
    subpage_types = []
    max_count = 1

    content = StreamField(
        [
            ("text", RichTextBlock()),
            ("alert", AlertBlock()),
            ("ena_data", EnaDataBlock()),
        ],
        blank=False,
        block_counts={"ena_data": {"min_num": 1, "max_num": 1}},
    )
    search_fields = Page.search_fields + [
        index.SearchField("content"),
        index.AutocompleteField("content"),
        index.AutocompleteField("title"),
    ]
    content_panels = Page.content_panels + [FieldPanel("content")]

    class Meta:
        """Metadata options for the genomic data page."""

        verbose_name = "Genomic data page"

    def get_context(self, request: HttpRequest, *args: Any, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        """Add the lazy-load URL and the search box's current value to the context."""
        context = super().get_context(request, *args, **kwargs)
        context["ena_listing_url"] = request.get_full_path()
        context["ena_search_text"] = request.GET.get("q", "").strip()[:MAX_SEARCH_LENGTH]
        return context

    def serve(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:  # noqa: ANN401
        """Serve the genomic data page.

        HTMX requests get just the listing partial (tabs, facets and results).
        Anything else, including HTMX history restores (which need a whole page),
        gets the full page.
        """
        if request.htmx and not request.htmx.history_restore_request:
            return render(
                request=request,
                template_name="cms/pages/genomic_data/partials/ena_listing.html",
                context=build_context_dict(request=request, page=self),
            )
        return super().serve(request, *args, **kwargs)
