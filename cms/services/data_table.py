"""Data table service: search, paginate, and build template context for tables."""

from __future__ import annotations

from typing import Any

import structlog
from django.core.paginator import Paginator
from django.http import HttpRequest
from django.utils.html import strip_tags
from wagtail.contrib.typed_table_block.blocks import TypedTable

LOGGER = structlog.get_logger(__name__)

DEFAULT_PER_PAGE = 10
DEFAULT_PER_PAGE_OPTIONS: tuple[int, ...] = (10, 25, 50)


def extract_table_data(typed_table: TypedTable | None) -> tuple[list[str], list[list[Any]], str]:
    """Convert a ``TypedTable`` value into plain headers, rows, and caption.

    ``RichTextValue`` objects are kept as-is so the Django template engine
    calls their ``__html__()`` method and renders safe HTML automatically.
    """
    if not typed_table or not typed_table.columns:
        return [], [], ""

    headers = [col["heading"] for col in typed_table.columns]
    rows = [list(row["values"]) for row in typed_table.row_data]
    caption = getattr(typed_table, "caption", "") or ""
    return headers, rows, caption


def extract_block_params(block_value: dict[str, Any]) -> dict[str, Any]:
    """Extract keyword arguments for ``get_table_context`` from a block value.

    Centralises the string-to-int / truthy conversions that both
    ``DataTableBlock.get_context`` and ``table_partial`` need.
    """
    raw_per_page = block_value.get("per_page")
    try:
        per_page = int(raw_per_page or DEFAULT_PER_PAGE)
    except TypeError, ValueError:
        LOGGER.warning("data_table.invalid_per_page", value=raw_per_page)
        per_page = DEFAULT_PER_PAGE

    return {
        "table_id": block_value["table_id"],
        "per_page_default": per_page,
        "show_controls": bool(block_value.get("show_controls", False)),
    }


def get_table_context(
    request: HttpRequest | None,
    rows: list[list[Any]],
    headers: list[str],
    caption: str,
    table_url: str,
    *,
    table_id: str = "data-table",
    per_page_default: int = DEFAULT_PER_PAGE,
    per_page_options: tuple[int, ...] = DEFAULT_PER_PAGE_OPTIONS,
    show_controls: bool = True,
) -> dict[str, Any]:
    """Build the context dict that both data-table templates expect.

    Args:
        request:          The current HTTP request (GET params are read from it).
                          May be ``None`` when rendered outside a request cycle
                          (e.g. management commands, Wagtail previews).
        rows:             Full dataset as a list-of-lists (one inner list per row).
        headers:          Column header strings, same length as each row.
        caption:          Text for the ``<caption>`` element (from the
                          TypedTableBlock's built-in caption field).
        table_url:        The URL that HTMX controls will call for updates.
        table_id:         HTML id prefix used by the template and HTMX targets.
        per_page_default: Number of rows shown when the user hasn't chosen.
        per_page_options: Choices offered in the "entries per page" select.
        show_controls:    When False the template hides the search bar,
                          entries-per-page selector, and status line, and
                          any ``search`` or ``per_page`` params are ignored.

    Returns:
        A dict ready to pass (or nest) into a template context.
    """
    params = request.GET if request else {}
    # Without controls there is no search input to clear a filter with.
    search = params.get("search", "").strip() if show_controls else ""

    try:
        page_number = int(params.get("page", 1))
    except TypeError, ValueError:
        LOGGER.warning("data_table.invalid_page_param", value=params.get("page"))
        page_number = 1

    if search:
        term = search.lower()
        rows = [row for row in rows if any(term in strip_tags(str(cell)).lower() for cell in row)]

    if not show_controls:
        # Show every row on one page. max(..., 1) keeps Paginator happy.
        per_page = max(len(rows), 1)
    else:
        raw_per_page = params.get("per_page", per_page_default)
        try:
            per_page = int(raw_per_page)
        except TypeError, ValueError:
            LOGGER.warning("data_table.invalid_per_page_param", value=raw_per_page)
            per_page = per_page_default
        if per_page not in per_page_options:
            per_page = per_page_default

    paginator = Paginator(rows, per_page)
    page_obj = paginator.get_page(page_number)

    page_range = [
        None if p == Paginator.ELLIPSIS else p
        for p in paginator.get_elided_page_range(page_obj.number, on_each_side=2, on_ends=1)
    ]

    return {
        "table_id": table_id,
        "caption": caption,
        "table_url": table_url,
        "headers": headers,
        "page_obj": page_obj,
        "page_range": page_range,
        "search": search,
        "per_page": per_page,
        "per_page_options": per_page_options,
        "total_count": paginator.count,
        "start_index": page_obj.start_index(),
        "end_index": page_obj.end_index(),
        "show_controls": show_controls,
    }
