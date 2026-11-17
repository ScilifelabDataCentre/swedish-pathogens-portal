"""Plot scoring modes: Difference vs Total DE genes per module.

Difference (default): (up − down) / overlap — signed, colour scale −1→+1.
Total: (up + down) / overlap — non-negative, colour scale 0→1.
"""

from __future__ import annotations

from typing import Any, Literal

PlotMetric = Literal["difference", "total"]

PLOT_METRIC_CHOICES: tuple[PlotMetric, ...] = ("difference", "total")
DEFAULT_PLOT_METRIC: PlotMetric = "difference"

PLOT_METRIC_LABELS: dict[PlotMetric, str] = {
    "difference": "Difference DE genes",
    "total": "Total DE genes",
}


def parse_plot_metric(value: Any, *, default: PlotMetric = DEFAULT_PLOT_METRIC) -> PlotMetric:
    """Parse a Plot dropdown value; unknown values fall back to default."""
    if isinstance(value, str):
        normalised = value.strip().lower()
        if normalised in PLOT_METRIC_CHOICES:
            return normalised  # type: ignore[return-value]
    return default


def plot_metric_label(metric: PlotMetric) -> str:
    """Human-readable Plot option label for stats chrome."""
    return PLOT_METRIC_LABELS[metric]
