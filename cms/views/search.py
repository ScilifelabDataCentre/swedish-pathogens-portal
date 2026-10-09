"""Site-wide search: a faceted, paginated results page over Wagtail pages."""

from collections.abc import Sequence
from functools import cache

from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils.http import urlencode
from django.views.decorators.vary import vary_on_headers
from wagtail.models import Page
from wagtail.query import PageQuerySet
from wagtail.search.backends import get_search_backend
from wagtail.search.backends.base import BaseSearchQueryCompiler, BaseSearchResults

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
# Mirrors the maxlength on the search inputs. A direct request bypasses that,
# and the backend compiles each term into a nested expression, so a query of a
# few hundred terms overflows the stack while the query is being built.
MAX_QUERY_LENGTH = 100


def _clean_query(request: HttpRequest) -> str:
    """Return the submitted query, trimmed and capped at a safe length."""
    return request.GET.get("q", "").strip()[:MAX_QUERY_LENGTH]


def _queryset_for(models: Sequence[type[Page]]) -> PageQuerySet:
    """Return live, public pages restricted to the given page types and their subclasses."""
    return Page.objects.live().public().type(*models)


def _base_queryset() -> PageQuerySet:
    """Return live, public pages restricted to the searchable page types."""
    return _queryset_for(SEARCH_MODELS)


@cache
def _last_term_prefix(compiler: type[BaseSearchQueryCompiler]) -> type[BaseSearchQueryCompiler]:
    """Return the backend's full-text compiler, with the last search term matched as a prefix."""
    return type(f"LastTermPrefix{compiler.__name__}", (compiler,), {"LAST_TERM_IS_PREFIX": True})


def _full_text_search(queryset: PageQuerySet, query: str) -> BaseSearchResults:
    """Search titles and body text, treating the last word as possibly half-typed.

    The dropdown's ``autocomplete()`` matches what has been typed so far, so
    "wastew" suggests the wastewater pages; pressing Enter has to find them too.
    ``search()`` only matches whole words, so this runs the backend's own
    compiler with the switch its autocomplete compiler flips, ``LAST_TERM_IS_PREFIX``,
    over the full title and body index. The words before the last stay whole
    and stemmed.

    ``_search`` is the shared entry point behind both ``search()`` and
    ``autocomplete()`` in modelsearch, the package Wagtail delegates search to.
    It is internal, so the partial-word tests in ``test_search`` guard it.
    """
    backend = get_search_backend()
    return backend._search(
        _last_term_prefix(backend.query_compiler_class),
        query,
        queryset,
        fields=None,
        operator="and",
        order_by_relevance=True,
    )


def _results_url(query: str, facet: str = "", page: int | None = None) -> str:
    """Return the relative results URL for a query, optionally narrowed to a facet and paged.

    Each facet and pagination link uses it twice, as the ``href`` that works
    without JavaScript and as the ``hx-get`` that swaps the results in place.
    """
    params: dict[str, str | int] = {"q": query}
    if facet:
        params["type"] = facet
    if page:
        params["page"] = page
    return f"?{urlencode(params)}"


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


@vary_on_headers("HX-Request", "HX-History-Restore-Request")
def search(request: HttpRequest) -> HttpResponse:
    """Render the site-wide search results page, faceted by page type.

    Facet and pagination links are htmx requests: they get only the results
    partial, which swaps in place and updates the result count. A history
    restore (back button after htmx's cache was evicted) gets the full page.
    It sends ``HX-Request`` as well, so both headers are in ``Vary``.
    """
    query = _clean_query(request)
    selected = request.GET.get("type", "").strip()
    if selected not in _MODELS_BY_KEY:
        selected = ""
    facets: list[dict[str, object]] = []
    items: list[dict[str, object]] = []
    total = 0
    shown = 0
    page_obj = None

    if query:
        for models, key, label in SEARCH_TYPES:
            count = _full_text_search(_queryset_for(models), query).count()
            if count:
                facets.append(
                    {"key": key, "label": label, "count": count, "url": _results_url(query, key)}
                )
        total = sum(int(facet["count"]) for facet in facets)

        base = _queryset_for(_MODELS_BY_KEY[selected]) if selected else _base_queryset()
        results = _full_text_search(base, query)

        paginator = Paginator(results, PAGE_SIZE)
        page_obj = paginator.get_page(request.GET.get("page"))
        # What the visitor is actually looking at: narrowed by the facet, where
        # `total` stays the count across every type for the "All" tab.
        shown = paginator.count
        # One batched fetch per content type instead of one per result: the
        # excerpt and the type label both need the concrete subclass.
        ordered_pks = [page.pk for page in page_obj]
        by_pk = {page.pk: page for page in Page.objects.filter(pk__in=ordered_pks).specific()}
        results_page = [by_pk[pk] for pk in ordered_pks if pk in by_pk]

        for specific in results_page:
            items.append(
                {
                    "url": specific.url,
                    "title": specific.title,
                    "excerpt": getattr(specific, "description", "") or specific.search_description,
                    "label": page_type_label(specific),
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
        "all_url": _results_url(query),
        "prev_url": (
            _results_url(query, selected, page_obj.previous_page_number())
            if page_obj and page_obj.has_previous()
            else None
        ),
        "next_url": (
            _results_url(query, selected, page_obj.next_page_number())
            if page_obj and page_obj.has_next()
            else None
        ),
    }
    template = "cms/search/results.html"
    if request.htmx and not request.htmx.history_restore_request:
        template += "#htmx_results"
    return render(request, template, context)


def search_autocomplete(request: HttpRequest) -> HttpResponse:
    """Return an htmx partial of top title matches for the typeahead dropdown."""
    query = _clean_query(request)
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
