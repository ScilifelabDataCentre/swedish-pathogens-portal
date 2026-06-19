"""CMS page for the DINA Liver Resource interactive dashboard."""

from typing import Any

from django.http import HttpRequest

from cms.pages.dashboard import DashboardPage
from cms.services.liver_resource.computation import VALID_CUTOFFS
from cms.services.liver_resource.examples import list_example_slugs
from cms.services.liver_resource.plotly_tln import build_base_figure_json


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
        context["base_tln_figure_json"] = build_base_figure_json()
        context["cutoff_choices"] = VALID_CUTOFFS
        context["example_slugs"] = list_example_slugs()
        return context
