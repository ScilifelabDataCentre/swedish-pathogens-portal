"""Service functions for the Genomic data page.

Responsible for:
(1) resolving the active (selected) pathogen, record type and page number.
(2) fetching record counts and one page of records from ENA.
(3) building the context for the ENA listing partial template.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog
from django.core.paginator import Paginator
from django.http import HttpRequest
from django.utils.http import urlencode

from portal_data.ena import (
    DEFAULT_RECORD_TYPE,
    RECORD_TYPES,
    RecordType,
    build_download_url,
    build_query,
    fetch_count,
    fetch_records,
)

if TYPE_CHECKING:
    from cms.pages.genomic_data import GenomicDataPage

LOGGER = structlog.get_logger(__name__)

PAGE_SIZE = 25


@dataclass(frozen=True)
class EnaPathogen:
    """A pathogen whose Swedish records are listed from ENA.

    Attributes:
        name: The pathogen name shown on the page.
        taxon_ids: NCBI taxonomy ids; records in any of these taxa (or below) match.
    """

    name: str
    taxon_ids: tuple[int, ...]

    @property
    def query(self) -> str:
        """Return the ENA query for this pathogen's Swedish records."""
        return build_query(self.taxon_ids)


def _clean_param(request: HttpRequest, name: str) -> str:
    """Return a single-line, stripped query parameter value."""
    return request.GET.get(name, "").strip().replace("\n", "").replace("\r", "")


def resolve_active_pathogen(page: GenomicDataPage, request: HttpRequest) -> EnaPathogen | None:
    """Resolve the selected pathogen from the request's ``pathogen`` query parameter.

    If none is given (e.g. initial page load), return the first pathogen.
    Otherwise return the matching pathogen, or None if it isn't configured.
    """
    requested = _clean_param(request, "pathogen")
    if not requested:
        return page.pathogens[0] if page.pathogens else None

    pathogen = page.pathogens_by_name.get(requested)
    if pathogen is None:
        LOGGER.warning(
            "genomic_data.unknown_pathogen",
            requested=requested,
            available=list(page.pathogens_by_name),
        )
    return pathogen


def resolve_record_type(request: HttpRequest) -> RecordType:
    """Resolve the selected record type, falling back to the default if unknown."""
    requested = _clean_param(request, "type")
    return RECORD_TYPES.get(requested) or RECORD_TYPES[DEFAULT_RECORD_TYPE]


def _page_number(request: HttpRequest) -> int:
    """Parse the requested page number, defaulting to 1 for missing or invalid values."""
    try:
        return max(int(_clean_param(request, "page") or 1), 1)
    except ValueError:
        return 1


def _url(path: str, *, pathogen: str, record_type: str, page: int = 1) -> str:
    """Build a link to ``path`` for the given pathogen, record type and page.

    The page number is left out for the first page, to keep URLs short.
    """
    params: dict[str, str | int] = {"pathogen": pathogen, "type": record_type}
    if page > 1:
        params["page"] = page
    return f"{path}?{urlencode(params)}"


def _format_count(count: int | None) -> str:
    """Format a count with thousands separators, or "?" if it couldn't be fetched."""
    return "?" if count is None else f"{count:,}"


def _fetch_counts(query: str) -> dict[str, int | None]:
    """Fetch the record count for every record type concurrently."""
    with ThreadPoolExecutor(max_workers=len(RECORD_TYPES)) as executor:
        futures = {
            key: executor.submit(fetch_count, record_type, query)
            for key, record_type in RECORD_TYPES.items()
        }
        return {key: future.result() for key, future in futures.items()}


def build_context_dict(request: HttpRequest, page: GenomicDataPage) -> dict[str, Any]:
    """Build the context for the ENA listing partial template."""
    path = request.path
    active_pathogen = resolve_active_pathogen(page=page, request=request)
    record_type = resolve_record_type(request)

    pathogen_links = [
        {
            "name": pathogen.name,
            "url": _url(path, pathogen=pathogen.name, record_type=record_type.result),
            "active": active_pathogen is not None and pathogen.name == active_pathogen.name,
        }
        for pathogen in page.pathogens
    ]
    context: dict[str, Any] = {
        "pathogen_links": pathogen_links,
        "active_pathogen": active_pathogen.name if active_pathogen else None,
        "record_type": record_type,
        "type_links": [],
        "count": None,
        "count_display": "",
        "records": [],
        "fetch_error": False,
        "page_obj": None,
        "page_links": [],
        "previous_url": None,
        "next_url": None,
        "download_url": None,
    }
    if active_pathogen is None:
        return context

    query = active_pathogen.query
    counts = _fetch_counts(query)
    count = counts[record_type.result]

    context["type_links"] = [
        {
            "label": rt.label,
            "count": counts[key],
            "count_display": _format_count(counts[key]),
            "url": _url(path, pathogen=active_pathogen.name, record_type=rt.result),
            "active": rt.result == record_type.result,
        }
        for key, rt in RECORD_TYPES.items()
    ]
    context["count"] = count
    context["count_display"] = _format_count(count)

    if count is None:
        context["fetch_error"] = True
        return context
    if count == 0:
        return context

    # A range stands in for the records, so Django can do the page maths without
    # loading anything: only the requested page is fetched from ENA.
    page_obj = Paginator(range(count), PAGE_SIZE).get_page(_page_number(request))
    records = fetch_records(record_type, query, offset=page_obj.start_index() - 1, limit=PAGE_SIZE)
    if records is None:
        context["fetch_error"] = True
        return context

    def page_url(number: int) -> str:
        """Return the link to page ``number`` of the current listing."""
        return _url(
            path, pathogen=active_pathogen.name, record_type=record_type.result, page=number
        )

    context.update(
        {
            "records": records,
            "page_obj": page_obj,
            "start_display": _format_count(page_obj.start_index()),
            "end_display": _format_count(page_obj.end_index()),
            "page_links": [
                {"number": number, "url": page_url(number), "current": number == page_obj.number}
                if number != Paginator.ELLIPSIS
                else None
                for number in page_obj.paginator.get_elided_page_range(
                    page_obj.number, on_each_side=2, on_ends=1
                )
            ],
            "previous_url": (
                page_url(page_obj.previous_page_number()) if page_obj.has_previous() else None
            ),
            "next_url": page_url(page_obj.next_page_number()) if page_obj.has_next() else None,
            "download_url": build_download_url(record_type, query),
        }
    )
    return context
