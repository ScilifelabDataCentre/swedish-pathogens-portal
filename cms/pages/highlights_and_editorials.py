"""CMS pages for highlights and editorials."""

from typing import TYPE_CHECKING, Any

from django.db import models
from django.http import HttpRequest
from modelcluster.fields import ParentalKey
from wagtail.admin.panels import FieldPanel, InlinePanel, MultiFieldPanel, PageChooserPanel
from wagtail.blocks import RichTextBlock
from wagtail.fields import RichTextField, StreamField
from wagtail.images import get_image_model_string
from wagtail.models import Orderable, Page
from wagtail.search import index

from cms.blocks import AlertBlock
from cms.services.highlights_and_editorials import get_related_articles

# Only import TopicPage for type checking to avoid circular imports
if TYPE_CHECKING:
    from cms.pages.topics import TopicPage

ARTICLE_TYPE_CHOICES = [
    ("data-highlight", "Data Highlight"),
    ("editorial", "Editorial"),
]


class HighlightsAndEditorialsTopic(Orderable):
    """A model representing the many-to-many relationship.

    This model represents the many-to-many relationship between highlights/editorials and topics.

    Attributes:
    page (ParentalKey): The highlight or editorial page that this topic is associated with.
    topic (ForeignKey): The topic that is associated with the highlight or editorial.
    """

    page = ParentalKey(
        "cms.HighlightsAndEditorialsPage",
        on_delete=models.CASCADE,
        related_name="article_topics",
    )
    topic = models.ForeignKey("cms.TopicPage", on_delete=models.CASCADE)

    panels = [
        PageChooserPanel("topic", "cms.TopicPage"),
    ]

    class Meta:
        """Meta options for the HighlightsAndEditorialsTopic model."""

        verbose_name = "Related Topic"
        verbose_name_plural = "Related Topics"


class HighlightsAndEditorialsPage(Page):
    """A page representing a single highlight or editorial.

    This page is intended to be a child of HighlightsAndEditorialsIndexPage.
    It will be displayed as a card on the index page.

    Attributes:
        description (str): A brief description of the highlight or editorial.
        image (ForeignKey): An image associated with the highlight or editorial
            (actually saved as a foreign key).
        image_caption (str): An optional caption for the image.
        article_type (str): The type of the article, either "data_highlight" or "editorial".
        announcement (str): An optional announcement message for the article,
            supporting basic rich text formatting.
        keywords (str): An optional comma-separated string of keywords for related content
            matching and search.
        author (str): An optional author name or names for the article.
        content (StreamField): A stream field for the page content, allowing rich text.
    """

    template = "cms/pages/highlights_and_editorials.html"
    parent_page_types = ["cms.HighlightsAndEditorialsIndexPage"]
    subpage_types = []

    description = models.CharField(max_length=255, blank=False)
    image = models.ForeignKey(
        get_image_model_string(),
        null=True,
        blank=False,
        on_delete=models.PROTECT,
        related_name="+",
    )
    image_caption = models.CharField(max_length=255, blank=True)
    article_type = models.CharField(
        max_length=50,
        blank=False,
        choices=ARTICLE_TYPE_CHOICES,
    )
    announcement = RichTextField(features=["bold", "italic", "link", "ol", "ul"], blank=True)
    keywords = models.TextField(blank=True)
    author = models.CharField(max_length=255, blank=True)
    content = StreamField(
        [
            ("text", RichTextBlock()),
            ("alert", AlertBlock()),
        ],
        blank=True,
    )

    search_fields = Page.search_fields + [
        index.SearchField("description"),
        index.SearchField("content"),
        index.SearchField("keywords"),
        index.SearchField("announcement"),
        index.SearchField("author"),
        index.AutocompleteField("title"),
    ]

    content_panels = Page.content_panels + [
        MultiFieldPanel(
            [
                FieldPanel(
                    "description",
                    help_text=(
                        "Brief text summary that will be displayed on the highlights "
                        "and editorials card."
                    ),
                ),
                FieldPanel(
                    "image",
                    help_text=(
                        "Thumbnail image that will be displayed on the highlights "
                        "and editorials card."
                    ),
                ),
                FieldPanel(
                    "image_caption",
                    help_text=(
                        "Optional caption for the thumbnail image. Displayed on the "
                        "article page but not on the card."
                    ),
                ),
            ],
            heading="Card details",
        ),
        FieldPanel(
            "article_type",
            help_text=("The type of the article i.e., highlight or editorial."),
        ),
        InlinePanel(
            "article_topics",
            classname="collapsed",
            help_text="Research topics associated with this highlight or editorial.",
        ),
        MultiFieldPanel(
            [
                FieldPanel(
                    "announcement",
                    help_text=(
                        "Optional announcement message supported by basic rich text formatting. "
                        "Displayed prominently at the top of the page, above the main content."
                    ),
                ),
                FieldPanel(
                    "keywords",
                    help_text=("Comma-separated keywords for related content matching and search"),
                ),
                FieldPanel(
                    "author",
                    help_text=(
                        "Optional author name or names for the article. "
                        "Displayed on the article page but not used for search or filtering."
                    ),
                ),
            ],
            heading="Optional metadata",
            classname="collapsed",
        ),
        FieldPanel(
            "content",
            help_text="The main content for the highlights and editorials page.",
        ),
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

    @property
    def topics(self) -> list[TopicPage]:
        """Return a sorted list of topics associated with this article."""
        return sorted((rel.topic for rel in self.article_topics.all()), key=lambda t: t.title)

    @property
    def keyword_list(self) -> list[str]:
        """Return keywords as a list of cleaned strings."""
        if not self.keywords.strip():
            return []
        return [tag.strip().lower() for tag in self.keywords.split(",") if tag.strip()]

    def get_context(self, request: HttpRequest) -> dict[str, Any]:
        """Add the parent page's title to the context for display on the page."""

        # Importing here to avoid circular import issues
        from cms.pages.highlights_and_editorials_index import HighlightsAndEditorialsIndexPage

        parent = self.get_ancestors().type(HighlightsAndEditorialsIndexPage).specific().first()
        context = super().get_context(request)
        context["page_heading"] = parent.title if parent else ""
        context["related_articles"] = get_related_articles(self)
        return context
