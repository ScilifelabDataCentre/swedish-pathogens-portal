"""Service functions for the Models and apps page (pathogen-related apps on SciLifeLab Serve).

Responsible for:
(1) reading the search words, facets and sort order from the request.
(2) filtering the (cached) Serve apps and counting the facet values.
(3) building the context for the listing partial template.

Serve's whole public catalogue is small enough to fetch at once, so searching,
filtering and sorting are done here rather than by the API.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from django.http import HttpRequest
from django.utils.http import urlencode
from django.utils.text import capfirst

from portal_data.serve_apps import SERVE_URL, ServeApp, fetch_public_apps, relevant_apps

if TYPE_CHECKING:
    from cms.pages.serve_apps import ServeAppsPage

# Longest search text accepted from the query string.
MAX_SEARCH_LENGTH = 200
# Facet values shown before the rest are tucked behind "Show more".
FACET_VALUES_SHOWN = 4
# Sorts before any date, so apps without one go last when sorting newest first.
_NO_DATE = datetime.min.replace(tzinfo=UTC)


@dataclass(frozen=True)
class Facet:
    """A facet: a query parameter and how to read its values from an app."""

    field: str
    label: str
    values_of: Callable[[ServeApp], tuple[str, ...]]
    value_label: Callable[[str], str] = str


@dataclass(frozen=True)
class SortOption:
    """A sort order the visitor can choose."""

    key: str
    label: str
    sort: Callable[[list[ServeApp]], list[ServeApp]]


FACETS: dict[str, Facet] = {
    facet.field: facet
    for facet in (
        # in display order: pathogen first, as that's what visitors come to filter on
        Facet("keyword", "Pathogen keyword", lambda app: app.keywords, capfirst),
        Facet("type", "App type", lambda app: (app.app_type,)),
    )
}
SORT_OPTIONS: dict[str, SortOption] = {
    option.key: option
    for option in (
        SortOption(
            "updated",
            "Recently updated",
            lambda apps: sorted(apps, key=lambda a: a.updated_on or _NO_DATE, reverse=True),
        ),
        SortOption(
            "created",
            "Newest",
            lambda apps: sorted(apps, key=lambda a: a.created_on or _NO_DATE, reverse=True),
        ),
        SortOption(
            "name", "Name (A-Z)", lambda apps: sorted(apps, key=lambda a: a.name.casefold())
        ),
    )
}
DEFAULT_SORT = "updated"


@dataclass(frozen=True)
class ListingState:
    """Everything the request selects: search words, facets and sort order."""

    text: str
    facets: dict[str, list[str]]
    sort: str = DEFAULT_SORT

    def url(self, path: str, *, facets: dict[str, list[str]] | None = None) -> str:
        """Build a link to ``path`` for this state, optionally with other facets.

        The default sort is left out, to keep URLs short.
        """
        params: list[tuple[str, str]] = []
        if self.text:
            params.append(("q", self.text))
        for field, values in (self.facets if facets is None else facets).items():
            params.extend((field, value) for value in values)
        if self.sort != DEFAULT_SORT:
            params.append(("sort", self.sort))
        return f"{path}?{urlencode(params)}" if params else path


def _clean(value: str) -> str:
    """Return a single-line, stripped query parameter value."""
    return value.strip().replace("\n", "").replace("\r", "")


def resolve_state(request: HttpRequest) -> ListingState:
    """Read the listing state from the request's query parameters.

    Facet parameters are limited to known facets (their values are only compared
    with the apps' own values, so needn't be validated further), and unknown sort
    orders fall back to the default.
    """
    text = _clean(request.GET.get("q", ""))[:MAX_SEARCH_LENGTH]
    facets: dict[str, list[str]] = {}
    for field in FACETS:
        values = [_clean(v)[:MAX_SEARCH_LENGTH] for v in request.GET.getlist(field)]
        values = list(dict.fromkeys(v for v in values if v))
        if values:
            facets[field] = values
    sort = _clean(request.GET.get("sort", ""))
    return ListingState(
        text=text, facets=facets, sort=sort if sort in SORT_OPTIONS else DEFAULT_SORT
    )


def _matches_text(app: ServeApp, words: list[str]) -> bool:
    """Return True if every search word is in the app's name, description, type or keywords."""
    haystack = " ".join((app.name, app.description, app.app_type, *app.keywords)).casefold()
    return all(word in haystack for word in words)


def _matches_facets(app: ServeApp, facets: dict[str, list[str]], skip: str | None = None) -> bool:
    """Return True if the app has one of the selected values of every facet (but ``skip``)."""
    return all(
        any(value in FACETS[field].values_of(app) for value in values)
        for field, values in facets.items()
        if field != skip
    )


def _facet_input_id(field: str, value: str) -> str:
    """Return a stable, unique checkbox id, so HTMX can restore focus after a swap."""
    digest = hashlib.sha1(value.encode(), usedforsecurity=False).hexdigest()[:10]
    return f"serve-facet-{field}-{digest}"


def _build_facets(apps: list[ServeApp], state: ListingState) -> list[dict[str, Any]]:
    """Build the facet lists, each counted over the apps matching the search and other facets.

    So a facet's counts show what ticking one more of its values would add (values
    within a facet are OR-ed, facets are AND-ed). Selected values are kept even
    when nothing matches them, so they can be unticked.
    """
    facets = []
    for field, facet in FACETS.items():
        counts = Counter(
            value
            for app in apps
            if _matches_facets(app, state.facets, skip=field)
            for value in dict.fromkeys(facet.values_of(app))
        )
        selected = state.facets.get(field, [])
        for value in selected:
            counts.setdefault(value, 0)
        if not counts:
            continue
        values = [
            {
                "value": {
                    "value": value,
                    "label": facet.value_label(value),
                    "selected": value in selected,
                },
                "id": _facet_input_id(field, value),
                "count_display": f"{count:,}",
            }
            for value, count in sorted(counts.items(), key=lambda vc: (-vc[1], vc[0].casefold()))
        ]
        facets.append(
            {
                "field": field,
                "label": facet.label,
                "values": values[:FACET_VALUES_SHOWN],
                "more_values": values[FACET_VALUES_SHOWN:],
                # keep "Show more" open when one of its values is selected
                "more_selected": any(v["value"]["selected"] for v in values[FACET_VALUES_SHOWN:]),
            }
        )
    return facets


def build_context_dict(request: HttpRequest, page: ServeAppsPage) -> dict[str, Any]:
    """Build the context for the Models and apps listing partial template."""
    state = resolve_state(request)
    context: dict[str, Any] = {
        "state": state,
        "serve_url": SERVE_URL,
        "fetch_error": False,
        "apps": [],
        "total": 0,
        "facets": [],
        "facets_active": bool(state.facets),
        "clear_facets_url": state.url(request.path, facets={}),
        "sort_options": SORT_OPTIONS.values(),
    }

    all_apps = fetch_public_apps()
    if all_apps is None:
        context["fetch_error"] = True
        return context

    apps = relevant_apps(
        all_apps, include_ids=page.include_app_ids, exclude_ids=page.exclude_app_ids
    )
    words = state.text.casefold().split()
    searched = [app for app in apps if _matches_text(app, words)]
    shown = [app for app in searched if _matches_facets(app, state.facets)]
    context.update(
        {
            "apps": SORT_OPTIONS[state.sort].sort(shown),
            "total": len(apps),
            "facets": _build_facets(searched, state),
        }
    )
    return context
