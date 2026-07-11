"""CMS page for a single Drug Repurposing Resource (DRR) dataset."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.db import models
from django.http import HttpRequest
from django.utils.functional import cached_property
from wagtail.admin.panels import FieldPanel, MultiFieldPanel
from wagtail.contrib.routable_page.models import RoutablePageMixin

from cms.pages.dashboard import DashboardPage

if TYPE_CHECKING:
    from cms.snippets.drr_dataset_data import DrrDatasetData


class DrrDatasetPage(RoutablePageMixin, DashboardPage):
    """A Drug Repurposing Resource dataset page (dataset-as-page).

    Lives under the existing Dashboards index and subclasses
    :class:`~cms.pages.dashboard.DashboardPage` to reuse its card fields,
    related topics, keywords, table of contents, and the server-side Plotly
    render path, while sourcing figures and summary statistics from
    :class:`~cms.snippets.drr_dataset_data.DrrDatasetData` instead of
    ``DashboardData``. ``RoutablePageMixin`` is present for the per-dataset
    download and raw-image 302 link-out routes added in a later subtask
    (see mvp-spec.md section 8).

    Attributes:
        organism: Source organism label (defaults to SARS-CoV-2).
        cell_line: Cell line used in the screen (e.g. Vero E6).
        screen_type: Screen description (e.g. Primary Cell Painting).
        upstream_accession: Upstream repository accession (e.g. S-BIAD2580).
        upstream_bia_url: Upstream raw-image study URL; target of the 302 link-out.
    """

    template = "cms/pages/drr_dataset.html"
    parent_page_types = ["cms.DashboardIndexPage"]
    subpage_types: list[str] = []

    organism = models.CharField(max_length=255, default="SARS-CoV-2")
    cell_line = models.CharField(max_length=255, blank=True)
    screen_type = models.CharField(max_length=255, blank=True)
    upstream_accession = models.CharField(max_length=64, blank=True)
    upstream_bia_url = models.URLField(blank=True)

    content_panels = [
        *DashboardPage.content_panels[:-1],
        MultiFieldPanel(
            [
                FieldPanel("organism"),
                FieldPanel("cell_line"),
                FieldPanel("screen_type"),
                FieldPanel("upstream_accession"),
                FieldPanel(
                    "upstream_bia_url",
                    help_text="Upstream raw-image study; target of the raw-image 302 link-out.",
                ),
            ],
            heading="Dataset metadata",
        ),
        DashboardPage.content_panels[-1],
    ]

    class Meta:
        """Meta options for the DrrDatasetPage model."""

        verbose_name = "DRR Dataset Page"

    @cached_property
    def dashboard_data(self) -> DrrDatasetData | None:
        """Return the DRR precomputed data row keyed by this page's slug."""
        from cms.snippets.drr_dataset_data import DrrDatasetData

        return DrrDatasetData.get_data(self.slug)

    def get_context(self, request: HttpRequest) -> dict[str, Any]:
        """Add the DRR summary-statistics payload to the inherited context."""
        context = super().get_context(request)
        context["summary"] = getattr(self.dashboard_data, "summary", {})
        return context
