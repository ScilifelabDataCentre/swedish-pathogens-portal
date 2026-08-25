"""Available Data Page that displays EBI dataset counts by category."""

from django.http import HttpRequest, HttpResponse
from wagtail.admin.panels import FieldPanel
from wagtail.blocks import RichTextBlock, StaticBlock
from wagtail.fields import StreamField
from wagtail.models import Page

from cms.blocks import AlertBlock
from cms.services.available_data import render_available_data_partial


class AvailableDataPage(Page):
    """Available data page that displays EBI dataset counts by category.

    Attributes:
        content (StreamField): StreamField with three content block types:
            - RichTextBlock: formatted text (headings, bold, italic, links, lists)
            - AlertBlock: callout/notice box
            - StaticBlock "available_data": displays the EBI dataset counts.
    """

    template = "cms/pages/available_data/index.html"
    parent_page_types = ["cms.HomePage"]
    subpage_types = []
    max_count = 1

    content = StreamField(
        [
            ("text", RichTextBlock()),
            ("alert", AlertBlock()),
            (
                "available_data",
                StaticBlock(
                    admin_text=(
                        "Displays EBI dataset counts by category, loaded via HTMX. "
                        "NOTE: This requires the page to be published until then, previewing it "
                        "will show an error instead of the counts."
                    ),
                    template="cms/pages/available_data/partials/available_data_section.html",
                ),
            ),
        ],
        blank=False,
        block_counts={"available_data": {"min_num": 1, "max_num": 1}},
    )

    content_panels = Page.content_panels + [FieldPanel("content")]

    def serve(self, request: HttpRequest) -> HttpResponse:
        """Serve the available data page.

        If the request is made via HTMX, render the dataset counts partial
        template, otherwise render the full page.
        """
        if request.htmx:
            return render_available_data_partial(request=request, page=self)
        return super().serve(request)
