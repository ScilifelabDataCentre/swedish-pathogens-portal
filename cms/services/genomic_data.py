"""Service functions for the Genomic data page.

Responsible for:
(1) reading the selected data type, search words, facets, sort and page from the request.
(2) searching EBI Search's ENA pathogen indexes for one page of Swedish records.
(3) building the context for the listing partial template.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from django.core.paginator import Paginator
from django.http import HttpRequest
from django.utils.http import urlencode

from portal_data.ebi_search import (
    DATA_TYPES,
    DEFAULT_DATA_TYPE,
    FACET_FIELDS,
    Column,
    DataType,
    SearchResult,
    fetch_count,
    is_valid_facet_value,
    search,
)

if TYPE_CHECKING:
    from cms.pages.genomic_data import GenomicDataPage

# Results per page the visitor can choose from, and the one used by default.
# The accession column is always first, always shown and always sortable.
ACCESSION_COLUMN = Column("acc", "Accession", sortable=True)
PAGE_SIZE_OPTIONS: tuple[int, ...] = (25, 50, 100)
DEFAULT_PAGE_SIZE = PAGE_SIZE_OPTIONS[0]
# Longest search text accepted from the query string.
MAX_SEARCH_LENGTH = 200
# Facet values shown before the rest are tucked behind "Show more".
FACET_VALUES_SHOWN = 4


@dataclass(frozen=True)
class Sort:
    """The column the table is sorted on, and in which direction."""

    field: str
    descending: bool = False


@dataclass(frozen=True)
class ListingState:
    """Everything the request selects: data type, search words, facets, sort and page size."""

    data_type: DataType
    text: str
    facets: dict[str, list[str]]
    sort: Sort | None
    page_size: int = DEFAULT_PAGE_SIZE

    def url(
        self,
        path: str,
        *,
        page: int = 1,
        data_type: DataType | None = None,
        facets: dict[str, list[str]] | None = None,
        sort: Sort | None | bool = True,
    ) -> str:
        """Build a link to ``path`` for this state, with any of its parts replaced.

        ``sort=True`` (the default) keeps the current sort, None drops it. The page
        size is always kept. The page number and the default page size are left out,
        to keep URLs short.
        """
        sort = self.sort if sort is True else sort
        params: list[tuple[str, str | int]] = [("type", (data_type or self.data_type).key)]
        if self.text:
            params.append(("q", self.text))
        for facet_field, values in (self.facets if facets is None else facets).items():
            params.extend((facet_field, value) for value in values)
        if isinstance(sort, Sort):
            params.extend([("sort", sort.field), ("order", "desc" if sort.descending else "asc")])
        if self.page_size != DEFAULT_PAGE_SIZE:
            params.append(("size", self.page_size))
        if page > 1:
            params.append(("page", page))
        return f"{path}?{urlencode(params)}"


def _clean(value: str) -> str:
    """Return a single-line, stripped query parameter value."""
    return value.strip().replace("\n", "").replace("\r", "")


def resolve_state(request: HttpRequest) -> ListingState:
    """Read the listing state from the request's query parameters.

    Unknown data types fall back to the default, facet parameters are limited to
    known facet fields, the sort must be a sortable field of the data type, and
    the page size must be one of ``PAGE_SIZE_OPTIONS``.
    """
    data_type = DATA_TYPES.get(_clean(request.GET.get("type", ""))) or DATA_TYPES[DEFAULT_DATA_TYPE]
    text = _clean(request.GET.get("q", ""))[:MAX_SEARCH_LENGTH]

    facets: dict[str, list[str]] = {}
    for facet_field in FACET_FIELDS:
        values = [_clean(v) for v in request.GET.getlist(facet_field)]
        values = list(dict.fromkeys(v for v in values if is_valid_facet_value(v)))
        if values:
            facets[facet_field] = values

    sort = None
    sort_field = _clean(request.GET.get("sort", ""))
    if sort_field in data_type.sortable_fields:
        sort = Sort(field=sort_field, descending=_clean(request.GET.get("order", "")) == "desc")
    try:
        page_size = int(_clean(request.GET.get("size", "")))
    except ValueError:
        page_size = DEFAULT_PAGE_SIZE
    if page_size not in PAGE_SIZE_OPTIONS:
        page_size = DEFAULT_PAGE_SIZE
    return ListingState(
        data_type=data_type, text=text, facets=facets, sort=sort, page_size=page_size
    )


def _page_number(request: HttpRequest) -> int:
    """Parse the requested page number, defaulting to 1 for missing or invalid values."""
    try:
        return max(int(_clean(request.GET.get("page", "")) or 1), 1)
    except ValueError:
        return 1


def _format_count(count: int | None) -> str:
    """Format a count with thousands separators, or "?" if it couldn't be fetched."""
    return "?" if count is None else f"{count:,}"


