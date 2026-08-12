"""Locations of the derived DRR artefacts on disk (spec section 4).

One definition of the per-dataset directory, shared by the ``drr_precompute``
command that writes the artefacts and the ``DrrDatasetPage`` routes that serve
them, so the writer and the reader cannot drift apart.
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings


def artefact_dir(slug: str) -> Path:
    """Return the derived-artefact directory for one DRR dataset.

    Args:
        slug: The dataset slug, matching both the page slug and
            ``DrrDatasetData.dataset_slug``.

    Returns:
        Path: ``MEDIA_ROOT/drr/<slug>``. Raw imagery never lands here.
    """
    return Path(settings.MEDIA_ROOT) / "drr" / slug
