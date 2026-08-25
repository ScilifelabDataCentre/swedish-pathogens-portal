"""Service functions for the Publications page.

Responsible for:
(1) resolving the active (selected) pathogen.
(2) fetching and parsing publications from Europe PMC.
(3) rendering the publications list partial template for HTMX requests.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.http import urlencode
from django.utils.text import slugify

from cms.services.external_apis import cache_get_or_set, fetch_json

if TYPE_CHECKING:
    from cms.pages.publications import PublicationsPage

LOGGER = structlog.get_logger(__name__)

# EuroPMC base URLs for publications page.
EUROPE_PMC_API_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
EUROPE_PMC_WEB_BASE_URL = "https://europepmc.org/search"
PUBLICATIONS_CACHE_TTL_SECONDS = 30 * 60


@dataclass
class Pathogen:
    """A pathogen that can be used to search for publications in Europe PMC.

    Attributes:
        name (str): The name of the pathogen.
        search_terms (list[str]): A list of search terms to find in a publication's abstract.
    """

    name: str
    search_terms: list[str]


@dataclass
class Publication:
    """A publication entry to be displayed on the publications page.

    Attributes:
        title (str): The title of the publication.
        authors (str): The authors of the publication.
        journal (str): The journal in which the publication was published.
        doi (str): The DOI of the publication.
        url (str | None): The URL to access the publication if available, otherwise None.
    """

    title: str
    authors: str
    journal: str
    doi: str
    url: str | None

    @classmethod
    def from_europe_pmc_result(cls, result: dict[str, Any]) -> Publication:
        """Build a Publication from one raw Europe PMC "result" entry.

        Rather than raising on missing fields, provides default values for missing data.
        """
        journal_info = result.get("journalInfo") or {}  # handles case where journalInfo = null/None
        journal = (journal_info.get("journal") or {}).get("title", "journal unknown")
        doi = result.get("doi", "doi unknown")

        if doi != "doi unknown":
            url = f"https://doi.org/{doi}"
        else:
            # another possible source for the url
            full_text_urls = (result.get("fullTextUrlList") or {}).get("fullTextUrl") or []
            url = full_text_urls[0].get("url") if full_text_urls else None

        return cls(
            title=result.get("title", "title unknown"),
            authors=result.get("authorString", "authors unknown"),
            journal=journal,
            doi=doi,
            url=url,
        )


def resolve_active_pathogen(page: PublicationsPage, request: HttpRequest) -> Pathogen | None:
    """Resolve which pathogen is active (selected) from the HTTP request's query parameters.

    If no pathogen provided (e.g. initial page load), return the first pathogen.
    Otherwise return the matching pathogen or None.
    """
    user_pathogen = request.GET.get("pathogen", "").strip().replace("\n", "").replace("\r", "")

    if not user_pathogen:
        return page.pathogens[0] if page.pathogens else None

    for pathogen in page.pathogens:
        if pathogen.name == user_pathogen:
            return pathogen

    available_pathogens = [p.name for p in page.pathogens]
    LOGGER.warning(
        "Pathogen %r not found among this page's configured pathogens. configured pathogens: %s",
        user_pathogen,
        available_pathogens,
    )
    return None


def _build_abstract_query(pathogen: Pathogen) -> str:
    """Build an Europe PMC "ABSTRACT:(...)" fragment OR-ing together search terms."""
    terms = " OR ".join(f'"{term}"' for term in pathogen.search_terms)
    return f"ABSTRACT:({terms})"


def fetch_pathogen_publications(pathogen: Pathogen) -> list[Publication]:
    """Fetch recent Sweden-affiliated publications for a pathogen from Europe PMC.

    Results cached according to `PUBLICATIONS_CACHE_TTL_SECONDS`.
    Returns an empty list on any fetch/parse failure.
    """
    now = timezone.now()
    past_year = f"{now.year - 1}-{now.month:02d} TO {now.year}-{now.month:02d}"
    query_string = f'{_build_abstract_query(pathogen)} AND AFF:"Sweden" AND PUB_YEAR:[{past_year}]'
    cache_key = slugify(f"publications_{pathogen.name}_{query_string}")

    def compute() -> list[Publication] | None:
        """Use in cache_get_or_set to fetch and parse publications if cache miss."""
        data = fetch_json(
            url=EUROPE_PMC_API_URL,
            params={
                "sortBy": "FIRST_PDATE_D desc",
                "resultType": "core",
                "format": "json",
                "pageSize": 10,
                "query": query_string,
            },
        )
        if data is None:
            return None

        publications = []
        for pub in data.get("resultList", {}).get("result", []):
            try:
                publications.append(Publication.from_europe_pmc_result(pub))
            except (AttributeError, TypeError) as e:
                LOGGER.error(
                    "publications.parse_error",
                    pathogen=pathogen.name,
                    error=str(e),
                    publication=pub,
                    exc_info=True,
                )
        return publications or None

    publications = cache_get_or_set(
        key=cache_key, timeout=PUBLICATIONS_CACHE_TTL_SECONDS, compute=compute
    )
    return publications if publications is not None else []


def render_publications_partial(request: HttpRequest, page: PublicationsPage) -> HttpResponse:
    """Render the publications list partial template for an HTMX request."""
    active_pathogen = resolve_active_pathogen(page=page, request=request)
    if not active_pathogen:
        context = {
            "active_pathogen": None,
            "publications": [],
            "europe_pmc_full_list": None,
        }
        return render(
            request=request,
            template_name="cms/pages/publications/partials/publications_list.html",
            context=context,
        )

    query_string = f'{_build_abstract_query(active_pathogen)} AND AFF:"Sweden"'
    web_url = f"{EUROPE_PMC_WEB_BASE_URL}?{urlencode({'query': query_string})}"
    context = {
        "active_pathogen": active_pathogen.name,
        "publications": fetch_pathogen_publications(active_pathogen),
        "europe_pmc_full_list": web_url,
    }
    return render(
        request=request,
        template_name="cms/pages/publications/partials/publications_list.html",
        context=context,
    )
