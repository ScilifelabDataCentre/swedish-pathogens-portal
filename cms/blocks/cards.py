"""Card-related StructBlock definitions for StreamField content."""

from typing import Any

from django import forms
from wagtail import blocks
from wagtail.images.blocks import ImageChooserBlock

ALLOWED_DESCRIPTION_FEATURES = ["bold", "italic", "link"]


class CardBlock(blocks.StructBlock):
    """Single teaser card that links to an external URL (new tab).

    May be used alone or as rows inside a ``CardGridBlock`` list.

    Attributes:
        image: Hero image at the top of the card.
        title: Primary heading (max 120 characters).
        description: Supporting text under the title (max 300 characters).
        url: Destination URL (full ``https://`` URL; opens in a new tab).
    """

    image = ImageChooserBlock(
        required=True,
        help_text="Image shown at the top of the card (required).",
    )
    title = blocks.CharBlock(
        required=True,
        max_length=120,
        help_text="Card heading (max 120 characters).",
    )
    description = blocks.RichTextBlock(
        required=True,
        features=ALLOWED_DESCRIPTION_FEATURES,
        max_length=300,
        help_text="Short supporting text under the title (max 300 characters).",
    )
    url = blocks.URLBlock(
        required=True,
        help_text="Full URL (https://…). Opens in a new browser tab.",
    )

    def get_context(
        self, value: dict[str, Any], parent_context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Include `truncate_text` in the context for the card template."""

        # get the value of truncate_text from the parent context before calling
        # super().get_context, this is important because in nested blocks, the
        # parent context may not be available after calling super().get_context
        truncate_text = (
            parent_context.get("value", {}).get("truncate_text", True) if parent_context else True
        )

        context = super().get_context(value, parent_context)
        context["truncate_text"] = truncate_text

        return context

    class Meta:
        """Set meta values."""

        icon = "placeholder"
        label = "Card (External Link)"
        collapsed = True
        label_format = "{title}"
        template = "cms/blocks/card.html"


class CardGridBlock(blocks.StructBlock):
    """Grid container for multiple card blocks.

    Allows editors to add a list of cards manually that will typically be rendered
    in a grid layout on the frontend.

    Attributes:
        cards: Ordered list of card blocks (minimum one).
        truncate_text: If checked, the title and description text in the cards will
            be truncated to fit the card layout.
    """

    truncate_text = blocks.BooleanBlock(
        required=False,
        default=True,
        help_text=(
            "If checked, the title and description text in the card "
            "will be truncated to fit the card layout."
        ),
    )
    cards = blocks.ListBlock(
        CardBlock(),
        min_num=1,
        label="Cards",
        collapsed=True,
        help_text="Add at least one card. Each card links to an external URL.",
    )

    class Meta:
        """Set meta values."""

        icon = "table"
        label = "Card Grid (External Links)"
        help_text = "Two- or three-column grid of external-link cards on the public site."
        template = "cms/blocks/card_grid.html"


class CatalogueCardBlock(CardBlock):
    """Card block variant for linking to internal catalogue records.

    Inherits all fields from CardBlock but enforces a specific "type" and "keywords" field for
    filtering and searching catalogue records. Uses the same template as CardBlock since the
    additional fields are for filtering/searching and not displayed on the card itself.

    Attributes:
        type: catalogue type, used in filtering and labeling (max 120 characters).
        keywords: Comma-separated keywords for filtering (max 300 characters).
    """

    type = blocks.CharBlock(
        required=True,
        max_length=120,
        help_text="Comma-separated types, used in filtering and labeling (Max 120 characters).",
    )

    keywords = blocks.TextBlock(
        required=False,
        max_length=300,
        help_text="Optional comma-separated keywords for filtering (Max 300 characters).",
    )

    class Meta:
        """Set meta values."""

        icon = "placeholder"
        label = "Catalogue card"
        collapsed = True
        label_format = "{title}"
        template = "cms/blocks/card.html"


class CatalogueCardGridBlock(blocks.StructBlock):
    """Grid block variant for catalogue cards.

    Allows editors to add a list of catalogue cards manually that will typically be rendered
    in a grid layout on the frontend. Each card includes additional fields for catalogue type
    and keywords to support filtering and searching of catalogue records.

    Uses the same template as CardGridBlock since the additional fields are for
    filtering/searching and not displayed on the card itself.

    Attributes:
        cards: Ordered list of catalogue card blocks (minimum one).
        truncate_text: If checked, the title and description text in the cards will
            be truncated to fit the card layout.
    """

    truncate_text = blocks.BooleanBlock(
        required=False,
        default=True,
        help_text=(
            "If checked, the title and description text in the card "
            "will be truncated to fit the card layout."
        ),
    )
    cards = blocks.ListBlock(
        CatalogueCardBlock(),
        min_num=1,
        label="Catalogue cards",
        collapsed=True,
        help_text=(
            "Add at least one card. Each card links to an external URL and includes "
            "catalogue type and keywords for filtering."
        ),
    )

    class Meta:
        """Set meta values."""

        icon = "table"
        label = "Catalogue card grid"
        help_text = "Two- or three-column grid of cards linking to external catalogue records."
        template = "cms/blocks/card_grid.html"


class ChildPageCardBlock(blocks.StructBlock):
    """Teaser cards for **published** child pages of a chosen parent page.

    Ordering and a cap on how many children to show are configurable. Child page
    models should eventually expose listing image and teaser fields expected by the
    template; until then, use only with page types that support that contract.

    Attributes:
        parent_page (PageChooserBlock): Parent page to pull child pages from.
        num_children (ChoiceBlock): How many child pages to display ("all" or "3").
        order_by (ChoiceBlock): Field to order child pages by ("latest" or "title").
    """

    # TODO: After the page models are implemented, this block either needs to be updated or
    # the block's template need to be updated to include more information like date, topic, etc.
    #
    # Depending on the need, a new block based on this one could be created to cover additional
    # use cases. For example, a block that allows selecting specific pages instead of pulling all
    # children from a parent page. We can discuss then and decide to either update this block
    # or create a new ones.
    #
    # For now, this block is a placeholder to demonstrate how to pull child pages and display
    # them as cards easily.

    parent_page = blocks.PageChooserBlock(
        help_text="Only published child pages of this page are shown, in the chosen order below."
    )
    num_children = blocks.ChoiceBlock(
        choices=[
            ("all", "All"),
            ("3", "First 3"),
        ],
        default="all",
        label="Number of child pages",
        widget=forms.RadioSelect,
        help_text="Show every matching child page, or cap the list at three (after sorting).",
    )
    order_by = blocks.ChoiceBlock(
        choices=[
            ("created", "Created date (newest first)"),
            ("updated", "Updated date (newest first)"),
            ("title", "Title (A-Z)"),
        ],
        default="created",
        label="Order by",
        widget=forms.RadioSelect,
        help_text="Sort child pages by first publish date, last publish date, or title.",
    )

    def get_context(
        self, value: dict[str, Any], parent_context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Build template context with the resolved child page queryset.

        Args:
            value: Cleaned block value from the stream.
            parent_context: Optional context from the parent template.

        Returns:
            Context dict including ``child_pages`` (queryset or slice) or an empty list.
        """
        context = super().get_context(value, parent_context)
        parent = value.get("parent_page")

        if parent:
            pages = parent.get_children().live().specific()

            # Order pages
            if value.get("order_by") == "created":
                pages = pages.order_by("-first_published_at")
            elif value.get("order_by") == "updated":
                pages = pages.order_by("-last_published_at")
            elif value.get("order_by") == "title":
                pages = pages.order_by("title")

            # Limit number of pages
            if value.get("num_children") == "3":
                pages = pages[:3]

            context["child_pages"] = pages
        else:
            context["child_pages"] = []

        return context

    class Meta:
        """Set meta values."""

        icon = "form"
        label = "Child page cards"
        help_text = (
            "Lists published child pages as teaser cards. Page types should provide "
            "listing image and teaser fields when those exist; until then, use only "
            "where the template matches your page model."
        )
        template = "cms/blocks/card_child_pages.html"
