"""Dashboard visualisation package for SLU wastewater."""

from .plot_generator import generate_figures
from .validators import validate_source_columns

__all__ = [
    "validate_source_columns",
    "generate_figures",
]
