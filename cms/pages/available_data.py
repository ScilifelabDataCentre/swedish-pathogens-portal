"""Available Data Page that displays EBI dataset counts by category."""

from django.http import HttpRequest, HttpResponse
from wagtail.admin.panels import FieldPanel
from wagtail.blocks import RichTextBlock
from wagtail.fields import StreamField
from wagtail.models import Page

from cms.blocks import AlertBlock


class AvailableDataPage(Page):
    """Available data page that displays EBI dataset counts by category.

    Attributes:
        content (StreamField): StreamField with three content block types:
            - RichTextBlock: formatted text (headings, bold, italic, links, lists)
            - AlertBlock: callout/notice box
            - StaticBlock "available_data": displays the EBI dataset counts. TODO
    """

    template = "cms/pages/available_data/index.html"
    parent_page_types = ["cms.HomePage"]
    subpage_types = []
    max_count = 1

    content = StreamField(
        [
            ("text", RichTextBlock()),
            ("alert", AlertBlock()),
        ],
        blank=False,
    )

    content_panels = Page.content_panels + [FieldPanel("content")]

    def serve(self, request: HttpRequest) -> HttpResponse:
        """Serve the available data page.

        If the request is made via HTMX, render the dataset counts partial
        template, otherwise render the full page.
        """
        # if request.htmx: TODO
        #     return render_available_data_partial(request=request, page=self)
        return super().serve(request)
