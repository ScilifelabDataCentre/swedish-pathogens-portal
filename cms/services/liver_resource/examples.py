"""Bundled example DE datasets for the liver dashboard."""

from __future__ import annotations

from pathlib import Path

from cms.services.liver_resource.reference_data import get_data_root

EXAMPLE_SLUGS: dict[str, str] = {
    "hcc-control": "HCC-Control.txt",
    "sleep-deprived": "sleep.deprived.AK-control.AK.txt",
    "slc16a13-ko": "SLC16A13_KO-Wild_type.txt",
}


def get_example_path(slug: str) -> Path | None:
    """Return the path to a bundled example file for a URL slug."""
    filename = EXAMPLE_SLUGS.get(slug)
    if filename is None:
        return None
    path = get_data_root() / "examples" / filename
    if not path.is_file():
        return None
    return path


def list_example_slugs() -> list[str]:
    """Return available example slugs in stable order."""
    return sorted(EXAMPLE_SLUGS)
