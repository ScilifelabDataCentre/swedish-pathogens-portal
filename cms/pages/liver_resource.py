"""CMS page for the HepaGeNIE interactive dashboard."""

from typing import Any

from django.http import HttpRequest, HttpResponse
from wagtail.admin.panels import FieldPanel, MultiFieldPanel
from wagtail.blocks import RichTextBlock, StreamValue
from wagtail.contrib.routable_page.models import RoutablePageMixin, path
from wagtail.fields import StreamField
from wagtail.search import index

from cms.blocks import (
    AlertBlock,
    CollapsibleBlock,
    DataTableBlock,
    HepageniePanelBlock,
    LastUpdatedBlock,
    PlotlyFigureBlock,
    StaticFigureBlock,
)
from cms.pages.dashboard import DashboardPage
from cms.views import liver_resource as liver_views
from dashboard_visualisation.liver_resource.analysis import LEAF_TRACE_INDEX
from dashboard_visualisation.liver_resource.dashboard_figures import (
    get_figure_data,
    resolve_base_tln_figure,
)
from dashboard_visualisation.liver_resource.examples import list_examples
from dashboard_visualisation.liver_resource.plotly_tln import DEFAULT_PLOT_HEIGHT_PX
from dashboard_visualisation.liver_resource.plot_metric import (
    DEFAULT_PLOT_METRIC,
    PLOT_METRIC_CHOICES,
    PLOT_METRIC_LABELS,
)
from dashboard_visualisation.liver_resource.session import (
    get_de_session,
    get_session_plot_metric,
    get_session_thresholds,
)
from dashboard_visualisation.liver_resource.thresholds import (
    ADJ_P_CHOICES,
    DEFAULT_ADJ_P,
    DEFAULT_LOGFC_FOLD,
    DEFAULT_THRESHOLD_KEY,
    LOGFC_FOLD_CHOICES,
)
from dashboard_visualisation.utils.plotly import plot_html_from_json

# Text blocks with these markers render below the plot (order preserved).
_CITATION_MARKER = "How to cite"
_SUPPLEMENTARY_MARKER = "supplementary workbook"
_REFERENCE_TLN_MARKER = "reference tln map"


def _is_below_plot_text(block: Any) -> bool:
    """Return True for footer text: citation, workbook, or reference TLN link."""
    if block.block_type != "text":
        return False
    html = str(block.value)
    folded = html.casefold()
    return (
        _CITATION_MARKER in html
        or _SUPPLEMENTARY_MARKER in folded
        or _REFERENCE_TLN_MARKER in folded
    )


def split_liver_content_for_plot(
    content: StreamValue,
) -> tuple[list[Any], list[Any]]:
    """Split StreamField blocks into intro (above plot) and footer (below).

    Footer text blocks are those whose HTML contains ``How to cite`` (APA
    citation), ``supplementary workbook``, or ``reference TLN map`` (Wagtail
    Document links). Keep StreamField order so editors can place the reference
    map and workbook links immediately before the citation.
    """
    above: list[Any] = []
    below: list[Any] = []
    for block in content:
        if _is_below_plot_text(block):
            below.append(block)
        else:
            above.append(block)
    return above, below


