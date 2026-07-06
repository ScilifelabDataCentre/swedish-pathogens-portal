"""Bundled example DE datasets for the liver dashboard sidebar."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from dashboard_visualisation.liver_resource.reference_data import get_data_root

ExampleKind = Literal["single", "multi"]

# Two curated sidebar examples: one solid-leaf (single DE), one pie-leaf (multi DE).
SINGLE_EXAMPLES: dict[str, str] = {
    "hcc-control": "HCC-Control.txt",
}

MULTI_EXAMPLES: dict[str, list[str]] = {
    "two-comparisons": [
        "HCC-Control.txt",
        "sleep.deprived.AK-control.AK.txt",
    ],
}

EXAMPLE_LABELS: dict[str, str] = {
    "hcc-control": "HCC vs control (single file)",
    "two-comparisons": "HCC + sleep deprived (pie chart)",
}

EXAMPLE_KINDS: dict[str, ExampleKind] = {
    "hcc-control": "single",
    "two-comparisons": "multi",
}

EXAMPLE_SLUG_ORDER: tuple[str, ...] = ("hcc-control", "two-comparisons")


def list_example_slugs() -> list[str]:
    """Return example slugs shown in the sidebar, in display order."""
    return list(EXAMPLE_SLUG_ORDER)


def _example_path(filename: str) -> Path | None:
    path = get_data_root() / "examples" / filename
    return path if path.is_file() else None


def get_example_path(slug: str) -> Path | None:
    """Return the path for a single-file example slug, or None when unknown."""
    filename = SINGLE_EXAMPLES.get(slug)
    if filename is None:
        return None
    return _example_path(filename)


def get_example_uploads(slug: str) -> list[tuple[str, Path]] | None:
    """Return ``(filename, path)`` pairs for a sidebar example slug."""
    if slug in SINGLE_EXAMPLES:
        path = _example_path(SINGLE_EXAMPLES[slug])
        if path is None:
            return None
        return [(path.name, path)]

    if slug in MULTI_EXAMPLES:
        uploads: list[tuple[str, Path]] = []
        for filename in MULTI_EXAMPLES[slug]:
            path = _example_path(filename)
            if path is None:
                return None
            uploads.append((filename, path))
        return uploads

    return None


def list_examples() -> list[dict[str, str]]:
    """Return metadata for sidebar example buttons."""
    examples: list[dict[str, str]] = []
    for slug in list_example_slugs():
        if slug in SINGLE_EXAMPLES:
            filename = SINGLE_EXAMPLES[slug]
        else:
            filename = ", ".join(MULTI_EXAMPLES[slug])
        examples.append(
            {
                "slug": slug,
                "label": EXAMPLE_LABELS[slug],
                "kind": EXAMPLE_KINDS[slug],
                "filename": filename,
            }
        )
    return examples
