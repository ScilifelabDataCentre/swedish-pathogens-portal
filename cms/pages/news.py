"""CMS Page for News."""

from typing import Any

from django.db import models
from django.http import HttpRequest
from wagtail.admin.panels import FieldPanel, MultiFieldPanel
from wagtail.blocks import RichTextBlock
from wagtail.fields import StreamField
from wagtail.images import get_image_model_string
from wagtail.models import Page

from cms.blocks import AlertBlock


class NewsPage(Page):
    """A page representing a single news article.

    This page is intended to be a child of NewsIndexPage. It contains the
    content of a news article, which can include rich text and alerts.

    Attributes:
        description (str): A brief text summary that will be displayed on the news card.
        image (Image): The image displayed on the news card and article page.
        image_caption (str): A required caption shown under the article image.
        content (StreamField): A stream field for the news article content, allowing rich text.
    """

    template = "cms/pages/news.html"
    parent_page_types = ["cms.NewsIndexPage"]
    subpage_types = []

    description = models.CharField(max_length=255, blank=False)
    image = models.ForeignKey(
        get_image_model_string(),
        null=True,
        blank=False,
        on_delete=models.PROTECT,
        related_name="+",
    )
    image_caption = models.CharField(max_length=255)
    content = StreamField(
        [
            ("text", RichTextBlock()),
            ("alert", AlertBlock()),
        ],
        blank=True,
    )

    content_panels = Page.content_panels + [
        MultiFieldPanel(
            [
                FieldPanel(
                    "description",
                    help_text="Brief text summary that will be displayed on the news card.",
                ),
                FieldPanel(
                    "image",
                    help_text=(
                        "Image used on the news card and article page. On the article page "
                        "it is shown at its natural proportions beside the text."
                    ),
                ),
                FieldPanel(
                    "image_caption",
                    help_text=(
                        "Required caption displayed below the image on the article page. "
                        "It is not displayed on the news card."
                    ),
                ),
            ],
            heading="Card details",
        ),
        FieldPanel("content", help_text="The main content for the news article."),
    ]

    promote_panels = Page.promote_panels + [
        FieldPanel(
            "first_published_at",
            help_text=(
                "The page creation date that will be displayed on the card. "
                "Defaults to the publication date."
            ),
        ),
    ]

    def get_context(self, request: HttpRequest) -> dict[str, Any]:
        """Add the parent page's title to the context for display on the news page."""

        # Importing here to avoid circular imports
        from cms.pages.news_index import NewsIndexPage

        context = super().get_context(request)
        parent = self.get_ancestors().type(NewsIndexPage).specific().first()
        if parent:
            context["page_heading"] = parent.title
        return context
