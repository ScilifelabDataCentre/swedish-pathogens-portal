"""Publications Page that displays recent Sweden affiliated research papers in Europe PMC."""

from dataclasses import dataclass
from typing import Any

from django.http import HttpRequest, HttpResponse
from django.utils.functional import cached_property
from wagtail.admin.panels import FieldPanel
from wagtail.blocks import RichTextBlock
from wagtail.fields import StreamField
from wagtail.models import Page

from cms.blocks import AlertBlock
from cms.blocks.publications import PublicationsBlock


@dataclass
class Pathogen:
    """A pathogen that can be used to search for publications in Europe PMC.

    Attributes:
        name (str): The name of the pathogen.
        search_terms (list[str]): A list of search terms to find in a publication's abstract.
    """

    name: str
    search_terms: list[str]


class PublicationsPage(Page):
    """Publications page that displays Sweden affiliated research papers in Europe PMC.

    Papers can be filtered by pathogen Uses EuroPMC's API to retrieve the data.

    Attributes:
        content (StreamField): StreamField with three content block types:
            - RichTextBlock: formatted text (headings, bold, italic, links, lists.
            - AlertBlock: callout/notice box.
            - PublicationsBlock: List recent publications for a given pathogen.
    """

    template = "cms/pages/publications/index.html"
    parent_page_types = ["cms.HomePage"]
    subpage_types = []

    content = StreamField(
        [
            ("text", RichTextBlock()),
            ("alert", AlertBlock()),
            ("publications", PublicationsBlock()),
        ],
        blank=False,
        block_counts={"publications": {"max_num": 1}},
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
        return pathogens

    def get_context(self, request: HttpRequest) -> dict[str, Any]:
        """Add TODO to the context."""
        context = super().get_context(request)
        return context

    def serve(self, request: HttpRequest) -> HttpResponse:
        """Serve the publications page.

        If the request is made via HTMX, render the publications list partial template,
        otherwise render the full page.
        """
        # if request.htmx:
        # TODO
        return super().serve(request)
