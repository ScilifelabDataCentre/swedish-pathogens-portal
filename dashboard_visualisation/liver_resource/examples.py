"""Bundled example DE dataset for the liver dashboard sidebar."""

from __future__ import annotations

from pathlib import Path

from dashboard_visualisation.liver_resource.reference_data import get_data_root

EXAMPLE_SLUG = "hcc-control"
EXAMPLE_FILENAME = "HCC-Control.txt"


def list_example_slugs() -> list[str]:
    """Return example slugs shown in the sidebar."""
    return [EXAMPLE_SLUG]


def get_example_path(slug: str) -> Path | None:
    """Return the bundled path for the sidebar example, or None when unknown."""
    if slug != EXAMPLE_SLUG:
        return None
    path = get_data_root() / "examples" / EXAMPLE_FILENAME
    return path if path.is_file() else None


def get_example_uploads(slug: str) -> list[tuple[str, Path]] | None:
    """Return ``(filename, path)`` pairs for the sidebar example slug."""
    path = get_example_path(slug)
    if path is None:
        return None
    return [(path.name, path)]


def example_label_from_filename(filename: str) -> str:
    """Build a readable sidebar label from an uploaded DE filename."""
    stem = Path(filename).stem.replace("_", " ").replace("-", " ")
    return stem or "Example dataset"


def resolve_example_label(dashboard_data: object | None = None) -> str:
    """Return the sidebar example label from DashboardData or the bundled filename."""
    source_file = getattr(dashboard_data, "source_file", None)
    if source_file is not None and getattr(source_file, "name", ""):
        return example_label_from_filename(source_file.name)
    return example_label_from_filename(EXAMPLE_FILENAME)


def list_examples(dashboard_data: object | None = None) -> list[dict[str, str]]:
    """Return metadata for the sidebar example button."""
    if get_example_path(EXAMPLE_SLUG) is None:
        return []

    label = resolve_example_label(dashboard_data)
    filename = EXAMPLE_FILENAME
    source_file = getattr(dashboard_data, "source_file", None)
    if source_file is not None and getattr(source_file, "name", ""):
        filename = Path(source_file.name).name

    return [
        {
            "slug": EXAMPLE_SLUG,
            "label": label,
            "kind": "single",
            "filename": filename,
        }
    ]
