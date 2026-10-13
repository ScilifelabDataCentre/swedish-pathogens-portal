"""Client for the ENA (European Nucleotide Archive) Portal API.

Fetches Swedish pathogen records from ENA for the Genomic data page. Nothing is
stored locally beyond a short-lived cache: record counts and one page of records
at a time are requested live, since some pathogens (e.g. SARS-CoV-2) have far
too many Swedish records to load wholesale the way MetaboLights studies are.

API documentation:
- https://ena-docs.readthedocs.io/en/latest/retrieval/programmatic-access.html
- https://www.ebi.ac.uk/ena/portal/api/doc
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import structlog

from cms.services.api_client import fetch_json
from cms.services.caching import cache_get_or_set

LOGGER = structlog.get_logger(__name__)

ENA_PORTAL_API_URL = "https://www.ebi.ac.uk/ena/portal/api"
ENA_BROWSER_VIEW_URL = "https://www.ebi.ac.uk/ena/browser/view"

# INSDC country values are "Country" or "Country: region", so match on a prefix.
SWEDEN_QUERY = 'country="Sweden*"'

ENA_COUNT_CACHE_TTL_SECONDS = 6 * 60 * 60  # 6 hours
ENA_RECORDS_CACHE_TTL_SECONDS = 60 * 60  # 1 hour


@dataclass(frozen=True)
class RecordType:
    """An ENA result type that can be listed on the Genomic data page.

    Attributes:
        result: The ENA Portal API ``result`` name, e.g. "read_run".
        label: Human-readable name shown on the page.
        accession_field: The field holding the record's primary accession.
        columns: ``(field, column header)`` pairs shown after the accession column.
    """

    result: str
    label: str
    accession_field: str
    columns: tuple[tuple[str, str], ...]

    @property
    def fields(self) -> list[str]:
        """Return every ENA field requested for this record type, accession first."""
        return [self.accession_field, *(field for field, _ in self.columns)]


# Displayed in this order. To list another ENA result type, add an entry here -
# the result type must support `tax_tree` and `country` searches.
RECORD_TYPES: dict[str, RecordType] = {
    "read_run": RecordType(
        result="read_run",
        label="Raw reads",
        accession_field="run_accession",
        columns=(
            ("scientific_name", "Organism"),
            ("collection_date", "Collection date"),
            ("country", "Location"),
            ("instrument_platform", "Platform"),
            ("library_strategy", "Library strategy"),
            ("first_public", "First public"),
        ),
    ),
    "sample": RecordType(
        result="sample",
        label="Samples",
        accession_field="sample_accession",
        columns=(
            ("scientific_name", "Organism"),
            ("collection_date", "Collection date"),
            ("country", "Location"),
            ("host", "Host"),
            ("first_public", "First public"),
        ),
    ),
    "sequence": RecordType(
        result="sequence",
        label="Sequences",
        accession_field="accession",
        columns=(
            ("description", "Description"),
            ("scientific_name", "Organism"),
            ("collection_date", "Collection date"),
            ("country", "Location"),
            ("first_public", "First public"),
        ),
    ),
}

DEFAULT_RECORD_TYPE = next(iter(RECORD_TYPES))


@dataclass(frozen=True)
class EnaRecord:
    """One ENA record, flattened for display in a table row.

    Attributes:
        accession: The record's primary accession.
        url: Link to the record in the ENA browser.
        cells: Display values in the same order as ``RecordType.columns``.
    """

    accession: str
    url: str
    cells: tuple[str, ...]

    @classmethod
    def from_ena_result(cls, result: dict[str, Any], record_type: RecordType) -> EnaRecord | None:
        """Build a record from one raw ENA search result, or None if it has no accession."""
        accession = str(result.get(record_type.accession_field) or "").strip()
        if not accession:
            return None
        cells = tuple(str(result.get(field) or "").strip() for field, _ in record_type.columns)
        return cls(accession=accession, url=f"{ENA_BROWSER_VIEW_URL}/{accession}", cells=cells)


def build_query(taxon_ids: Iterable[int]) -> str:
    """Build an ENA query for records from Sweden within any of the given taxa.

    ``tax_tree`` includes all descendants of a taxon, so a species taxon also
    matches its strains and lineages. Taxon ids are cast to int, as they are
    interpolated into the query string.
    """
    ids = sorted({int(taxon_id) for taxon_id in taxon_ids})
    if not ids:
        raise ValueError("At least one taxon id is required.")
    taxa = " OR ".join(f"tax_tree({taxon_id})" for taxon_id in ids)
    return f"({taxa}) AND {SWEDEN_QUERY}"


def _cache_key(prefix: str, *parts: object) -> str:
    """Build a short cache key, hashing the parts as queries can be long."""
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:16]
    return f"ena_{prefix}_{digest}"


def _parse_count(data: object) -> int | None:
    """Parse the count endpoint's body, which is a bare number (or ``{"count": n}``)."""
    if isinstance(data, dict):
        data = data.get("count")
    if isinstance(data, bool) or not isinstance(data, int | str):
        return None
    try:
        count = int(data)
    except ValueError:
        return None
    return count if count >= 0 else None


def fetch_count(record_type: RecordType, query: str) -> int | None:
    """Return how many records of ``record_type`` match ``query``, or None on failure."""

    def compute() -> int | None:
        """Use in cache_get_or_set to fetch the count if cache miss."""
        data = fetch_json(
            url=f"{ENA_PORTAL_API_URL}/count",
            params={"result": record_type.result, "query": query},
        )
        if data is None:
            return None
        count = _parse_count(data)
        if count is None:
            LOGGER.error("ena.invalid_count_response", result=record_type.result, body=data)
        return count

    return cache_get_or_set(
        key=_cache_key("count", record_type.result, query),
        timeout=ENA_COUNT_CACHE_TTL_SECONDS,
        compute=compute,
    )


def fetch_records(
    record_type: RecordType, query: str, *, offset: int, limit: int
) -> list[EnaRecord] | None:
    """Return one page of records matching ``query``, or None on failure."""

    def compute() -> list[EnaRecord] | None:
        """Use in cache_get_or_set to fetch and parse records if cache miss."""
        data = fetch_json(
            url=f"{ENA_PORTAL_API_URL}/search",
            params={
                "result": record_type.result,
                "query": query,
                "fields": ",".join(record_type.fields),
                "format": "json",
                "limit": limit,
                "offset": offset,
            },
        )
        if not isinstance(data, list):
            if data is not None:
                LOGGER.error("ena.invalid_search_response", result=record_type.result)
            return None

        records = []
        for result in data:
            if not isinstance(result, dict):
                continue
            record = EnaRecord.from_ena_result(result, record_type)
            if record is not None:
                records.append(record)
        return records

    return cache_get_or_set(
        key=_cache_key("records", record_type.result, query, offset, limit),
        timeout=ENA_RECORDS_CACHE_TTL_SECONDS,
        compute=compute,
    )


def build_download_url(record_type: RecordType, query: str) -> str:
    """Return an ENA Portal API link that downloads every matching record as TSV.

    The file is served directly by ENA, so no data passes through this portal.
    ``limit=0`` asks ENA for all records rather than its default first page.
    """
    params = {
        "result": record_type.result,
        "query": query,
        "fields": ",".join(record_type.fields),
        "format": "tsv",
        "limit": 0,
        "download": "true",
    }
    return f"{ENA_PORTAL_API_URL}/search?{urlencode(params)}"
