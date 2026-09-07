"""CMS pages for outbreaks."""

from typing import Any

from django.db import models
from django.http import HttpRequest
from wagtail.admin.panels import FieldPanel, MultiFieldPanel
from wagtail.blocks import RichTextBlock
from wagtail.fields import StreamField
from wagtail.images import get_image_model_string
from wagtail.models import Page

from cms.blocks import AlertBlock, DataTableBlock

OUTBREAKS_STATUS_DEFAULT = "ongoing"
OUTBREAKS_STATUS_CHOICES = [
    ("ongoing", "Ongoing"),
    ("historical", "Historical"),
]


class OutbreakPage(Page):
    """A page representing a single outbreak.

    This page is intended to be used as a child of OutbreaksIndexPage. It represents
    a single outbreak and can contain content related to that outbreak.

    Attributes:
        description (str): A brief description of the outbreak.
        image (ForeignKey): An image associated with the outbreak (actually saved as a foreign key).
        status (str): The current status of the outbreak (e.g., "ongoing" or "historical").
        content (StreamField): A stream field for the page content, allowing rich text.
    """

    template = "cms/pages/outbreak.html"
    parent_page_types = ["cms.OutbreaksIndexPage"]
    subpage_types = []

    description = models.CharField(max_length=255, blank=False)
    image = models.ForeignKey(
        get_image_model_string(),
        null=True,
        blank=False,
        on_delete=models.PROTECT,
        related_name="+",
    )
    status = models.CharField(
        max_length=50,
        blank=False,
        choices=OUTBREAKS_STATUS_CHOICES,
        default=OUTBREAKS_STATUS_DEFAULT,
    )
    content = StreamField(
        [
            ("text", RichTextBlock()),
            ("alert", AlertBlock()),
            ("data_table", DataTableBlock()),
        ],
        blank=False,
    )

    content_panels = Page.content_panels + [
        MultiFieldPanel(
            [
                FieldPanel(
                    "description",
                    help_text="Brief text summary that will be displayed on the outbreaks card.",
                ),
                FieldPanel(
                    "image",
                    help_text="Thumbnail image that will be displayed on the outbreaks card.",
                ),
            ],
            heading="Card details",
        ),
        FieldPanel(
            "status",
            help_text=(
                "The current status of the outbreak and will be used to "
                "group outbreaks on the index page. 'Ongoing' outbreaks are "
                "displayed in the order they appear in the page explorer. "
                "Click 'sort menu order' to reorder 'Ongoing' outbreaks. "
                "'Historical' outbreaks are always sorted alphabetically by title."
            ),
        ),
        FieldPanel(
            "content",
            help_text="The main content for the outbreak page.",
        ),
    ]

    def get_context(self, request: HttpRequest) -> dict[str, Any]:
        """Add the parent page's title to the context for display on the outbreak page."""

        # Importing here to avoid circular import issues
        from cms.pages.outbreaks_index import OutbreaksIndexPage

        context = super().get_context(request)
        parent = self.get_ancestors().type(OutbreaksIndexPage).specific().first()
        context["page_heading"] = parent.title if parent else ""
        return context