def _search_with_counts(
    state: ListingState, page_number: int
) -> tuple[dict[str, int | None], SearchResult | None]:
    """Fetch the tab counts and the requested page of results, all concurrently.

    The count for every data type and the search itself are independent
    requests, so they share one thread pool and the page waits for the slowest
    one, rather than for the counts and then the search in turn.
    """
    with ThreadPoolExecutor(max_workers=len(DATA_TYPES) + 1) as executor:
        search_future = executor.submit(
            search,
            state.data_type,
            text=state.text,
            selected_facets=state.facets,
            start=(page_number - 1) * state.page_size,
            size=state.page_size,
            sort=(state.sort.field, state.sort.descending) if state.sort else None,
        )
        count_futures = {
            key: executor.submit(fetch_count, data_type, state.text)
            for key, data_type in DATA_TYPES.items()
        }
        counts = {key: future.result() for key, future in count_futures.items()}
        return counts, search_future.result()


def _sort_header(
    column: Column, sort: Sort | None, url_for: Callable[[Sort], str]
) -> dict[str, Any]:
    """Build a table header, linking sortable columns to sort on them.

    Clicking the column already sorted ascending flips it to descending; any
    other column starts ascending. ``state`` is the header's ``aria-sort`` value.
    """
    field = column.field
    header: dict[str, Any] = {"column": column, "label": column.label, "state": None, "url": None}
    if not column.sortable:
        return header
    if sort is not None and sort.field == field:
        header["state"] = "descending" if sort.descending else "ascending"
    next_sort = Sort(field=field, descending=header["state"] == "ascending")
    header["url"] = url_for(next_sort)
    header["next_order"] = "descending" if next_sort.descending else "ascending"
    return header


def _facet_input_id(facet_field: str, value: str) -> str:
    """Return a stable, unique checkbox id, so HTMX can restore focus after a swap."""
    digest = hashlib.sha1(value.encode(), usedforsecurity=False).hexdigest()[:10]
    return f"ena-facet-{facet_field}-{digest}"


def build_context_dict(request: HttpRequest, page: GenomicDataPage | None = None) -> dict[str, Any]:
    """Build the context for the Genomic data listing partial template."""
    path = request.path
    state = resolve_state(request)
    data_type = state.data_type
    page_number = _page_number(request)

    counts, result = _search_with_counts(state, page_number)

    context: dict[str, Any] = {
        "state": state,
        "data_type": data_type,
        "search_text": state.text,
        "type_links": [
            {
                "label": dt.label,
                "count_display": _format_count(counts[key]),
                # switching data type keeps the search words but not the facets or sort,
                # as each index has its own facets and sortable fields
                "url": state.url(path, data_type=dt, facets={}, sort=None),
                "active": dt.key == data_type.key,
            }
            for key, dt in DATA_TYPES.items()
        ],
        "facets": [],
        "facets_active": bool(state.facets),
        "clear_facets_url": state.url(path, facets={}),
        "fetch_error": result is None,
        "records": [],
        "page_obj": None,
        "sort_headers": [],
        "page_size": state.page_size,
        "page_size_options": PAGE_SIZE_OPTIONS,
    }
    if result is None:
        return context

    context["facets"] = []
    for facet in result.facets:
        values = [
            {
                "value": v,
                "id": _facet_input_id(facet.field, v.value),
                "count_display": _format_count(v.count),
            }
            for v in facet.values
        ]
        context["facets"].append(
            {
                "field": facet.field,
                "label": facet.label,
                "values": values[:FACET_VALUES_SHOWN],
                "more_values": values[FACET_VALUES_SHOWN:],
                # keep "Show more" open when one of its values is selected
                "more_selected": any(v.selected for v in facet.values[FACET_VALUES_SHOWN:]),
            }
        )
    if result.total == 0:
        return context

    # A range stands in for the results, so Django can do the page maths: only the
    # requested page is fetched from EBI Search. A page past the end is clamped.
    page_obj = Paginator(range(result.total), state.page_size).get_page(page_number)
    if page_obj.number != page_number:
        result = search(
            data_type,
            text=state.text,
            selected_facets=state.facets,
            start=page_obj.start_index() - 1,
            size=state.page_size,
            sort=(state.sort.field, state.sort.descending) if state.sort else None,
        )
        if result is None:
            context["fetch_error"] = True
            return context

    def page_url(number: int) -> str:
        """Return the link to page ``number`` of the current results."""
        return state.url(path, page=number)

    def sort_url(sort: Sort) -> str:
        """Return the link that sorts the results by ``sort`` (back on page 1)."""
        return state.url(path, sort=sort)

    context.update(
        {
            "records": result.records,
            "page_obj": page_obj,
            "total_display": _format_count(result.total),
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
            "sort_headers": [
                _sort_header(ACCESSION_COLUMN, state.sort, sort_url),
                *(_sort_header(column, state.sort, sort_url) for column in data_type.columns),
            ],
            # each row's cells paired with their column, for per-column styling and hiding
            "rows": [
                {"record": record, "cells": list(zip(data_type.columns, record.cells, strict=True))}
                for record in result.records
            ],
            # the columns visitors can show or hide (the accession is always shown)
            "columns": data_type.columns,
        }
    )
    return context
