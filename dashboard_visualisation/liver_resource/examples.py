"""Bundled example DE dataset for the liver dashboard sidebar."""

from __future__ import annotations

from pathlib import Path

from dashboard_visualisation.liver_resource.reference_data import get_data_root

EXAMPLE_SLUG = "hcc-control"
EXAMPLE_FILENAME = "HCC-Control.txt"
EXAMPLE_LABEL = "HCC vs control"


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


def list_examples() -> list[dict[str, str]]:
    """Return metadata for the sidebar example button."""
    return [
        {
            "slug": EXAMPLE_SLUG,
            "label": EXAMPLE_LABEL,
            "kind": "single",
            "filename": EXAMPLE_FILENAME,
        }
    ]
