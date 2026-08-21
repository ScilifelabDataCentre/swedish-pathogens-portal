"""Basic content page model with a StreamField body."""

from django.db import models
from wagtail.admin.panels import FieldPanel
from wagtail.blocks import RichTextBlock, StaticBlock
from wagtail.fields import StreamField
from wagtail.models import Page

from cms.blocks import AlertBlock, CollapsibleBlock, DataTableBlock


class BasicPage(Page):
    """Simple content page with a reorderable stream of common blocks.

    Attributes:
        show_toc: Whether to generate and display a table of contents sidebar.
        content (StreamField): StreamField with five content block types:
            - RichTextBlock: formatted text (headings, bold, italic, links, lists)
            - AlertBlock: callout/notice box
            - DataTableBlock: interactive table with search and pagination
            - CollapsibleBlock: ``<details>`` accordion with a rich-text body
            - StaticBlock: Matomo analytics opt-out widget
    """

    template = "cms/pages/basic_page.html"

    show_toc = models.BooleanField(default=False, blank=True, verbose_name="Show TOC")

    content = StreamField(
        [
            (
                "text",
                RichTextBlock(
                    verbose_name="Text (rich)",
                    help_text="Main body copy. Use headings for structure; images optional.",
                ),
            ),
            ("alert", AlertBlock()),
            ("data_table", DataTableBlock()),
            ("collapsible", CollapsibleBlock()),
            (
                "matomo_opt_out",
                StaticBlock(
                    admin_text=("Displays the Matomo analytics opt-out widget."),
                    template="cms/components/matomo_opt_out.html",
                ),
            ),
        ],
        blank=True,
        block_counts={
            "matomo_opt_out": {"max_num": 1},
        },
    )

    content_panels = Page.content_panels + [
        FieldPanel(
            "content",
            help_text="Drag blocks to reorder. Each block type has its own fields and help text.",
        ),
    ]

    promote_panels = Page.promote_panels + [
        FieldPanel(
            "show_toc",
            help_text=(
                "If checked, a table of contents will be generated from "
                "headings in the content and displayed in a sidebar."
            ),
        ),
    ]
