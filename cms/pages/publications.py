"""Publications Page that displays recent Sweden affiliated research papers in Europe PMC."""

from typing import Any

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils.functional import cached_property
from wagtail.admin.panels import FieldPanel
from wagtail.blocks import RichTextBlock
from wagtail.fields import StreamField
from wagtail.models import Page

from cms.blocks import AlertBlock
from cms.blocks.publications import PublicationsBlock
from cms.services.publications import (
    Pathogen,
    build_context_dict,
    resolve_active_pathogen,
)


class PublicationsPage(Page):
    """Publications page that displays Sweden affiliated research papers in Europe PMC.

    Papers can be filtered by pathogen. Uses EuroPMC's API to retrieve the data.

    Attributes:
        content (StreamField): StreamField with three content block types:
            - RichTextBlock: formatted text (headings, bold, italic, links, lists.
            - AlertBlock: callout/notice box.
            - PublicationsBlock: List recent publications for a given pathogen.
    """

    template = "cms/pages/publications/index.html"
    parent_page_types = ["cms.HomePage"]
    subpage_types = []
    max_count = 1

    content = StreamField(
        [
            ("text", RichTextBlock()),
            ("alert", AlertBlock()),
            ("publications", PublicationsBlock()),
        ],
        blank=False,
        block_counts={"publications": {"min_num": 1, "max_num": 1}},
    )
    content_panels = Page.content_panels + [FieldPanel("content")]

    @cached_property
    def pathogens(self) -> list[Pathogen]:
        """Return a list of pathogens from the publications block in the content StreamField."""
        pathogens: list[Pathogen] = []
        for block in self.content:
            if block.block_type != "publications":
                continue
            for pathogen_data in block.value["pathogens"]:
                pathogens.append(
                    Pathogen(
                        name=pathogen_data["name"],
                        search_terms=list(pathogen_data["search_terms"]),
                    )
                )
        return sorted(pathogens, key=lambda pathogen: pathogen.name)

    @cached_property
    def pathogens_by_name(self) -> dict[str, Pathogen]:
        """Return a mapping of pathogen name to Pathogen for lookups by name."""
        return {pathogen.name: pathogen for pathogen in self.pathogens}

    def get_context(self, request: HttpRequest) -> dict[str, Any]:
        """Add the active (selected) pathogen to the template context."""
        context = super().get_context(request)
        active_pathogen = resolve_active_pathogen(page=self, request=request)
        context["active_pathogen"] = active_pathogen.name if active_pathogen else None
        return context

    def serve(self, request: HttpRequest) -> HttpResponse:
        """Serve the publications page.

        If the request is made via HTMX, render the publications list partial template,
        otherwise render the full page.
        """
        if request.htmx:
            return render(
                request=request,
                template_name="cms/pages/publications/partials/publications_list.html",
                context=build_context_dict(request=request, page=self),
            )
        return super().serve(request)
