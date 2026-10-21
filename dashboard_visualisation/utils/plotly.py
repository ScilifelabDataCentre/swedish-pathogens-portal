"""Plotly figure conversion, HTML rendering, and CDN helpers."""

import json
import logging
import math
import re
from functools import lru_cache
from typing import Any

import plotly.graph_objects as go
import plotly.io as pio
import structlog

LOGGER = structlog.get_logger(__name__)
_HTML_LOGGER = logging.getLogger(__name__)

_PLOTLYJS_SCRIPT_PATTERN = re.compile(
    r'<script.*?src="([^"]+plotly[^"]+\.js)".*?integrity="(.*?)".*?</script>',
)


def figure_to_json(fig: go.Figure) -> dict[str, Any]:
    """Convert a Plotly figure to a PostgreSQL-safe JSON dict.

    Replaces NaN/Infinity floats with None since JSONB rejects them.
    Leaves bdata arrays as-is (Plotly.js renders them natively).
    """

    def _sanitize(obj: object) -> object:
        if isinstance(obj, dict):
            return {k: _sanitize(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_sanitize(item) for item in obj]
        if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
            return None
        return obj

    raw = json.loads(pio.to_json(fig))
    return _sanitize(raw)


def plot_html_from_json(
    data: dict[str, Any] | str | None,
    *,
    height: str | int = "100%",
    skip_invalid: bool = False,
    include_plotlyjs: str | bool = False,
    display_modebar: bool = True,
) -> str | None:
    """Build a Plotly HTML fragment from pre-computed figure JSON.

    Args:
        data: Plotly figure dict or JSON string with ``data`` and ``layout`` keys.
        height: Passed to Plotly's ``to_html`` as ``default_height``.
        skip_invalid: When True, invalid JSON properties are ignored.
        include_plotlyjs: Passed to Plotly's ``to_html`` (False when JS is loaded once).
        display_modebar: Passed to Plotly's ``to_html`` as ``config.displayModeBar``.

    Returns:
        HTML fragment for template embedding, or None if conversion fails.
    """
    if data is None:
        _HTML_LOGGER.warning("plot_html_from_json called with None data")
        return None

    html_settings = {
        "full_html": False,
        "default_height": height,
        "include_plotlyjs": include_plotlyjs,
    }

    if not display_modebar:
        html_settings["config"] = {"displayModeBar": False}

    try:
        jstring = data if isinstance(data, str) else json.dumps(data)
        fig = pio.from_json(jstring, skip_invalid=skip_invalid)
        return fig.to_html(**html_settings)
    except ValueError:
        _HTML_LOGGER.warning("Invalid Plotly JSON for plot HTML conversion", exc_info=True)
    except Exception:
        _HTML_LOGGER.warning("Failed to build plot HTML from JSON", exc_info=True)
    return None


@lru_cache
def get_plotlyjs_cdn_param(param: str) -> str | None:
    """Return the Plotly.js CDN URL or SRI hash for the installed Plotly version.

    Args:
        param: ``"url"`` for the script URL, or ``"hash"`` for the integrity value.

    Returns:
        The requested CDN parameter, or ``None`` if extraction fails.
    """
    if param not in ("url", "hash"):
        LOGGER.warning("plotly_cdn.invalid_param", param=param)
        return None

    html_string = pio.to_html({}, full_html=False, include_plotlyjs="cdn")
    match = _PLOTLYJS_SCRIPT_PATTERN.search(html_string)
    if not match:
        LOGGER.warning("plotly_cdn.script_tag_not_found")
        return None

    index = 0 if param == "url" else 1
    return match.group(index + 1)
