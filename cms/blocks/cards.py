"""Card-related StructBlock definitions for StreamField content."""

from wagtail import blocks
from wagtail.images.blocks import ImageChooserBlock

ALLOWED_CARD_DESCRIPTION_FEATURES = ["bold", "italic"]


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
        features=ALLOWED_CARD_DESCRIPTION_FEATURES,
        max_length=255,
        help_text="Short supporting text under the title (max 255 characters).",
    )
    url = blocks.URLBlock(
        required=True,
        help_text="Full URL (https://…). Opens in a new browser tab.",
    )

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
    """

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
    """

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
