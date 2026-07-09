"""CMS page for dashboard index."""

from datetime import date
from typing import Any

from django.db import models
from django.http import HttpRequest, HttpResponse
from wagtail.admin.panels import FieldPanel
from wagtail.blocks import RichTextBlock
from wagtail.fields import StreamField
from wagtail.models import Page

from cms.blocks import AlertBlock
from cms.services.decorators import htmx_request_with_url_update
from cms.services.validators import validate_filters


class DashboardIndexPage(Page):
    """A page listing all dashboards.

    This page is the parent of all DashboardPage instances. Only one instance
    can exist. Child dashboard pages are listed as cards grouped by data_status.

    Attributes:
        content: Optional introductory content above the dashboard listing.
    """

    max_count = 1
    template = "cms/pages/dashboard_index.html"
    htmx_template = "cms/pages/dashboard_index.html#dashboards_grid"
    parent_page_types = ["cms.HomePage"]
    subpage_types = ["cms.DashboardPage", "cms.DrrDatasetPage"]

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
        """Add child dashboards grouped by data_status to the context."""

        # Importing here to avoid circular imports
        from cms.pages.dashboard import DATA_STATUS_CHOICES, DashboardPage, DashboardTopic

        context = super().get_context(request)

        # Collect all unique topics from the child dashboards for filtering options
        context["all_topics"] = sorted(
            DashboardTopic.objects.filter(page__live=True)
            .values_list("topic__title", flat=True)
            .distinct()
        )

        context["all_status_types"] = sorted([label for _, label in DATA_STATUS_CHOICES])

        # Validate and clean the query parameters for filtering
        validated_filters = validate_filters(
            request.GET,
            valid_types=context["all_status_types"],
            valid_topics=context["all_topics"],
        )

        filters = models.Q()

        # If a search query is passed as a query parameter,
        # filter the dashboards based on that query
        search_filter = validated_filters.get("search")
        if search_filter:
            filters &= (
                models.Q(title__icontains=search_filter)
                | models.Q(description__icontains=search_filter)
                | models.Q(keywords__icontains=search_filter)
            )

        # If a status type is passed as a query parameter,
        # filter the dashboards based on that type
        type_filter = validated_filters.get("type")
        if type_filter:
            filters &= models.Q(data_status__in=type_filter)
            context["type_filter"] = type_filter

        # If a topic is passed as a query parameter,
        # filter the dashboards based on that topic
        topics_filter = validated_filters.get("topic")
        if topics_filter:
            filters &= models.Q(dashboard_topics__topic__slug__in=topics_filter)
            context["topics_filter"] = topics_filter

        dashboards = (
            DashboardPage.objects.child_of(self)
            .live()
            .public()
            .prefetch_related("dashboard_topics__topic")
            .distinct()
            .filter(filters)
        )

        # Sort dashboards by date_updated (newest first) and then title (A-Z)
        dashboards = sorted(
            dashboards,
            key=lambda d: (
                -(d.dashboard_data_updated_at or date.min).toordinal(),
                d.title.lower(),
            ),
        )

        context["dashboards_list"] = dashboards

        return context

    @htmx_request_with_url_update()
    def serve(self, request: HttpRequest) -> HttpResponse:
        """Override serve method to handle HTMX requests for filtering."""
        return super().serve(request)
