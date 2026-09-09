"""Standard catalogue page model with a StreamField body."""

from typing import Any

from django.db import models
from django.http import HttpRequest, HttpResponse
from django.utils.functional import cached_property
from django.utils.html import strip_tags
from django.utils.text import slugify
from wagtail import blocks
from wagtail.admin.panels import FieldPanel
from wagtail.fields import StreamField
from wagtail.models import Page

from cms.blocks import AlertBlock, CatalogueCardGridBlock
from cms.services.decorators import htmx_request_with_url_update
from cms.services.validators import validate_filters


class CataloguePage(Page):
    """Catalogue page with a StreamField body for listing catalogue cards.

    Attributes:
        content (StreamField): StreamField with multiple content block types:
            - RichTextBlock: formatted text (headings, bold, italic, links, lists)
            - AlertBlock: styled alert message with custom text and type
            - CatalogueCardGridBlock: grid of cards linking to child pages
    """

    template = "cms/pages/catalogue.html"
    htmx_template = "cms/pages/catalogue.html#catalogue_grid"
    parent_page_types = ["cms.HomePage"]
    subpage_types = []

    filter_label = models.CharField(max_length=100, blank=False)
    content = StreamField(
        [
            (
                "text",
                blocks.RichTextBlock(
                    verbose_name="Text (rich)",
                    help_text="Rich text content. Supports headings, links, etc. for formatting.",
                ),
            ),
            ("alert", AlertBlock()),
            (
                "card_grid",
                CatalogueCardGridBlock(
                    help_text=(
                        "Catalogue items added here will be displayed in a grid layout. "
                        "The items are rendered as cards and ordered alphabetically."
                    )
                ),
            ),
        ],
        blank=True,
    )

    content_panels = Page.content_panels + [
        FieldPanel(
            "filter_label",
            help_text=(
                "Label for the filter section (e.g., 'Catalogue Type'). This will be used as the "
                "heading for the filter controls on the frontend."
            ),
        ),
        FieldPanel(
            "content",
            help_text="Drag blocks to reorder. Each block type has its own fields and help text.",
        ),
    ]

    @cached_property
    def cards(self) -> list[dict[str, Any]]:
        """Extract card data from the content StreamField for use in templates."""

        cards: list[dict[str, Any]] = []

        for block in self.content:
            if block.block_type != "card_grid":
                continue

            for card in block.value.get("cards", []):
                cards.append(
                    {
                        "title": card["title"],
                        "description": card["description"],
                        "image": card["image"],
                        "url": card["url"],
                        "type": card["type"],
                        "keywords": card["keywords"],
                        "truncate_text": block.value.get("truncate_text", True),
                    }
                )

        return sorted(cards, key=lambda x: x["title"].lower())

    @cached_property
    def card_types(self) -> list[str]:
        """Get unique card types from the cards for filtering options."""
        return sorted({t.strip() for card in self.cards for t in card["type"].split(",")})

    def get_context(self, request: HttpRequest) -> dict[str, Any]:
        """Add cards and card types to the template context."""
        context = super().get_context(request)
        context["catalogue_types"] = self.card_types
        context["catalogue_list"] = self.cards

        # Validate and clean the query parameters for filtering
        validated_filters = validate_filters(
            request.GET,
            valid_types=context["catalogue_types"],
            expected_keys={"search", "type"},
        )

        search_filter = validated_filters.get("search")
        if search_filter:
            context["catalogue_list"] = [
                card
                for card in context["catalogue_list"]
                if search_filter.lower() in card["title"].lower()
                or search_filter.lower() in strip_tags(card["description"]).lower()
                or search_filter.lower() in card["keywords"].lower()
            ]

        type_filters = validated_filters.get("type")
        if type_filters:
            context["catalogue_list"] = [
                card
                for card in context["catalogue_list"]
                if any(slugify(t.strip()) in type_filters for t in card["type"].split(","))
            ]
            context["type_filter"] = type_filters

        return context

    @htmx_request_with_url_update()
    def serve(self, request: HttpRequest) -> HttpResponse:
        """Override serve method to handle HTMX requests for filtering."""
        return super().serve(request)
