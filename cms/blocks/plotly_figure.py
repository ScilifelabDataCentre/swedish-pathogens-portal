"""Plotly figure block for rendering pre-computed charts."""

from typing import Any

from django.core.cache import cache
from wagtail.blocks import BooleanBlock, CharBlock, IntegerBlock, StructBlock, URLBlock

from dashboard_visualisation.utils import plot_html_from_json


class PlotlyFigureBlock(StructBlock):
    """Renders a pre-computed Plotly chart from DashboardData.

    The figure_id field maps to a key in the DashboardData.data JSONField.
    Plot HTML is generated on the server and cached per page slug and figure_id.

    Attributes:
        figure_id: Key matching a figure in the DashboardData JSON dict.
        alt_text: Accessibility description of the chart.
        height: Chart height in pixels.
        caption: Optional text displayed below the chart.
        script_github_url: Link to the viz script in this repo on GitHub.
        show_data_download: Whether to show a data download link below the chart.
    """

    figure_id = CharBlock(
        required=True,
        help_text="Key matching a figure in the DashboardData JSON.",
    )
    alt_text = CharBlock(
        required=True,
        help_text="Accessibility description (aria-label) for the chart.",
    )
    height = IntegerBlock(
        required=True,
        default=500,
        help_text="Chart height in pixels.",
    )
    caption = CharBlock(
        required=False,
        help_text="Optional visible caption below the chart (separate from alt text).",
    )
    script_github_url = URLBlock(
        required=False,
        help_text="Link to the viz script in this repo on GitHub.",
    )
    show_data_download = BooleanBlock(
        required=False,
        default=False,
        help_text="Show a link to download the underlying data file.",
    )

    CACHE_TIMEOUT_SECONDS = 60 * 60 * 24

    def get_context(
        self,
        value: dict[str, Any],
        parent_context: dict | None = None,
    ) -> dict[str, Any]:
        """Add cached server-rendered Plotly HTML for this figure."""
        context = super().get_context(value, parent_context)
        parent_context = parent_context or {}

        figure_id = value["figure_id"]
        figures = parent_context.get("figures", {})
        figure_json = figures.get(figure_id)

        plot_html = None
        if figure_json is not None:
            page = parent_context.get("page")
            slug = getattr(page, "slug", "unknown")
            file_hash = parent_context.get("source_file_hash") or ""
            height_px = int(value.get("height") or 500)
            # Height must be part of the key: Plotly bakes default_height into the
            # generated HTML, so a height-only StreamField change must miss the cache.
            cache_key = f"dashboard_plot_html:{slug}:{figure_id}:{file_hash}:{height_px}"
            plot_html = cache.get(cache_key)
            if plot_html is None:
                plot_html = plot_html_from_json(
                    figure_json,
                    height=f"{height_px}px",
                    include_plotlyjs=False,
                )
                if plot_html is not None:
                    cache.set(cache_key, plot_html, self.CACHE_TIMEOUT_SECONDS)

        context["plot_html"] = plot_html
        return context

    class Meta:
        """Block metadata."""

        template = "cms/blocks/plotly_figure.html"
        icon = "doc-full"
        label = "Plotly Figure"
