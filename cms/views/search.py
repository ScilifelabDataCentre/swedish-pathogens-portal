"""Site-wide search: a faceted, paginated results page over Wagtail pages."""

from collections import Counter
from collections.abc import Sequence

from django.contrib.contenttypes.models import ContentType
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils.http import urlencode
from django.views.decorators.vary import vary_on_headers
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


def _facet(model: type[Page]) -> tuple[str, str]:
    """Return the ``(key, label)`` of the facet a page type falls under, or blanks.

    Matched with ``issubclass`` rather than an exact type lookup so that
    subclasses reached through multi-table inheritance — a ``DrrDatasetPage`` is
    a ``DashboardPage`` — are labelled instead of falling through to a blank
    badge.
    """
    for models, key, label in SEARCH_TYPES:
        if issubclass(model, models):
            return key, label
    return "", ""


def page_type_label(page: Page) -> str:
    """Return the facet label describing what kind of page this is."""
    return _facet(type(page))[1]


def _matches(query: str) -> list[tuple[int, str]]:
    """Return ``(page pk, facet key)`` for every page matching the query, best first.

    The last word may still be half-typed, and no single index handles that.
    ``search()`` uses a stemmed index ("monitoring" is stored as "monitor"), so
    it relates word forms but only matches whole words; a prefix of it would stop
    matching once typing runs past the stem ("monitorin"). ``autocomplete()``
    matches the last word as an unstemmed prefix, over the same text (every page
    model pairs its ``SearchField``s with ``AutocompleteField``s), but needs the
    earlier words spelled exactly. So, every word required in each pass:

    1. ``search(query)``: all words whole and stemmed; "vaccines" finds "vaccine".
    2. ``search(earlier words)`` narrowed by ``autocomplete(last word)``: completed
       words stemmed, the last a prefix; "antibiotics res" finds "Antibiotic
       resistance".
    3. ``autocomplete(query)``: all words as written, the last a prefix. Keeps
       earlier words the stemmed index drops, like "of" in "of resis".

    Results follow that order. Loading just the pk and content type of every
    match lets one pass serve the facet counts and the page, instead of a
    search per facet.
    """
    base = _base_queryset().only("id", "content_type")
    *earlier, last = query.split()
    passes = [base.search(query, operator="and")]
    if earlier:
        completed = [page.pk for page in base.search(" ".join(earlier), operator="and")]
        passes.append(base.filter(pk__in=completed).autocomplete(last, operator="and"))
    passes.append(base.autocomplete(query, operator="and"))

    found: dict[int, str] = {}
    for results in passes:
        for page in results:
            if page.pk not in found:
                model = ContentType.objects.get_for_id(page.content_type_id).model_class()
                found[page.pk] = _facet(model)[0]
    return list(found.items())


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
        matches = _matches(query)
        counts = Counter(key for _, key in matches)
        facets = [
            {"key": key, "label": label, "count": counts[key], "url": _results_url(query, key)}
            for _, key, label in SEARCH_TYPES
            if counts[key]
        ]
        total = len(matches)

        paginator = Paginator(
            [pk for pk, key in matches if key == selected or not selected], PAGE_SIZE
        )
        page_obj = paginator.get_page(request.GET.get("page"))
        # What the visitor is actually looking at: narrowed by the facet, where
        # `total` stays the count across every type for the "All" tab.
        shown = paginator.count
        # One batched fetch per content type instead of one per result: the
        # excerpt and the type label both need the concrete subclass.
        ordered_pks = list(page_obj)
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
        # Titles only: the autocomplete index now holds body text too (see _matches).
        matches = _base_queryset().autocomplete(query, fields=["title"])[:AUTOCOMPLETE_LIMIT]
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
