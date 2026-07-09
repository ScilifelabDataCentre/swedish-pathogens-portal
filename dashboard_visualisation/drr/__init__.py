"""Drug Repurposing Resource (DRR) precompute logic.

This subpackage turns the Spjuth team's Cell Painting feature table plus its
CBCS compound metadata into the derived artefacts a ``DrrDatasetPage`` serves:
a compound index, summary statistics, and server-side Plotly figures. It is
driven offline by the ``drr_precompute`` management command (FREYA-2556), never
at request time, and mirrors the ``liver_resource`` viz-subpackage layout.
"""

from .compounds import build_compound_index
from .figures import build_all_figures
from .loader import FeatureTable, load_feature_table, load_metadata
from .summary import build_summary

__all__ = [
    "FeatureTable",
    "build_all_figures",
    "build_compound_index",
    "build_summary",
    "load_feature_table",
    "load_metadata",
]
