"""CMS page for outbreaks index."""

from typing import Any

from django.http import HttpRequest
from wagtail.admin.panels import FieldPanel
from wagtail.blocks import RichTextBlock
from wagtail.fields import StreamField
from wagtail.models import Page, PageQuerySet

from cms.blocks import AlertBlock


class OutbreaksIndexPage(Page):
    """A page listing all outbreaks.

    This page is intended to be used as a parent page for OutbreakPage instances.
    Only one instance of this page can exist. Child outbreak pages will be listed
    as cards on this page.

    Attributes:
        content (StreamField): A stream field for the page content, allowing rich text.
    """

    max_count = 1
    template = "cms/pages/outbreaks_index.html"
    parent_page_types = ["cms.HomePage"]
    subpage_types = ["cms.OutbreakPage"]

    content = StreamField(
        [
            ("text", RichTextBlock()),
            ("alert", AlertBlock()),
        ],
        blank=True,
    )

    content_panels = Page.content_panels + [
        FieldPanel("content"),
    ]

    def get_context(self, request: HttpRequest) -> dict[str, Any]:
        """Add child outbreaks to the context."""

        # Importing here to avoid circular imports
        from cms.pages.outbreaks import OUTBREAKS_STATUS_CHOICES, OutbreakPage

        context = super().get_context(request)

        all_outbreaks: dict[str, PageQuerySet] = {}
        for _type, _label in OUTBREAKS_STATUS_CHOICES:
            fetched_outbreaks = (
                self.get_children()
                .type(OutbreakPage)
                .live()
                .public()
                .filter(outbreakpage__status=_type)
                .specific()
            )
            if fetched_outbreaks:
                all_outbreaks[_type] = fetched_outbreaks
        context["outbreaks"] = all_outbreaks

        return context
