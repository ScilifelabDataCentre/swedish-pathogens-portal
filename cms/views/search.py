"""Site-wide search: a faceted, paginated results page over Wagtail pages."""

from collections.abc import Sequence

from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from wagtail.models import Page
from wagtail.query import PageQuerySet

from cms.pages import (
    AvailableDataPage,
    BasicPage,
    CataloguePage,
    ContactPage,
    DashboardPage,
    HighlightsAndEditorialsPage,
    NewsPage,
    OutbreakPage,
    PlpProjectPage,
    PortalDataPage,
    PublicationsPage,
    SLUDashboardSubPage,
    TopicPage,
)

# Ordered (page types, facet key, human label). Listing/index/home pages are excluded.
# A facet may cover several page types: `DashboardPage` also matches its subclasses
# (DRR datasets, the Liver resource, the SLU dashboard) through multi-table
# inheritance, and the singleton pages are grouped rather than given a tab each.
SEARCH_TYPES: list[tuple[tuple[type[Page], ...], str, str]] = [
    ((NewsPage,), "news", "News"),
    ((HighlightsAndEditorialsPage,), "articles", "Articles"),
    ((TopicPage,), "topics", "Topics"),
    ((OutbreakPage,), "outbreaks", "Outbreaks"),
    ((DashboardPage, SLUDashboardSubPage), "dashboards", "Dashboards"),
    ((PlpProjectPage,), "plp", "PLP projects"),
    ((CataloguePage,), "catalogue", "Catalogue"),
    ((PortalDataPage,), "datasets", "Datasets"),
    ((BasicPage, AvailableDataPage, ContactPage, PublicationsPage), "pages", "Pages"),
]
SEARCH_MODELS: list[type[Page]] = [model for models, _, _ in SEARCH_TYPES for model in models]
_MODELS_BY_KEY: dict[str, tuple[type[Page], ...]] = {key: models for models, key, _ in SEARCH_TYPES}
PAGE_SIZE = 12
AUTOCOMPLETE_LIMIT = 8


def _queryset_for(models: Sequence[type[Page]]) -> PageQuerySet:
    """Return live, public pages restricted to the given page types and their subclasses."""
    return Page.objects.live().public().type(*models)


def _base_queryset() -> PageQuerySet:
    """Return live, public pages restricted to the searchable page types."""
    return _queryset_for(SEARCH_MODELS)


def page_type_label(page: Page) -> str:
    """Return the facet label describing what kind of page this is.

    Matched with ``isinstance`` rather than an exact type lookup so that
    subclasses reached through multi-table inheritance — a ``DrrDatasetPage`` is
    a ``DashboardPage`` — are labelled instead of falling through to a blank
    badge.
    """
    for models, _, label in SEARCH_TYPES:
        if isinstance(page, tuple(models)):
            return label
    return ""


def page_location(page: Page) -> list[dict[str, str | None]]:
    """Return a page's searchable ancestors, for display under its title.

    Two pages can share a title, so the type label alone does not always
    separate them; where they sit does. Only ancestors that are themselves
    searchable are kept. The rest — the site root, the home page and listing
    pages such as "News & Updates" — are structural containers whose name the
    type badge already conveys, so naming them would put a line of noise under
    every result instead of only the nested ones that need it.
    """
    searchable = tuple(SEARCH_MODELS)
    return [
        {"title": ancestor.title, "url": ancestor.url if ancestor.live else None}
        for ancestor in page.get_ancestors().specific()
        if isinstance(ancestor, searchable)
    ]


def search(request: HttpRequest) -> HttpResponse:
    """Render the site-wide search results page, faceted by page type."""
    query = request.GET.get("q", "").strip()
    selected = request.GET.get("type", "").strip()
    facets: list[dict[str, object]] = []
    items: list[dict[str, object]] = []
    total = 0
    shown = 0
    page_obj = None

    if query:
        for models, key, label in SEARCH_TYPES:
            count = _queryset_for(models).search(query, operator="and").count()
            if count:
                facets.append({"key": key, "label": label, "count": count})
        total = sum(int(facet["count"]) for facet in facets)

        narrowed = _MODELS_BY_KEY.get(selected)
        base = _queryset_for(narrowed) if narrowed else _base_queryset()
        results = base.search(query, operator="and")

        paginator = Paginator(results, PAGE_SIZE)
        page_obj = paginator.get_page(request.GET.get("page"))
        # What the visitor is actually looking at: narrowed by the facet, where
        # `total` stays the count across every type for the "All" tab.
        shown = paginator.count
        for page in page_obj:
            specific = page.specific
            items.append(
                {
                    "url": specific.url,
                    "title": specific.title,
                    "excerpt": getattr(specific, "description", "") or specific.search_description,
                    "label": page_type_label(specific),
                    "ancestors": page_location(specific),
                }
            )

    context = {
        "page_heading": "Search",
        "query": query,
        "selected": selected,
        "facets": facets,
        "total": total,
        "shown": shown,
        "items": items,
        "page_obj": page_obj,
    }
    return render(request, "cms/search/results.html", context)


def search_autocomplete(request: HttpRequest) -> HttpResponse:
    """Return an htmx partial of top title matches for the typeahead dropdown."""
    query = request.GET.get("q", "").strip()
    results: list[dict[str, object]] = []
    if query:
        matches = _base_queryset().autocomplete(query)[:AUTOCOMPLETE_LIMIT]
        for page in matches:
            specific = page.specific
            results.append(
                {
                    "url": specific.url,
                    "title": specific.title,
                    "label": page_type_label(specific),
                }
            )
    return render(request, "cms/search/autocomplete.html", {"query": query, "results": results})
