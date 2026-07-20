"""CMS page for the DINA Liver Resource interactive dashboard."""

from typing import Any

from django.http import HttpRequest
from django.urls import reverse

from cms.pages.dashboard import DashboardPage
from dashboard_visualisation.liver_resource.analysis import LEAF_TRACE_INDEX
from dashboard_visualisation.liver_resource.computation import VALID_CUTOFFS
from dashboard_visualisation.liver_resource.dashboard_figures import (
    get_figure_data,
    resolve_base_tln_figure,
)
from dashboard_visualisation.liver_resource.examples import list_examples
from dashboard_visualisation.liver_resource.plotly_tln import DEFAULT_PLOT_HEIGHT_PX
from dashboard_visualisation.liver_resource.session import (
    DEFAULT_CUTOFF,
    get_de_session,
    get_session_cutoff,
)
from dashboard_visualisation.utils.plotly import plot_html_from_json


class LiverResourceDashboardPage(DashboardPage):
    """Visitor-driven liver TLN dashboard with session-scoped DE uploads.

    Shares card fields with :class:`DashboardPage` for the index listing.
    The page body is rendered from a custom template with upload controls,
    Plotly TLN, and htmx partial updates rather than StreamField figures.
    """

    template = "cms/pages/liver_resource.html"

    class Meta:
        """Meta options for the LiverResourceDashboardPage model."""

        verbose_name = "Liver Resource Dashboard"

    def get_context(self, request: HttpRequest) -> dict[str, Any]:
        """Add liver-specific TLN and control metadata to template context."""
        context = super().get_context(request)
        figure_data = get_figure_data(self.dashboard_data)
        base_figure_json = resolve_base_tln_figure(figure_data)
        session = get_de_session(request)

        context["base_tln_figure_json"] = base_figure_json
        context["base_plot_html"] = plot_html_from_json(
            base_figure_json,
            height=f"{DEFAULT_PLOT_HEIGHT_PX}px",
            include_plotlyjs=False,
        )
        context["plot_height"] = DEFAULT_PLOT_HEIGHT_PX
        context["leaf_trace_index"] = LEAF_TRACE_INDEX
        context["cutoff_choices"] = VALID_CUTOFFS
        context["default_cutoff"] = DEFAULT_CUTOFF
        context["current_cutoff"] = get_session_cutoff(request) if session else DEFAULT_CUTOFF
        context["has_session"] = session is not None
        context["examples"] = list_examples(self.dashboard_data)
        context["liver_upload_url"] = reverse("cms:liver_upload")
        context["liver_recompute_url"] = reverse("cms:liver_recompute")
        return context
