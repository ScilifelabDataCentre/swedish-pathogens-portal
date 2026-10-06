"""CMS pages for topics."""

from datetime import date
from typing import Any

from django.db import models
from django.http import HttpRequest
from wagtail.admin.panels import FieldPanel, MultiFieldPanel
from wagtail.blocks import RichTextBlock
from wagtail.fields import StreamField
from wagtail.images import get_image_model_string
from wagtail.models import Page

from cms.blocks import AlertBlock


class TopicPage(Page):
    """A page representing a single topic.

    This page is intended to be used as a child of TopicsIndexPage. It represents
    a single topic and can contain content related to that topic.

    Attributes:
        description (str): A brief description of the topic.
        image (ForeignKey): An image associated with the topic (actually saved as a foreign key).
        content (StreamField): A stream field for the page content, allowing rich text.
    """

    template = "cms/pages/topic.html"
    parent_page_types = ["cms.TopicsIndexPage"]
    subpage_types = []

    description = models.CharField(max_length=255, blank=False)
    image = models.ForeignKey(
        get_image_model_string(),
        null=True,
        blank=False,
        on_delete=models.PROTECT,
        related_name="+",
    )
    content = StreamField(
        [
            ("text", RichTextBlock()),
            ("alert", AlertBlock()),
        ],
        blank=False,
    )

    content_panels = Page.content_panels + [
        MultiFieldPanel(
            [
                FieldPanel(
                    "description",
                    help_text="Brief text summary that will be displayed on the topics card.",
                ),
                FieldPanel(
                    "image",
                    help_text="Thumbnail image that will be displayed on the topics card.",
                ),
            ],
            heading="Card details",
        ),
        FieldPanel(
            "content",
            help_text="The main content for the topic page.",
        ),
    ]

    @property
    def tagged_highlights_and_editorials(self) -> models.QuerySet:
        """Return highlights and editorials related to this topic."""

        # Importing here to avoid circular import issues
        from cms.pages.highlights_and_editorials import HighlightsAndEditorialsPage

        # To avoid error in TopicPage preview in Wagtail admin when the page is first created
        if not self.pk:
            return HighlightsAndEditorialsPage.objects.none()

        return (
            HighlightsAndEditorialsPage.objects.live()
            .public()
            .filter(article_topics__topic=self)
            .distinct()
            .order_by("-first_published_at")
        )

    @property
    def tagged_dashboards(self) -> models.QuerySet:
        """Return dashboards related to this topic."""

        # Importing here to avoid circular import issues
        from cms.pages.dashboard import DashboardPage

        # To avoid error in TopicPage preview in Wagtail admin when the page is first created
        if not self.pk:
            return DashboardPage.objects.none()

        return (
            DashboardPage.objects.live()
            .public()
            .filter(dashboard_topics__topic=self)
            .distinct()
            .specific()
        )

    def get_context(self, request: HttpRequest) -> dict[str, Any]:
        """Add the parent page's title to the context for display on the topic page."""

        # Importing here to avoid circular import issues
        from cms.pages.dashboard_index import DashboardIndexPage
        from cms.pages.highlights_and_editorials_index import HighlightsAndEditorialsIndexPage
        from cms.pages.topics_index import TopicsIndexPage

        context = super().get_context(request)

        parent = self.get_ancestors().type(TopicsIndexPage).specific().first()
        context["page_heading"] = parent.title if parent else ""

        context["tagged_articles_count"] = self.tagged_highlights_and_editorials.count()
        context["tagged_highlights_and_editorials"] = self.tagged_highlights_and_editorials[:3]
        highlights_and_editorials_index = HighlightsAndEditorialsIndexPage.objects.live().first()
        context["articles_index_url"] = (
            highlights_and_editorials_index.url if highlights_and_editorials_index else ""
        )

        context["tagged_dashboards_count"] = self.tagged_dashboards.count()
        context["tagged_dashboards"] = sorted(
            self.tagged_dashboards,
            key=lambda d: (-(d.dashboard_data_updated_at or date.min).toordinal(), d.title.lower()),
        )[:3]
        dashboard_index = DashboardIndexPage.objects.live().first()
        context["dashboards_index_url"] = dashboard_index.url if dashboard_index else ""
        return context
