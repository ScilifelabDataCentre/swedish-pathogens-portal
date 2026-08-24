"""Wagtail page for the SLU wastewater dashboard subpages."""

from typing import TYPE_CHECKING, Any

from django.db import models
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils.functional import cached_property
from wagtail.admin.panels import FieldPanel
from wagtail.blocks import RichTextBlock, StaticBlock
from wagtail.fields import StreamField
from wagtail.models import Page

from cms.blocks import AlertBlock, CollapsibleBlock, LastUpdatedBlock, PlotlyFigureBlock
from dashboard_visualisation.slu_wastewater.constants import VIRUSES_OF_INTEREST
from dashboard_visualisation.slu_wastewater.quantitative_plot import (
    get_all_sites_plot,
    get_single_site_plot,
)
from dashboard_visualisation.slu_wastewater.validators import validate_analysis_plot_request_params

if TYPE_CHECKING:
    from cms.pages.slu_dashboard import SLUDashboardPage


class SLUDashboardSubPage(Page):
    """Wagtail page for the SLU wastewater dashboard subpages.

    This page is a child of the SLUDashboardPage and is used to display quantitative
    and qualitative analysis of wastewater data for a specific virus of interest.
    Each subpage corresponds to information about a virus of interest. A "methodology"
    subpage is also created to provide information about the methods used to collect
    and analyze the wastewater data.

    Attributes:
        inherit_notice (bool): Whether to inherit the notice from the parent page.
        include_in_navigation (bool): Whether to include this page in the navigation menu.
        navigation_order (int): Order of this page in the navigation menu.
            Lower numbers appear first.
        slu_content (StreamField): Main content of the page, which can include text,
            figures, alerts, and other static blocks.
    """

    template = "cms/pages/slu_wastewater/slu_dashboard.html"
    parent_page_types = ["cms.SLUDashboardPage"]
    subpage_types = []

    inherit_notice = models.BooleanField(default=True, blank=True)
    include_in_navigation = models.BooleanField(default=True, blank=True)
    navigation_order = models.PositiveIntegerField(default=1, blank=True)
    show_toc = models.BooleanField(default=False, blank=True, verbose_name="Show TOC")

    slu_content = StreamField(
        [
            ("text", RichTextBlock()),
            ("alert", AlertBlock()),
            ("collapsible", CollapsibleBlock()),
            ("last_updated", LastUpdatedBlock()),
            ("plotly_figure", PlotlyFigureBlock()),
            (
                "site_info",
                StaticBlock(
                    admin_text="A static block that displays information about the sampling sites.",
                    template="cms/pages/slu_wastewater/partials/method_and_site_info.html",
                ),
            ),
            (
                "virus_quantitative_plot",
                StaticBlock(
                    admin_text=(
                        "A static block that displays the quantitative analysis plot and the plot "
                        "filter options in a collapsible section."
                    ),
                    template="cms/pages/slu_wastewater/partials/quantitative_analysis.html",
                ),
            ),
        ],
        blank=False,
        block_counts={
            "site_info": {"max_num": 1},
            "virus_quantitative_plot": {"max_num": 1},
        },
        collapsed=True,
    )

    content_panels = Page.content_panels + [
        FieldPanel(
            "inherit_notice",
            help_text="If checked, this page will inherit the notice from the parent page.",
        ),
        FieldPanel(
            "include_in_navigation",
            help_text="If checked, this page will be included in the navigation menu.",
        ),
        FieldPanel(
            "navigation_order",
            help_text="Order of this page in the navigation menu. Lower numbers appear first.",
        ),
        FieldPanel(
            "slu_content",
            help_text="Main content: text, figures, and alerts.",
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

    class Meta:
        """Meta options for the SLUDashboardSubPage model."""

        verbose_name = "SLU Wastewater Dashboard Subpage"

    @cached_property
    def parent(self) -> SLUDashboardPage:
        """Return the parent page of this subpage."""
        return self.get_parent().specific

    @property
    def notice_type(self) -> str:
        """Return the notice type from the parent page."""
        return self.parent.notice_type if self.parent else "info"

    @property
    def notice(self) -> str:
        """Return the notice from the parent page."""
        return self.parent.notice if self.parent and self.inherit_notice else ""

    @property
    def dashboard_data(self) -> dict | None:
        """Return the dashboard data from the parent page."""
        return self.parent.dashboard_data if self.parent else None

    @property
    def dashboard_data_updated_at(self) -> str | None:
        """Return the dashboard data updated_at from the parent page."""
        return self.parent.dashboard_data_updated_at if self.parent else None

    @property
    def get_data_status_display(self) -> str | None:
        """Return the dashboard data status display from the parent page."""
        return self.parent.get_data_status_display if self.parent else None

    @property
    def navigation_tabs(self) -> list[dict[str, str]] | None:
        """Return a list of navigation tabs for the dashboard and its subpages."""
        return self.parent.navigation_tabs if self.parent else None

    def get_context(self, request: HttpRequest) -> dict[str, Any]:
        """Add DashboardData figures, CSV URL, and parent heading to template context."""

        # Importing here to avoid chances of circular import issues
        from cms.pages.dashboard_index import DashboardIndexPage

        context = super().get_context(request)
        context["dashboard_data"] = self.dashboard_data
        context["figures"] = getattr(self.dashboard_data, "data", {})
        context["data_updated_at"] = self.dashboard_data_updated_at
        context["source_file_hash"] = getattr(self.dashboard_data, "source_file_hash", "")

        heading_parent = self.get_ancestors().type(DashboardIndexPage).first()
        context["page_heading"] = heading_parent.title if heading_parent else ""
        context["page_title"] = self.parent.title if self.parent else ""
        return context

    def serve(self, request: HttpRequest) -> HttpResponse:
        """Override serve method to handle HTMX requests for plot generation."""

        # Handle HTMX requests for plot generation, currently only the quantitative
        # analysis plot is expected to be requested via HTMX. If this changes in the
        # future, additional logic may be needed to determine which plot to generate.
        if request.htmx:
            if self.title not in VIRUSES_OF_INTEREST:
                # This should not happen, the title of the pages created should match
                # the viruses of interest, as it is used for filtering the data. So if
                # the title does not match, return an error message instead of crashing.
                return render(
                    request,
                    "cms/pages/slu_wastewater/partials/load_message.html",
                    {
                        "missing_data": self.title,
                        "message_type": "error",
                    },
                )
            raw_data = getattr(self.dashboard_data, "data", {}).get("raw_data", None)
            if raw_data is None:
                # This should never happen, but if it does, return
                # an error message instead of crashing the page.
                return render(
                    request,
                    "cms/pages/slu_wastewater/partials/load_message.html",
                    {"missing_data": "Raw data", "message_type": "error"},
                )
            request_params = validate_analysis_plot_request_params(request.GET, raw_data)
            # call appropriate function depending upon the plot type
            if request.GET.get("plot-toggle") == "all":
                quant_plot_html = get_all_sites_plot(
                    data=raw_data, virus=self.title, as_html=True, **request_params
                )
            else:
                quant_plot_html = get_single_site_plot(
                    data=raw_data, virus=self.title, as_html=True, **request_params
                )
            return HttpResponse(quant_plot_html)

        # If not an HTMX request, proceed with the default serve method
        return super().serve(request)
