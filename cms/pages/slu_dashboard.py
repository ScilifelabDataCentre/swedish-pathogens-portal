"""Wagtail page for the SLU wastewater dashboard."""

from django.db import models
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils.functional import cached_property
from wagtail.admin.panels import FieldPanel, MultiFieldPanel
from wagtail.blocks import RichTextBlock, StaticBlock
from wagtail.fields import RichTextField, StreamField

from cms.blocks import AlertBlock, CollapsibleBlock, LastUpdatedBlock, PlotlyFigureBlock
from cms.pages.dashboard import DashboardPage
from dashboard_visualisation.slu_wastewater.quantitative_plot import get_quant_overview_plot

NOTICE_TYPE_CHOICES = [
    ("info", "Info"),
    ("warning", "Warning"),
    ("success", "Success"),
    ("error", "Error"),
]


class SLUDashboardPage(DashboardPage):
    """Wagtail page for the SLU wastewater "Overview".

    This page is the top-level page for the SLU wastewater dashboard, and it is
    sub-classed from the DashboardPage model to inherit card fields, keywords,
    related topics, fetching related dashboard data. But it has its own 'slu_content'
    i.e. StreamField for the main content, which includes general blocks and SLU
    wastewater-specific blocks. The 'content' field from the parent class is not used.

    Attributes:
        notice (RichTextField): Optional notice to display at the top of the page.
            If set, this notice will be inherited by subpages.
        notice_type (CharField): Optional notice type that sets the style of the
            notice text. If set, this notice type will be inherited by subpages.
        slu_content (StreamField): Main content of the page, which can include text,
            figures, alerts, and other static blocks.
    """

    template = "cms/pages/slu_wastewater/slu_dashboard.html"
    parent_page_types = ["cms.DashboardIndexPage"]
    subpage_types = ["cms.SLUDashboardSubPage"]
    max_count = 1

    notice = RichTextField(features=["h4", "h5", "bold", "italic", "link"], blank=True)
    notice_type = models.CharField(
        max_length=20, choices=NOTICE_TYPE_CHOICES, default="info", blank=True
    )

    slu_content = StreamField(
        [
            ("text", RichTextBlock()),
            ("alert", AlertBlock()),
            ("collapsible", CollapsibleBlock()),
            ("last_updated", LastUpdatedBlock()),
            ("plotly_figure", PlotlyFigureBlock()),
            (
                "recent_data_info",
                StaticBlock(
                    admin_text=(
                        "A static block that displays a summary of the most recent data in the "
                        "dataset as a collapsible section."
                    ),
                    template="cms/pages/slu_wastewater/partials/recent_data_info.html",
                ),
            ),
            (
                "overview_quantitative_plot",
                StaticBlock(
                    admin_text=(
                        "A static block that displays the quantitative overview plot and the plot "
                        "filter options in a collapsible section."
                    ),
                    template="cms/pages/slu_wastewater/partials/overview_quant_plot.html",
                ),
            ),
        ],
        blank=False,
        block_counts={
            "recent_data_info": {"max_num": 1},
            "overview_quantitative_plot": {"max_num": 1},
        },
        collapsed=True,
    )

    # No need to include the last panel from the parent class, which is the "content" field,
    # since we are using a new StreamField with additional blocks instead.
    content_panels = DashboardPage.content_panels[:-1] + [
        MultiFieldPanel(
            [
                FieldPanel(
                    "notice_type",
                    help_text=(
                        "Optional notice type that sets the style of the notice text. "
                        "Inherited by subpages."
                    ),
                ),
                FieldPanel(
                    "notice",
                    help_text=(
                        "Optional notice to display at the top of the page. Inherited by subpages."
                    ),
                ),
            ],
            heading="Top level notice",
            classname="collapsed",
        ),
        FieldPanel(
            "slu_content",
            help_text="Main content: text, figures, and alerts.",
        ),
    ]

    class Meta:
        """Meta options for the SLUDashboardPage model."""

        verbose_name = "SLU Wastewater Dashboard"

    @cached_property
    def navigation_tabs(self) -> list[dict[str, str]]:
        """Return a list of navigation links for the dashboard and its subpages."""
        links = [{"title": "Overview", "url": self.url}]
        child_pages = self.get_children().live().specific()
        for child in sorted(child_pages, key=lambda p: (p.navigation_order, p.title)):
            if getattr(child, "include_in_navigation", True):
                links.append({"title": child.title, "url": child.url})
        return links

    def serve(self, request: HttpRequest) -> HttpResponse:
        """Override serve method to handle HTMX requests for plot generation."""

        # Handle HTMX requests for plot generation, currently only the quantitative
        # overview plot is expected to be requested via HTMX. If this changes in the
        # future, additional logic may be needed to determine which plot to generate.
        if request.htmx:
            request_params = dict(request.GET)
            raw_data = getattr(self.dashboard_data, "data", {}).get("raw_data", None)
            if raw_data is None:
                # This should never happen, but if it does, return
                # an error message instead of crashing the page.
                return render(
                    request,
                    "cms/pages/slu_wastewater/partials/load_message.html",
                    {"missing_data": "Raw data", "message_type": "error"},
                )
            plot_html = get_quant_overview_plot(data=raw_data, as_html=True, **request_params)
            return HttpResponse(plot_html)

        # If not an HTMX request, proceed with the default serve method
        return super().serve(request)
