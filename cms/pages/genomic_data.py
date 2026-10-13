"""Genomic data page that lists Swedish pathogen records from ENA."""

from typing import Any

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils.functional import cached_property
from wagtail.admin.panels import FieldPanel
from wagtail.blocks import RichTextBlock
from wagtail.fields import StreamField
from wagtail.models import Page

from cms.blocks import AlertBlock, EnaDataBlock
from cms.services.genomic_data import EnaPathogen, build_context_dict


class GenomicDataPage(Page):
    """Genomic data page that lists Swedish pathogen records from ENA.

    Records are fetched live from the ENA Portal API, filtered by pathogen
    (configured in the ENA data block) and record type (raw reads, samples, sequences).

    Attributes:
        content (StreamField): StreamField with three content block types:
            - RichTextBlock: formatted text (headings, bold, italic, links, lists).
            - AlertBlock: callout/notice box.
            - EnaDataBlock: the ENA records listing, with its pathogens.
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
    content_panels = Page.content_panels + [FieldPanel("content")]

    class Meta:
        """Metadata options for the genomic data page."""

        verbose_name = "Genomic data page"

    @cached_property
    def pathogens(self) -> list[EnaPathogen]:
        """Return the pathogens from the ENA data block, sorted by name."""
        pathogens: list[EnaPathogen] = []
        for block in self.content:
            if block.block_type != "ena_data":
                continue
            for pathogen_data in block.value["pathogens"]:
                pathogens.append(
                    EnaPathogen(
                        name=pathogen_data["name"],
                        taxon_ids=tuple(pathogen_data["taxon_ids"]),
                    )
                )
        return sorted(pathogens, key=lambda pathogen: pathogen.name.casefold())

    @cached_property
    def pathogens_by_name(self) -> dict[str, EnaPathogen]:
        """Return a mapping of pathogen name to EnaPathogen for lookups by name."""
        return {pathogen.name: pathogen for pathogen in self.pathogens}

    def get_context(self, request: HttpRequest, *args: Any, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        """Add the URL the ENA listing is lazy-loaded from to the template context."""
        context = super().get_context(request, *args, **kwargs)
        context["ena_listing_url"] = request.get_full_path()
        return context

    def serve(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:  # noqa: ANN401
        """Serve the genomic data page.

        HTMX requests get just the ENA listing partial; anything else, including
        HTMX history restores (which need a whole page), gets the full page.
        """
        if request.htmx and not request.htmx.history_restore_request:
            return render(
                request=request,
                template_name="cms/pages/genomic_data/partials/ena_listing.html",
                context=build_context_dict(request=request, page=self),
            )
        return super().serve(request, *args, **kwargs)
