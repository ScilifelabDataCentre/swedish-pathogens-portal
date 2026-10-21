"""Template tags for loading Plotly.js from the CDN matching the Python package."""

from django import template
from django.template.loader import render_to_string

from dashboard_visualisation.utils.plotly import get_plotlyjs_cdn_param, plot_html_from_json

register = template.Library()

# Fallback if CDN metadata cannot be parsed (Plotly 3.4.0 / plotly 6.6.0 pairing).
_FALLBACK_URL = "https://cdn.plot.ly/plotly-3.4.0.min.js"
_FALLBACK_INTEGRITY = "sha256-KEmPoupLpFyGMyGAiOsiNDbKDKAvxXAn/W+oQa0ZAfk="


@register.simple_tag
def plotlyjs_url() -> str:
    """Return the Plotly.js CDN URL for the installed Plotly Python package."""
    return get_plotlyjs_cdn_param("url") or _FALLBACK_URL


@register.simple_tag
def plotlyjs_integrity() -> str:
    """Return the Plotly.js SRI integrity hash for the installed Plotly Python package."""
    return get_plotlyjs_cdn_param("hash") or _FALLBACK_INTEGRITY


@register.simple_tag(takes_context=True)
def plotlyjs_once(context: template.Context) -> str:
    """Include the Plotly.js CDN script at most once per page render."""
    if context.get("plotlyjs_loaded"):
        return ""
    context["plotlyjs_loaded"] = True
    return render_to_string("cms/components/plotly_js.html")


@register.simple_tag
def plotly_html_from_json(
    data: str, height: str | int = "100%", display_modebar: bool = True
) -> str:
    """Return a Plotly HTML div from a JSON string."""
    return plot_html_from_json(data, height=height, display_modebar=display_modebar) or ""
