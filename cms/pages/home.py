"""A home page model."""

from typing import Any

from django.core.exceptions import ValidationError
from django.db import models
from django.http import HttpRequest
from wagtail.admin.panels import FieldPanel, MultiFieldPanel, PageChooserPanel
from wagtail.blocks import RichTextBlock
from wagtail.fields import StreamField
from wagtail.models import Page

from cms.blocks import AlertBlock, CollapsibleBlock, PageSectionBlock

NOTICE_TYPE_CHOICES = [
    ("info", "Info"),
    ("warning", "Warning"),
    ("success", "Success"),
    ("error", "Error"),
]


class HomePage(Page):
    """Top-level homepage of the site.

    This page sits directly under the Wagtail root node and serves as
    the main entry point for the website. It can only be created once.
    """

    template = "cms/pages/home.html"
    max_count = 1
    parent_page_types = ["wagtailcore.Page"]

    hero_title = models.CharField(
        max_length=255,
        blank=True,
        help_text="The main title displayed in the hero section of the homepage.",
    )
    hero_text = models.CharField(
        max_length=255,
        blank=True,
        help_text="The text displayed below the main title in the hero section.",
    )
    hero_button_text = models.CharField(
        max_length=70,
        blank=True,
        help_text=(
            "The text displayed on the button in the hero section. This acts as enabler "
            "for the button, so if this is blank, no button will be displayed."
        ),
    )
    hero_button_page = models.ForeignKey(
        "wagtailcore.Page",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="The page that the button in the hero section links to.",
    )
    hero_button_link = models.URLField(
        blank=True,
        help_text="The URL that the button in the hero section links to.",
    )

    content = StreamField(
        [
            ("text", RichTextBlock()),
            ("alert", AlertBlock()),
            ("collapsible", CollapsibleBlock()),
            ("page_section", PageSectionBlock()),
        ],
        blank=True,
        collapsed=True,
        help_text="Content for the left column of the homepage.",
    )

    content_panels = Page.content_panels + [
        MultiFieldPanel(
            [
                FieldPanel("hero_title"),
                FieldPanel("hero_text"),
                FieldPanel("hero_button_text"),
                PageChooserPanel("hero_button_page"),
                FieldPanel("hero_button_link"),
            ],
            heading="Hero Section",
            classname="collapsed",
        ),
        FieldPanel("content"),
    ]

    def clean(self) -> None:
        """Ensure some validation rules are enforced for the homepage model."""
        super().clean()

        # When hero button text is provided, one link MUST be set, but not both.
        if self.hero_button_text:
            if self.hero_button_page and self.hero_button_link:
                message = (
                    "When hero button text is provided, only either a hero button page or "
                    "a hero button link can be set, not both."
                )
                raise ValidationError({"hero_button_page": message, "hero_button_link": message})
            if not self.hero_button_page and not self.hero_button_link:
                message = (
                    "When hero button text is provided, either a hero button page or a "
                    "hero button link must be set."
                )
                raise ValidationError({"hero_button_page": message, "hero_button_link": message})
        # When either a link is set, hero button text must be provided.
        elif self.hero_button_page or self.hero_button_link:
            message = (
                "When either a hero button page or a hero button link is set, "
                "hero button text must also be provided."
            )
            raise ValidationError({"hero_button_text": message})

    def get_context(self, request: HttpRequest) -> dict[str, Any]:
        """Add additional context variables for the homepage template."""

        from cms.pages import NewsIndexPage

        context = super().get_context(request)
        context["news_page"] = NewsIndexPage.objects.live().first()
        context["news_child_pages"] = (
            context["news_page"]
            .get_children()
            .live()
            .public()
            .specific()
            .order_by("-first_published_at")[:3]
            if context["news_page"]
            else []
        )

        return context
