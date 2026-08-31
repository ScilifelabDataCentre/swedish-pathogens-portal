"""CMS page for individual dashboards."""

from datetime import date
from typing import TYPE_CHECKING, Any

from django.db import models
from django.http import HttpRequest
from django.utils import timezone
from django.utils.functional import cached_property
from modelcluster.fields import ParentalKey
from wagtail.admin.panels import FieldPanel, InlinePanel, MultiFieldPanel, PageChooserPanel
from wagtail.blocks import RichTextBlock
from wagtail.fields import StreamField
from wagtail.images import get_image_model_string
from wagtail.models import Orderable, Page

from cms.blocks import (
    AlertBlock,
    CollapsibleBlock,
    DataTableBlock,
    LastUpdatedBlock,
    PlotlyFigureBlock,
    StaticFigureBlock,
)

# Only import TopicPage for type checking to avoid circular imports
if TYPE_CHECKING:
    from cms.pages.topics import TopicPage
    from cms.snippets.dashboard_data import DashboardData

DATA_STATUS_CHOICES = [
    ("active", "Active"),
    ("historic", "Historic"),
]


class DashboardTopic(Orderable):
    """A model representing the many-to-many relationship.

    This model represents the many-to-many relationship between dashboards and topics.

    Attributes:
    page (ParentalKey): The dashboard page that this topic is associated with.
    topic (ForeignKey): The topic that is associated with the dashboard.
    """

    page = ParentalKey(
        "cms.DashboardPage",
        on_delete=models.CASCADE,
        related_name="dashboard_topics",
    )
    topic = models.ForeignKey("cms.TopicPage", on_delete=models.CASCADE)

    panels = [
        PageChooserPanel("topic", "cms.TopicPage"),
    ]

    class Meta:
        """Meta options for the DashboardTopic model."""

        verbose_name = "Related Topic"
        verbose_name_plural = "Related Topics"


class DashboardEbiPathogen(Orderable):
    """An EBI pathogen type associated with a dashboard page."""

    page = ParentalKey(
        "cms.DashboardPage",
        on_delete=models.CASCADE,
        related_name="ebi_type_of_pathogens",
    )
    ebi_type_of_pathogen = models.CharField(
        max_length=255,
        verbose_name="Type of pathogen",
    )

    panels = [
        FieldPanel("ebi_type_of_pathogen"),
    ]

    class Meta:
        """Meta options for the EBI pathogen type."""

        verbose_name = "EBI type of pathogen"
        verbose_name_plural = "EBI types of pathogen"


class DashboardPage(Page):
    """A page representing a single data dashboard.

    Displays data visualisations (Plotly charts or static figures) along with
    explanatory text. Card fields (description, image, data_status) are used
    by the parent DashboardIndexPage for the card grid listing.

    Attributes:
        show_toc: Whether to generate and display a table of contents sidebar.
        description: Brief text for the index card.
        image: Thumbnail image for the index card.
        data_status: Whether the dashboard data is active or historic.
        keywords: Optional keywords for searching.
        ebi_data_type: Data type shown in the European Pathogens Portal catalogue.
        ebi_data_source: Data source shown in the European Pathogens Portal catalogue.
        content: StreamField with text, collapsible sections, alerts, and figure blocks.
    """

    template = "cms/pages/dashboard.html"
    parent_page_types = ["cms.DashboardIndexPage"]
    subpage_types = []

    show_toc = models.BooleanField(default=False, blank=True, verbose_name="Show TOC")
    description = models.CharField(max_length=255, blank=False)
    image = models.ForeignKey(
        get_image_model_string(),
        null=True,
        blank=False,
        on_delete=models.PROTECT,
        related_name="+",
    )
    data_status = models.CharField(
        max_length=50,
        choices=DATA_STATUS_CHOICES,
    )
    keywords = models.TextField(blank=True)
    ebi_data_type = models.CharField(max_length=255, blank=True)
    ebi_data_source = models.CharField(max_length=255, blank=True)
    content = StreamField(
        [
            ("text", RichTextBlock()),
            ("alert", AlertBlock()),
            ("collapsible", CollapsibleBlock()),
            ("data_table", DataTableBlock()),
            ("last_updated", LastUpdatedBlock()),
            ("plotly_figure", PlotlyFigureBlock()),
            ("static_figure", StaticFigureBlock()),
        ],
        blank=False,
    )

    content_panels = Page.content_panels + [
        MultiFieldPanel(
            [
                FieldPanel(
                    "description",
                    help_text="Brief text displayed on the dashboard index card.",
                ),
                FieldPanel(
                    "image",
                    help_text="Thumbnail image displayed on the dashboard index card.",
                ),
            ],
            heading="Card details",
        ),
        FieldPanel(
            "data_status",
            help_text="Whether this dashboard's data is active or historic.",
        ),
        InlinePanel(
            "dashboard_topics",
            classname="collapsed",
            help_text="Research topics associated with this dashboard.",
        ),
        FieldPanel(
            "keywords",
            help_text=("Comma-separated keywords for related content matching and search"),
        ),
        MultiFieldPanel(
            [
                FieldPanel("ebi_data_type"),
                InlinePanel(
                    "ebi_type_of_pathogens",
                    label="Type of pathogen",
                    help_text="Add one or more pathogen types for the EBI catalogue.",
                ),
                FieldPanel("ebi_data_source"),
            ],
            heading="EBI / European Pathogens Portal",
            help_text=(
                "The catalogue name uses the dashboard Title. "
                "Enter the remaining catalogue values here."
            ),
            classname="collapsed",
        ),
        FieldPanel(
            "content",
            help_text="Main content: short intro, collapsible long text, charts, and figures.",
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
        FieldPanel(
            "first_published_at",
            help_text=(
                "The page creation date that will be displayed on the card, if the dashboard "
                "doesn't have a corresponding data update timestamp."
            ),
        ),
    ]

    @property
    def topics(self) -> list[TopicPage]:
        """Return a sorted list of topics associated with this dashboard."""
        return sorted((rel.topic for rel in self.dashboard_topics.all()), key=lambda t: t.title)

    @property
    def keyword_list(self) -> list[str]:
        """Return keywords as a list of cleaned strings."""
        if not self.keywords.strip():
            return []
        return [tag.strip().lower() for tag in self.keywords.split(",") if tag.strip()]

    @cached_property
    def dashboard_data(self) -> DashboardData | None:
        """Return a dictionary of data figures for this dashboard."""
        from cms.snippets.dashboard_data import DashboardData

        return DashboardData.get_data(self.slug)

    @property
    def dashboard_data_updated_at(self) -> date | None:
        """Return the last updated timestamp for the dashboard data or the first published date."""
        data_date = getattr(self.dashboard_data, "data_updated_at", None)
        if data_date:
            return data_date
        if self.first_published_at:
            return timezone.localdate(self.first_published_at)
        return None

    def get_context(self, request: HttpRequest) -> dict[str, Any]:
        """Add DashboardData figures, CSV URL, and parent heading to template context."""

        # Importing here to avoid circular import issues
        from cms.pages.dashboard_index import DashboardIndexPage

        context = super().get_context(request)
        context["dashboard_data"] = self.dashboard_data
        context["figures"] = getattr(self.dashboard_data, "data", {})
        context["data_updated_at"] = self.dashboard_data_updated_at
        context["source_file_hash"] = getattr(self.dashboard_data, "source_file_hash", "")

        parent = self.get_ancestors().type(DashboardIndexPage).specific().first()
        context["page_heading"] = parent.title if parent else ""
        return context
