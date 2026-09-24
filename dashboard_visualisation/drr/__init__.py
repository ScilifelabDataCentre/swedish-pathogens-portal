"""Drug Repurposing Resource (DRR) precompute logic.

This subpackage turns the Spjuth team's Cell Painting feature table plus its
CBCS compound metadata into the derived artefacts a ``DrrDatasetPage`` serves:
a compound index, summary statistics, and server-side Plotly figures. It is
driven offline by the ``drr_precompute`` management command (FREYA-2556), never
at request time, and mirrors the ``liver_resource`` viz-subpackage layout.
"""

from .artefacts import artefact_dir
from .channels import Channel, channel_map, figure_feature_columns, present_channels
from .compounds import (
    build_compound_index,
    build_name_lookup,
    compound_label,
    name_lookup_report,
    normalize_cbkid,
    reconciliation_report,
)
from .figures import (
    FIGURE_CLIP_BOUND,
    SNIPPET_FIGURE_BYTE_CEILING,
    FigureBundle,
    build_all_figures,
    build_figure_bundle,
    clip_figure_values,
    clip_report,
    figure_basis_token,
    oversized_figures,
)
from .loader import FeatureTable, load_compound_names, load_feature_table, load_metadata
from .radar import RadarAxis, artefact_key, build_ring, require_populations
from .summary import build_summary

__all__ = [
    "FIGURE_CLIP_BOUND",
    "SNIPPET_FIGURE_BYTE_CEILING",
    "Channel",
    "FeatureTable",
    "FigureBundle",
    "RadarAxis",
    "artefact_dir",
    "artefact_key",
    "build_all_figures",
    "build_compound_index",
    "build_figure_bundle",
    "build_name_lookup",
    "build_ring",
    "build_summary",
    "channel_map",
    "clip_figure_values",
    "clip_report",
    "compound_label",
    "figure_basis_token",
    "figure_feature_columns",
    "load_compound_names",
    "load_feature_table",
    "load_metadata",
    "name_lookup_report",
    "normalize_cbkid",
    "oversized_figures",
    "present_channels",
    "reconciliation_report",
    "require_populations",
]
