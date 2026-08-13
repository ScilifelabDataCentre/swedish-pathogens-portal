"""Dashboard visualisation package for SLU wastewater."""

from .data_validator import validate_source_columns
from .plot_generator import generate_figures

__all__ = [
    "validate_source_columns",
    "generate_figures",
]
