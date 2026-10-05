"""Summary counts of portal data studies, for display outside the listing page.

Used by the ``PortalDataSummaryBlock`` on the Available Data page to show how
many studies are available and a per-facet breakdown, with links back into the
(pre-filtered) Portal data listing.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from cms.services.caching import cache_get_or_set

from .services import build_facets, get_datatype_config, load_all_items

SUMMARY_CACHE_TTL_SECONDS = 60 * 60  # 1 hour


def filter_by_country(items: list[dict[str, Any]], country: str) -> list[dict[str, Any]]:
    """Return the items whose ``country`` matches ``country`` (case-insensitive).

    An empty ``country`` means "no filter" and returns all items unchanged.
    """
    country = country.strip().casefold()
    if not country:
        return items
    return [it for it in items if str(it.get("country") or "").strip().casefold() == country]


def get_summary_counts(*, datatype: str, facet: str, country: str = "") -> dict[str, Any]:
    """Return the total study count and per-value counts for one facet.

    Returns a dict with ``total`` (int) and ``buckets`` (list of ``{"value", "count"}``),
    cached for ``SUMMARY_CACHE_TTL_SECONDS`` as parsing every study's metadata is slow.
    """
    cache_key = f"portal_data_summary_{datatype}_{facet}_{country.strip().casefold()}"

    def compute() -> dict[str, Any]:
        """Use in cache_get_or_set to compute the counts if cache miss."""
        items = filter_by_country(load_all_items(datatype), country)
        facets = build_facets(items=items, facet_names=[facet], filters={}, datatype=datatype)
        buckets = [{"value": b["value"], "count": b["count"]} for b in facets.get(facet, [])]
        return {"total": len(items), "buckets": buckets}

    result = cache_get_or_set(key=cache_key, timeout=SUMMARY_CACHE_TTL_SECONDS, compute=compute)
    return result if result is not None else {"total": 0, "buckets": []}


def build_portal_data_summary(
    *,
    datatype: str,
    listing_url: str,
    facet: str,
    country: str = "",
    title: str = "",
    max_rows: int = 8,
) -> dict[str, Any] | None:
    """Build a section dict for the Available Data page's category partial.

    The returned dict has the same shape as the EBI sections built in
    ``cms.services.available_data`` (title, total_count, total_url, rows), plus
    ``internal=True`` so links open in the same tab. Each row links to the
    listing pre-filtered on that facet value.

    Returns None for an unknown datatype.
    """
    config = get_datatype_config(datatype)
    if config is None:
        return None

    counts = get_summary_counts(datatype=datatype, facet=facet, country=country)

    buckets = counts["buckets"]
    # year is already sorted most recent first, otherwise show the largest groups first
    if facet != "year":
        buckets = sorted(buckets, key=lambda b: (-b["count"], b["value"]))

    rows = [
        {
            "label": bucket["value"],
            # facet values (e.g. "LC-MS", "NMR spectroscopy") are shown as-is, not title-cased
            "display_label": bucket["value"],
            "count": bucket["count"],
            "url": f"{listing_url}?{urlencode({facet: bucket['value']})}",
        }
        for bucket in buckets[:max_rows]
    ]

    return {
        "title": title or config.label,
        "total_count": counts["total"],
        "total_url": listing_url,
        "rows": rows,
        "internal": True,
    }