class LiverResourceDashboardPage(RoutablePageMixin, DashboardPage):
    """Visitor-driven HepaGeNIE TLN dashboard with session-scoped DE uploads.

    Reuses :class:`DashboardPage` card fields. Uses a liver-only
    ``liver_content`` StreamField (same idea as SLU ``slu_content``) so
    ``hepagene_panel`` is not added to other dashboards. Django MTI forbids
    redefining the inherited ``content`` field on this subclass.

    Until the panel cut-over, the body still uses a custom template with a
    hardcoded sidebar+TLN and phrase markers
    (``reference TLN map`` / ``supplementary workbook`` / ``How to cite``) to
    split intro vs footer. ``image`` is the index thumbnail only. The sidebar
    example DE file is ``DashboardData.source_file`` for this slug.
    """

    template = "cms/pages/liver_resource.html"
    max_count = 1

    # Liver-only StreamField: shared dashboard blocks + HepaGeNIE panel.
    # Parent DashboardPage.content is unused in the editor (see content_panels).
    liver_content = StreamField(
        [
            ("text", RichTextBlock()),
            ("alert", AlertBlock()),
            ("collapsible", CollapsibleBlock()),
            ("data_table", DataTableBlock()),
            ("last_updated", LastUpdatedBlock()),
            ("plotly_figure", PlotlyFigureBlock()),
            ("static_figure", StaticFigureBlock()),
            ("hepagene_panel", HepageniePanelBlock()),
        ],
        blank=False,
        default=list,
    )

    search_fields = DashboardPage.search_fields + [
        index.SearchField("liver_content"),
        index.AutocompleteField("liver_content"),
    ]

    # Drop parent ``content`` panel; show ``liver_content`` instead (SLU pattern).
    content_panels = [
        *DashboardPage.content_panels[:1],
        MultiFieldPanel(
            [
                FieldPanel(
                    "description",
                    help_text="Brief text displayed on the dashboard index card.",
                ),
                FieldPanel(
                    "image",
                    help_text=(
                        "Thumbnail on the dashboard index card only. Link the "
                        "reference TLN map JPG from page text as a Document "
                        "(same pattern as the supplementary workbook)."
                    ),
                ),
            ],
            heading="Card details",
        ),
        *DashboardPage.content_panels[2:-1],
        FieldPanel(
            "liver_content",
            help_text=(
                "Main HepaGeNIE content. Includes the HepaGeNIE interactive panel "
                "block (liver-only; not available on other dashboards)."
            ),
        ),
    ]

    class Meta:
        """Meta options for the LiverResourceDashboardPage model."""

        verbose_name = "HepaGeNIE Dashboard"

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
        if session is not None:
            current_adj_p, current_logfc_fold = get_session_thresholds(request)
            current_plot_metric = get_session_plot_metric(request)
        else:
            current_adj_p, current_logfc_fold = DEFAULT_ADJ_P, DEFAULT_LOGFC_FOLD
            current_plot_metric = DEFAULT_PLOT_METRIC
        context["adj_p_choices"] = ADJ_P_CHOICES
        context["logfc_fold_choices"] = LOGFC_FOLD_CHOICES
        context["plot_metric_choices"] = [
            {"value": value, "label": PLOT_METRIC_LABELS[value]} for value in PLOT_METRIC_CHOICES
        ]
        context["current_adj_p"] = current_adj_p
        context["current_logfc_fold"] = current_logfc_fold
        context["current_plot_metric"] = current_plot_metric
        context["default_adj_p"] = DEFAULT_ADJ_P
        context["default_logfc_fold"] = DEFAULT_LOGFC_FOLD
        context["default_plot_metric"] = DEFAULT_PLOT_METRIC
        context["default_threshold_key"] = DEFAULT_THRESHOLD_KEY
        context["has_session"] = session is not None
        context["examples"] = list_examples(self.dashboard_data)
        content_above, content_below = split_liver_content_for_plot(self.liver_content)
        context["liver_content_above"] = content_above
        context["liver_content_below"] = content_below
        return context

    # ------------------------------------------------------------------ #
    # Routes                                                             #
    # ------------------------------------------------------------------ #

    @path("upload/")
    def upload_de(self, request: HttpRequest) -> HttpResponse:
        """HTMX/JSON: validate upload, store session, return coloured figure."""
        return liver_views.upload_de(request)

    @path("example/<slug:example_slug>/")
    def load_example(self, request: HttpRequest, example_slug: str) -> HttpResponse:
        """HTMX/JSON: load a curated example DE file into the session."""
        return liver_views.load_example(request, example_slug)

    @path("recompute/")
    def recompute(self, request: HttpRequest) -> HttpResponse:
        """HTMX/JSON: recolour the TLN from the current session thresholds."""
        return liver_views.recompute(request)

    @path("download-template/")
    def download_template(self, request: HttpRequest) -> HttpResponse:
        """Download the empty DE upload template."""
        return liver_views.download_template(request)

    @path("export/modules/")
    def export_module_scores(self, request: HttpRequest) -> HttpResponse:
        """Download module scores CSV for the current session."""
        return liver_views.export_module_scores(request)

    @path("export/genes/")
    def export_genes(self, request: HttpRequest) -> HttpResponse:
        """Download gene classification CSV for the current session."""
        return liver_views.export_genes(request)
