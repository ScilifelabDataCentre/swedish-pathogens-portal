"""Page details structure blocks for use in StreamFields."""

from typing import Any

import structlog
from django import forms
from django.core.exceptions import ValidationError
from wagtail import blocks

LOGGER = structlog.get_logger(__name__)

order_by_choices = [
    ("title", "Title (A-Z)"),
    ("created", "Created date (newest first)"),
    ("updated", "Updated date (newest first)"),
    ("data_updated", "Data updated date (newest first)"),
]

order_by_mapping = {
    "created": "-first_published_at",
    "updated": "-last_published_at",
    "title": "title",
}


class PageSectionBlock(blocks.StructBlock):
    """Page section block for displaying information about a selected page.

    A selected page's details can be displayed along with a list of its child pages.
    The block allows for optional customization of the section title and description,
    as well as the ordering of child pages.

    Attributes:
        page (PageChooserBlock): The page to display details for.
        title (CharBlock): Optional section title, defaults to the page title if not provided.
        description (RichTextBlock): Optional section description text.
        order_by (ChoiceBlock): Field to order child pages by ("latest" or "title").
        show_badge_in_child_pages (BooleanBlock): Whether to show a 'type' badge on each child card.
        show_date_in_child_pages (BooleanBlock): Whether to show the date on each child card.
        show_topics_in_child_pages (BooleanBlock): Whether to show the topics on each child card.
    """

    page = blocks.PageChooserBlock(help_text="Select a page to display its details.")
    title = blocks.CharBlock(
        max_length=100,
        required=False,
        help_text="Optional section title, if not given, the page title will be used.",
    )
    description = blocks.RichTextBlock(
        required=False,
        help_text="Optional section description text.",
    )
    order_by = blocks.ChoiceBlock(
        choices=order_by_choices,
        default="title",
        label="Order by",
        widget=forms.RadioSelect,
        help_text=(
            "Sort child pages by title, first publish date, last publish date, "
            "or data updated date (for Dashboards)."
        ),
    )
    show_badge_in_child_pages = blocks.BooleanBlock(
        required=False,
        default=False,
        help_text="Show a badge text on each child card.",
    )
    show_date_in_child_pages = blocks.BooleanBlock(
        required=False,
        default=False,
        help_text="Show the date on each child card.",
    )
    show_topics_in_child_pages = blocks.BooleanBlock(
        required=False,
        default=False,
        help_text="Show the topics on each child card.",
    )

    def clean(self, value: dict[str, Any]) -> dict[str, Any]:
        """Clean the block value and ensure the selected page is live and public.

        Args:
            value: The block value to clean.
        """
        cleaned_value = super().clean(value)
        page = cleaned_value.get("page")

        if page:
            if not page.live:
                raise ValidationError({"page": "Draft pages cannot be selected."})
            if page.get_view_restrictions().exists():
                raise ValidationError({"page": "Private pages cannot be selected."})

        return cleaned_value

    def get_context(
        self, value: dict[str, Any], parent_context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Build template context with the resolved child page queryset.

        Args:
            value: Cleaned block value from the stream.
            parent_context: Optional context from the parent template.

        Returns:
            Context dict including ``section_child_pages`` (queryset or slice) or an empty list.
        """
        context = super().get_context(value, parent_context)
        page = value.get("page")
        order_by = value.get("order_by")

        # if the selected page is deleted or converted to a draft or set to private
        # return an empty list of child pages
        if not page or not page.live or page.get_view_restrictions().exists():
            context["invalid_page"] = True
            return context

        child_pages = page.get_children().live().public().specific()

        try:
            # This option is meant only for dashboard pages, and the dashboard_data_updated_at
            # is not a field but a property, so instead of sorting it in DB we sort it in Python.
            if order_by == "data_updated":
                child_pages = sorted(
                    child_pages,
                    key=lambda p: p.dashboard_data_updated_at or p.first_published_at,
                    reverse=True,
                )
            else:
                order_by = order_by_mapping.get(order_by, "title")
                child_pages = child_pages.order_by(order_by)
        except Exception:
            LOGGER.exception(
                "Error occurred while sorting child pages", page=page, order_by=order_by
            )

        # Build a list of child page details to include in the context for
        # rendering to avoid conditional logic in the template and to allow
        # for additional fields like badges, dates, and topics. There are
        # better ways to do this, which requires some refactoring on the
        # page model. So decided to go with this is a simple approach that
        # works for the needed pages. Refactoring can be done later if needed.
        children = []
        for child in child_pages[:3]:
            child_info = {
                "title": child.title,
                "description": getattr(child, "description", ""),
                "url": child.url,
                "image": getattr(child, "image", None),
            }

            if value.get("show_badge_in_child_pages"):
                if "dashboard" in page.url:
                    badge_text = child.data_status
                elif "highlights" in page.url:
                    badge_text = child.article_type
                else:
                    badge_text = getattr(child, "type", None)
                child_info["badge"] = badge_text

            if value.get("show_date_in_child_pages"):
                if "dashboard" in page.url:
                    card_date = child.dashboard_data_updated_at
                else:
                    card_date = child.first_published_at
                child_info["date"] = card_date

            if value.get("show_topics_in_child_pages"):
                child_info["topics"] = getattr(child, "topics", [])

            children.append(child_info)

        context["section_children"] = children
        return context

    class Meta:
        """Set meta values."""

        icon = "form"
        label = "Page Section"
        help_text = "Block to add a section with details of a selected page and its child pages."
        template = "cms/blocks/page_section.html"
