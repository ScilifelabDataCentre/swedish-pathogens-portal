"""Resolve the HepaGeNIE supplementary workbook from Wagtail Documents.

Editors upload the Jackie xlsx in Wagtail admin → Documents and set the
document title to :data:`SUPPLEMENTARY_DOCUMENT_TITLE`. No page FK and no
migration — same spirit as reusing the dashboard card image for the
reference TLN map.
"""

from __future__ import annotations

from typing import Any

SUPPLEMENTARY_DOCUMENT_TITLE = "HepaGeNIE supplementary"
DOWNLOAD_FILENAME = "HepaGeNIE_supplementary_module_data.xlsx"


def get_supplementary_document() -> Any | None:
    """Return the Wagtail Document for the supplementary workbook, if uploaded.

    Looks up by exact title :data:`SUPPLEMENTARY_DOCUMENT_TITLE` (case-insensitive).
    """
    from wagtail.documents import get_document_model

    Document = get_document_model()
    return (
        Document.objects.filter(title__iexact=SUPPLEMENTARY_DOCUMENT_TITLE)
        .order_by("-created_at")
        .first()
    )
