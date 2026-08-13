"""Check if the data is valid for the dashboard visualisation."""

from .constants import expected_columns


def validate_source_columns(columns: list[str]) -> str | None:
    """Validate that the uploaded file has the expected columns for this dashboard."""
    missing_columns = set(expected_columns) - set(columns)
    if missing_columns:
        return f"Missing columns: {', '.join(missing_columns)}"
    return None
