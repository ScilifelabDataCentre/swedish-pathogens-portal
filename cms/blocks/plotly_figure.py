"""Plotly figure block for rendering pre-computed charts."""

from typing import Any

from django.core.cache import cache
from wagtail.blocks import BooleanBlock, CharBlock, IntegerBlock, StructBlock, URLBlock

from dashboard_visualisation.utils import plot_html_from_json

CACHE_TIMEOUT_SECONDS = 60 * 60 * 24


def figure_caveat(figure_json: dict[str, Any] | None) -> str:
    """Return a qualification the figure's payload carries about itself, if any.

    Read from ``layout.meta.caveat``, so whatever computed the figure states
    the caveat once, beside the values it applies to, and every surface that
    renders the figure renders it too. It is page text rather than a Plotly
    annotation because annotation text does not wrap and is clipped at the
    plot's edge on a narrow viewport.

    Args:
        figure_json: The precomputed Plotly JSON, or ``None``.

    Returns:
        The caveat, or an empty string when the figure declares none.
    """
    if not figure_json:
        return ""
    meta = figure_json.get("layout", {}).get("meta") or {}
    return str(meta.get("caveat", "")) if isinstance(meta, dict) else ""


def cached_plot_html(
    figure_json: dict[str, Any] | None,
    *,
    slug: str,
    figure_id: str,
    file_hash: str,
    height_px: int,
    variant: str = "",
) -> str | None:
    """Render one figure's Plotly HTML server-side, caching it per figure.

    The one place this cache is keyed, so a route that swaps a figure body into
    a rendered page shares the block's scheme instead of adding a second one.

    Args:
        figure_json: The precomputed Plotly JSON, or ``None`` when the figure is
            not available.
        slug: The page slug the figure belongs to.
        figure_id: The figure's key within the page's data.
        file_hash: The data row's ``source_file_hash``, which changes whenever
            anything a figure depends on changes.
        height_px: Chart height. Plotly bakes it into the generated HTML, so a
            height-only change must miss the cache.
        variant: Distinguishes two renders of the same ``figure_id`` — the
            per-compound radars, whose ``cbkid`` would otherwise let one
            compound serve another's figure (spec section 8.3).

    Returns:
        The rendered HTML, or ``None`` when there is no figure to render.
    """
    if figure_json is None:
        return None

    cache_key = f"dashboard_plot_html:{slug}:{figure_id}:{variant}:{file_hash}:{int(height_px)}"
    plot_html = cache.get(cache_key)
    if plot_html is None:
        plot_html = plot_html_from_json(
            figure_json,
            height=f"{int(height_px)}px",
            include_plotlyjs=False,
        )
        if plot_html is not None:
            cache.set(cache_key, plot_html, CACHE_TIMEOUT_SECONDS)
    return plot_html


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

    def get_context(
        self,
        value: dict[str, Any],
        parent_context: dict | None = None,
    ) -> dict[str, Any]:
        """Add cached server-rendered Plotly HTML for this figure."""
        context = super().get_context(value, parent_context)
        parent_context = parent_context or {}

        figure_id = value["figure_id"]
        page = parent_context.get("page")
        figure_json = parent_context.get("figures", {}).get(figure_id)

        context["plot_html"] = cached_plot_html(
            figure_json,
            slug=getattr(page, "slug", "unknown"),
            figure_id=figure_id,
            file_hash=parent_context.get("source_file_hash") or "",
            height_px=int(value.get("height") or 500),
        )
        context["figure_caveat"] = figure_caveat(figure_json)
        return context

    class Meta:
        """Block metadata."""

        template = "cms/blocks/plotly_figure.html"
        icon = "doc-full"
        label = "Plotly Figure"
