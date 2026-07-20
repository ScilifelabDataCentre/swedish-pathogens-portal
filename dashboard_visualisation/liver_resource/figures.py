"""Viz registry entry for liver ``DashboardData`` uploads (serology-style flow)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dashboard_visualisation.liver_resource.analysis import analyse_de_uploads
from dashboard_visualisation.liver_resource.computation import parse_de_file
from dashboard_visualisation.liver_resource.dashboard_figures import (
    stored_example_entry_from_analysis,
)
from dashboard_visualisation.liver_resource.examples import (
    EXAMPLE_SLUG,
    storage_display_filename,
)
from dashboard_visualisation.liver_resource.plotly_tln import build_base_figure_json
from dashboard_visualisation.liver_resource.session import DEFAULT_CUTOFF
from dashboard_visualisation.liver_resource.validators import REQUIRED_COLUMNS
from dashboard_visualisation.utils.uploads import SourceFile


def validate_source_columns(columns: list[str]) -> str | None:
    """Validate limma-style DE columns for the uploaded example file."""
    missing = [column for column in REQUIRED_COLUMNS if column not in columns]
    if missing:
        return f"Missing required columns: {', '.join(missing)}"
    return None


def generate_figures(source_file: SourceFile) -> dict[str, Any]:
    """Build neutral base TLN and one sidebar example from the uploaded DE file."""
    filename = storage_display_filename(Path(source_file.name).name)
    de_data = parse_de_file(source_file)
    analysis = analyse_de_uploads([(filename, de_data)], cutoff=DEFAULT_CUTOFF)

    return {
        "base_tln": build_base_figure_json(),
        "examples": {
            EXAMPLE_SLUG: {
                DEFAULT_CUTOFF: stored_example_entry_from_analysis(analysis),
            },
        },
    }
