"""DE thresholds: Adj P.val × LogFC fold.

Default pair is ``0.05`` / ``1.5`` (DashboardData key ``0.05_1.5``).
"""

from __future__ import annotations

import math
from typing import Any

ADJ_P_CHOICES: tuple[float, ...] = (0.05, 0.01, 0.005, 0.001, 0.0005, 0.0001)
LOGFC_FOLD_CHOICES: tuple[float, ...] = (1.5, 2.0, 5.0, 10.0, 20.0)

DEFAULT_ADJ_P: float = 0.05
DEFAULT_LOGFC_FOLD: float = 1.5


def format_number(value: float) -> str:
    """Format a threshold number without trailing zeros (0.05, 1.5, 10)."""
    return f"{value:g}"


def threshold_key(adj_p: float, logfc_fold: float) -> str:
    """Stable DashboardData / session key, e.g. ``0.05_1.5``."""
    return f"{format_number(adj_p)}_{format_number(logfc_fold)}"


DEFAULT_THRESHOLD_KEY = threshold_key(DEFAULT_ADJ_P, DEFAULT_LOGFC_FOLD)


def format_threshold_label(adj_p: float, logfc_fold: float) -> str:
    """Human-readable label for plot titles and stats."""
    return f"adj.P<{format_number(adj_p)}, fold {format_number(logfc_fold)}"


def parse_adj_p(value: Any, *, default: float = DEFAULT_ADJ_P) -> float:  # noqa: ANN401
    """Parse an Adj P.val choice; unknown values fall back to default."""
    try:
        parsed = float(value)
    except TypeError, ValueError:
        return default
    for choice in ADJ_P_CHOICES:
        if math.isclose(parsed, choice, rel_tol=0.0, abs_tol=1e-12):
            return choice
    return default


def parse_logfc_fold(value: Any, *, default: float = DEFAULT_LOGFC_FOLD) -> float:  # noqa: ANN401
    """Parse a LogFC fold choice; unknown values fall back to default."""
    try:
        parsed = float(value)
    except TypeError, ValueError:
        return default
    for choice in LOGFC_FOLD_CHOICES:
        if math.isclose(parsed, choice, rel_tol=0.0, abs_tol=1e-12):
            return choice
    return default


def logfc_threshold(logfc_fold: float) -> float:
    """Absolute log2 fold-change threshold for the given fold multiplier."""
    return math.log2(logfc_fold)
