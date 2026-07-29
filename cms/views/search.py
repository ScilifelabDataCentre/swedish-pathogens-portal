"""Site-wide search: a faceted, paginated results page over Wagtail pages."""

from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from wagtail.models import Page
from wagtail.query import PageQuerySet

from cms.pages import (
    BasicPage,
    CataloguePage,
    DashboardPage,
    HighlightsAndEditorialsPage,
    NewsPage,
    OutbreakPage,
    PlpProjectPage,
    PortalDataPage,
    TopicPage,
)

# Ordered (model, facet key, human label). Listing/index/home pages are excluded.
SEARCH_TYPES: list[tuple[type[Page], str, str]] = [
    (NewsPage, "news", "News"),
    (HighlightsAndEditorialsPage, "articles", "Articles"),
    (TopicPage, "topics", "Topics"),
    (OutbreakPage, "outbreaks", "Outbreaks"),
    (DashboardPage, "dashboards", "Dashboards"),
    (PlpProjectPage, "plp", "PLP projects"),
    (CataloguePage, "catalogue", "Catalogue"),
    (PortalDataPage, "datasets", "Datasets"),
    (BasicPage, "pages", "Pages"),
]
SEARCH_MODELS: list[type[Page]] = [model for model, _, _ in SEARCH_TYPES]
_MODEL_BY_KEY: dict[str, type[Page]] = {key: model for model, key, _ in SEARCH_TYPES}
_LABEL_BY_MODEL: dict[type[Page], str] = {model: label for model, _, label in SEARCH_TYPES}
PAGE_SIZE = 12


def _base_queryset() -> PageQuerySet:
    """Return live, public pages restricted to the searchable page types."""
    return Page.objects.live().public().type(*SEARCH_MODELS)


def search(request: HttpRequest) -> HttpResponse:
    """Render the site-wide search results page, faceted by page type."""
    query = request.GET.get("q", "").strip()
    selected = request.GET.get("type", "").strip()
    facets: list[dict[str, object]] = []
    items: list[dict[str, object]] = []
    total = 0
    page_obj = None

    if query:
        for model, key, label in SEARCH_TYPES:
            count = model.objects.live().public().search(query, operator="and").count()
            if count:
                facets.append({"key": key, "label": label, "count": count})
        total = sum(int(facet["count"]) for facet in facets)

        if selected in _MODEL_BY_KEY:
            results = _MODEL_BY_KEY[selected].objects.live().public().search(query, operator="and")
        else:
            results = _base_queryset().search(query, operator="and")

        paginator = Paginator(results, PAGE_SIZE)
        page_obj = paginator.get_page(request.GET.get("page"))
        for page in page_obj:
            specific = page.specific
            items.append(
                {
                    "url": specific.url,
                    "title": specific.title,
                    "excerpt": getattr(specific, "description", "") or specific.search_description,
                    "label": _LABEL_BY_MODEL.get(type(specific), ""),
                }
            )

    context = {
        "page_heading": "Search",
        "query": query,
        "selected": selected,
        "facets": facets,
        "total": total,
        "items": items,
        "page_obj": page_obj,
    }
    return render(request, "cms/search/results.html", context)
