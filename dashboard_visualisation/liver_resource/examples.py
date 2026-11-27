"""Sidebar example DE dataset for the liver dashboard.

The example DE file is the Wagtail ``DashboardData.source_file`` for slug
``hepagenie-tln`` (same pattern as the card image / Documents workbook).
No go-live example file is bundled in the repo.
"""

from __future__ import annotations

import re
from pathlib import Path

EXAMPLE_SLUG = "obese-control"
EXAMPLE_LABEL = "Obese vs control (GSE126848)"

# Django FileSystemStorage may append ``_<7 alphanum>`` before the extension.
_STORAGE_SUFFIX_RE = re.compile(r"_([A-Za-z0-9]{7})(\.[^.]+)$")


def list_example_slugs() -> list[str]:
    """Return example slugs shown in the sidebar."""
    return [EXAMPLE_SLUG]


def storage_display_filename(filename: str) -> str:
    """Return a human-facing filename, stripping Django storage collision suffixes."""
    name = Path(filename).name
    return _STORAGE_SUFFIX_RE.sub(r"\2", name)


def example_label_from_filename(filename: str) -> str:
    """Build a readable sidebar label from an uploaded DE filename."""
    stem = Path(storage_display_filename(filename)).stem
    stem = stem.replace("_", " ").replace("-", " ")
    return stem or "Example dataset"


def _is_obese_example_filename(filename: str) -> bool:
    """Return True when ``filename`` is the GSE126848 obese example."""
    stem = Path(storage_display_filename(filename)).stem.lower().replace("_", "-")
    return stem in {"obese-control", "gse126848-obese-control", "gse126848 obese-control"}


def _dashboard_source_file(dashboard_data: object | None) -> object | None:
    """Return DashboardData.source_file when it has a stored name."""
    source_file = getattr(dashboard_data, "source_file", None)
    if source_file is not None and getattr(source_file, "name", ""):
        return source_file
    return None


def resolve_example_label(dashboard_data: object | None = None) -> str:
    """Return the sidebar example label from DashboardData (obese → canonical label)."""
    source_file = _dashboard_source_file(dashboard_data)
    if source_file is None:
        return EXAMPLE_LABEL
    if _is_obese_example_filename(source_file.name):
        return EXAMPLE_LABEL
    return example_label_from_filename(source_file.name)


def get_example_uploads(
    slug: str,
    dashboard_data: object | None = None,
) -> list[tuple[str, Path]] | None:
    """Return ``(filename, path)`` for the sidebar example from DashboardData.

    Uses the Wagtail-uploaded ``source_file``. Returns ``None`` when the slug is
    unknown or no DashboardData source file is configured.
    """
    if slug != EXAMPLE_SLUG:
        return None
    source_file = _dashboard_source_file(dashboard_data)
    if source_file is None:
        return None
    try:
        path = Path(source_file.path)
    except AttributeError, NotImplementedError, ValueError:
        return None
    if not path.is_file():
        return None
    return [(storage_display_filename(source_file.name), path)]


def list_examples(dashboard_data: object | None = None) -> list[dict[str, str]]:
    """Return metadata for the sidebar example button when DashboardData is set."""
    source_file = _dashboard_source_file(dashboard_data)
    if source_file is None:
        return []

    return [
        {
            "slug": EXAMPLE_SLUG,
            "label": resolve_example_label(dashboard_data),
            "kind": "single",
            "filename": storage_display_filename(source_file.name),
        }
    ]
