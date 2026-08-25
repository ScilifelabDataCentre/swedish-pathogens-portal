"""Service functions for the Available Data page.

Responsible for fetching per-category dataset counts from the EMBL-EBI search
API and assembling them into the page's template context.
"""

from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import structlog
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils.text import slugify

from cms.services.external_apis import cache_get_or_set, fetch_json

if TYPE_CHECKING:
    from cms.pages.available_data import AvailableDataPage

LOGGER = structlog.get_logger(__name__)

# EMBL-EBI EBIsearch REST API URL and query params
EBI_BASE_URL = "https://www.ebi.ac.uk/ebisearch/ws/rest"
EBI_SWEDEN_FILTER = '((country:"Sweden"))'
NOT_COVID_QUERY = "(tag:pathogen AND NOT tag:covid19)"
MATCH_ALL_QUERY = "(id:[* TO *])"
AVAIL_DATA_CACHE_TTL_SECONDS = 6 * 60 * 60  # 6 hours


def fetch_priority_pathogen_taxon_ids() -> list[str]:
    """Fetch the current list of priority-pathogen taxon ids from EBI.

    This returns a list of taxon ids, which are used in the "outbreaks" API queries for filtering.
    """
    # used if no results found, a blank list would be a match all query.
    failed_fetch_value = ["0"]
    cache_key = "available_data_priority_pathogen_taxon_ids"

    def compute() -> list[str] | None:
        """Use in cache_get_or_set to fetch the taxon ids if cache miss."""
        # max size=1000 per request. Current value is 198 hits, so quite a lot of wiggle room.
        params = {"query": "id:[* TO *]", "format": "JSON", "size": 1000, "fields": "TAXONOMY"}
        url = f"{EBI_BASE_URL}/priority_pathogens"
        data = fetch_json(url=url, params=params)
        if data is None:
            return None

        taxon_ids = []
        for entry in data.get("entries", []):
            taxonomy = entry.get("fields", {}).get("TAXONOMY")
            if taxonomy:
                taxon_ids.append(taxonomy[0])

        if not taxon_ids:
            LOGGER.warning("available_data.no_priority_taxon_ids_found", url=url)
            return None

        return taxon_ids

    result = cache_get_or_set(key=cache_key, timeout=AVAIL_DATA_CACHE_TTL_SECONDS, compute=compute)
    return result if result is not None else failed_fetch_value


def fetch_ebi_hit_count(index: str, query: str) -> int:
    """Return the hit count from EMBL-EBI's EBIsearch API for the given index/query.

    Returns 0 on any fetch/parse failure.
    """
    full_query = f"{query} {EBI_SWEDEN_FILTER}"
    # hash the slug first as query contains many taxon ids concatenated
    query_hash = hashlib.sha256(full_query.encode()).hexdigest()[:16]
    cache_key = f"available_data_ebi_{slugify(index)}_{query_hash}"

    def compute() -> int | None:
        """Use in cache_get_or_set to fetch the hit count if cache miss."""
        params = {"query": full_query, "size": 0, "format": "JSON", "facetcount": 0}
        url = f"{EBI_BASE_URL}/{index}"
        data = fetch_json(url=url, params=params)
        if data is None:
            return None
        try:
            return int(data.get("hitCount", 0))
        except (TypeError, ValueError) as e:
            LOGGER.error(
                "available_data.invalid_hit_count_response",
                url=url,
                error=str(e),
                exc_info=True,
            )
            return None

    result = cache_get_or_set(key=cache_key, timeout=AVAIL_DATA_CACHE_TTL_SECONDS, compute=compute)
    return result if result is not None else 0


def build_portal_url(main_path: str, db: str) -> str:
    """Build a Central Pathogens Portal query link, scoped to Sweden."""
    return f"https://www.pathogensportal.org/{main_path}?db={db}&query=(country:%22Sweden%22)&activeTab=Results"


def build_page_context() -> dict:
    """Fetch the EBI "hitcounts" needed to build the page context.

    Counts are fetched concurrently before assembling the context dict.
    """
    with ThreadPoolExecutor(max_workers=11) as executor:
        taxon_ids_future = executor.submit(fetch_priority_pathogen_taxon_ids)
        pathogen_futures = {
            "sequence": executor.submit(fetch_ebi_hit_count, "embl-pathogen", MATCH_ALL_QUERY),
            "analysis": executor.submit(fetch_ebi_hit_count, "sra-analysis", NOT_COVID_QUERY),
            "raw reads": executor.submit(fetch_ebi_hit_count, "sra-experiment", NOT_COVID_QUERY),
            "samples": executor.submit(fetch_ebi_hit_count, "sra-sample", NOT_COVID_QUERY),
            "assembly": executor.submit(fetch_ebi_hit_count, "genome_assembly", NOT_COVID_QUERY),
        }

        # we need the taxon ids query to finish before we can submit the "Outbreaks" queries
        taxon_ids = taxon_ids_future.result()
        priority_query = "TAXON:(" + " OR ".join(taxon_ids) + ")"
        priority_futures = {
            "priority pathogens": executor.submit(
                fetch_ebi_hit_count, "priority_pathogens", MATCH_ALL_QUERY
            ),
            "sequences": executor.submit(fetch_ebi_hit_count, "embl-pathogen", priority_query),
            "analysis": executor.submit(fetch_ebi_hit_count, "sra-analysis", priority_query),
            "raw reads": executor.submit(fetch_ebi_hit_count, "sra-experiment", priority_query),
            "samples": executor.submit(fetch_ebi_hit_count, "sra-sample", priority_query),
            "assembly": executor.submit(fetch_ebi_hit_count, "genome_assembly", priority_query),
        }

        pathogen_counts = {label: future.result() for label, future in pathogen_futures.items()}
        priority_counts = {label: future.result() for label, future in priority_futures.items()}

    pathogen_row_specs = [
        ("sequence", "embl-pathogen"),
        ("analysis", "sra-analysis"),
        ("raw reads", "sra-experiment"),
        ("samples", "sra-sample"),
        ("assembly", "genome_assembly"),
    ]
    pathogens_section = {
        "title": "Pathogen Sequences",
        "total_count": sum(pathogen_counts.values()),
        "total_url": build_portal_url(main_path="sequences", db="sequences"),
        "rows": [
            {
                "label": label,
                "count": pathogen_counts[label],
                "url": build_portal_url(main_path="sequences", db=db),
            }
            for label, db in pathogen_row_specs
        ],
    }

    priority_row_specs = [
        ("priority pathogens", "priority_pathogens"),
        ("sequences", "embl-pathogen"),
        ("analysis", "sra-analysis"),
        ("raw reads", "sra-experiment"),
        ("samples", "sra-sample"),
        ("assembly", "genome_assembly"),
    ]
    outbreaks_section = {
        "title": "Outbreaks",
        "total_count": sum(priority_counts.values()),
        "total_url": build_portal_url(main_path="priority-pathogens", db="priorityPathogens"),
        "rows": [
            {
                "label": label,
                "count": priority_counts[label],
                "url": build_portal_url(main_path="priority-pathogens", db=db),
            }
            for label, db in priority_row_specs
        ],
    }

    return {
        "pathogens_sequences": pathogens_section,
        "outbreaks": outbreaks_section,
    }


def render_available_data_partial(request: HttpRequest, page: AvailableDataPage) -> HttpResponse:
    """Render the available data counts partial template for an HTMX request."""
    return render(
        request=request,
        template_name="cms/pages/available_data/partials/available_data_counts.html",
        context=build_page_context(),
    )
