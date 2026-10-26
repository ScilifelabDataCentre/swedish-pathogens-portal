"""Client for EBI Search's ENA pathogen indexes, used by the Genomic data page.

EBI Search indexes ENA's records and is what the central Pathogens Portal
(https://www.pathogensportal.org/sequences) is built on. Unlike the ENA Portal
API it supports faceting, offset paging and sorting, so the page can request one
page of results at a time with facet counts for the whole result set.

API documentation: https://www.ebi.ac.uk/ebisearch/documentation/rest-api
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

import structlog

from cms.services.api_client import fetch_json
from cms.services.caching import cache_get_or_set

LOGGER = structlog.get_logger(__name__)

EBI_SEARCH_URL = "https://www.ebi.ac.uk/ebisearch/ws/rest"
ENA_BROWSER_VIEW_URL = "https://www.ebi.ac.uk/ena/browser/view"

# Every query is limited to pathogen records from Sweden. `country:"Sweden"` also
# matches values such as "Sweden, Stockholm"; COVID-19 records are included.
BASE_QUERY = '(country:"Sweden") AND tag:pathogen'

SEARCH_CACHE_TTL_SECONDS = 30 * 60  # 30 minutes
COUNT_CACHE_TTL_SECONDS = 6 * 60 * 60  # 6 hours
# EBI Search can take several seconds, e.g. for a prefix search on a large index,
# so allow longer than the shared API client's default of 10 seconds.
REQUEST_TIMEOUT_SECONDS = 20

# EBI Search returns at most 100 entries per request.
MAX_PAGE_SIZE = 100
# Values returned per facet; the page shows a few and hides the rest behind "Show more".
FACET_VALUE_COUNT = 20
# Most words accepted from the search box.
MAX_SEARCH_TERMS = 10

# Facets shown in the sidebar, in this order, when the data type's index has them.
FACET_FIELDS: tuple[str, ...] = (
    "classification",
    "TAXON",
    "collection_date",
    "first_public_date",
    "host",
    "region",
    "instrument_platform",
    "library_strategy",
    "analysis_type",
)


@dataclass(frozen=True)
class Column:
    """A table column, backed by one EBI Search field.

    Attributes:
        field: The EBI Search field name.
        label: Column header.
        sortable: Whether EBI Search can sort this index on the field.
        kind: "text", "date" (YYYYMMDD shown as YYYY-MM-DD) or "taxon" (linked to ENA).
    """

    field: str
    label: str
    sortable: bool = False
    kind: str = "text"


@dataclass(frozen=True)
class DataType:
    """A kind of ENA record, backed by one EBI Search index (domain).

    Attributes:
        key: Short name used in URLs, e.g. "raw-reads".
        domain: The EBI Search domain, e.g. "sra-experiment".
        label: Name shown on the page.
        columns: Columns shown after the accession column.
    """

    key: str
    domain: str
    label: str
    columns: tuple[Column, ...]

    @property
    def fields(self) -> list[str]:
        """Return the EBI Search fields requested for this data type."""
        return ["acc", *(column.field for column in self.columns)]

    @property
    def sortable_fields(self) -> set[str]:
        """Return the fields results can be sorted on (the accession always can)."""
        return {"acc", *(column.field for column in self.columns if column.sortable)}


ORGANISM = Column("scientific_name", "Organism")
COLLECTION_DATE = Column("collection_date", "Collection date", sortable=True, kind="date")
FIRST_PUBLIC = Column("first_public_date", "First public", sortable=True, kind="date")

# Displayed as tabs in this order, matching the central portal. Sortable flags
# follow each index's field settings in EBI Search.
DATA_TYPES: dict[str, DataType] = {
    data_type.key: data_type
    for data_type in (
        DataType(
            key="sequences",
            domain="embl-pathogen",
            label="Sequences",
            columns=(
                ORGANISM,
                Column("TAXON", "Taxon ID", sortable=True, kind="taxon"),
                Column("description", "Description"),
                COLLECTION_DATE,
                Column("host", "Host", sortable=True),
                Column("strain", "Strain", sortable=True),
            ),
        ),
        DataType(
            key="analyses",
            domain="sra-analysis",
            label="Analyses",
            columns=(
                ORGANISM,
                Column("TAXON", "Taxon ID", kind="taxon"),
                Column("analysis_type", "Analysis type", sortable=True),
                COLLECTION_DATE,
                Column("host", "Host"),
                Column("center_name", "Centre"),
            ),
        ),
        DataType(
            key="raw-reads",
            domain="sra-experiment",
            label="Raw reads",
            columns=(
                ORGANISM,
                Column("TAXON", "Taxon ID", kind="taxon"),
                COLLECTION_DATE,
                Column("host", "Host"),
                Column("instrument_platform", "Platform", sortable=True),
                Column("library_strategy", "Library strategy", sortable=True),
                FIRST_PUBLIC,
            ),
        ),
        DataType(
            key="samples",
            domain="sra-sample",
            label="Samples",
            columns=(
                ORGANISM,
                Column("TAXON", "Taxon ID", kind="taxon"),
                COLLECTION_DATE,
                Column("host", "Host"),
                Column("center_name", "Centre"),
                FIRST_PUBLIC,
            ),
        ),
        DataType(
            key="assemblies",
            domain="genome_assembly",
            label="Assemblies",
            columns=(
                ORGANISM,
                Column("TAXON", "Taxon ID", kind="taxon"),
                Column("description", "Description"),
                Column("assembly_level", "Assembly level", sortable=True),
                COLLECTION_DATE,
                Column("host", "Host", sortable=True),
            ),
        ),
    )
}

DEFAULT_DATA_TYPE = next(iter(DATA_TYPES))


@dataclass(frozen=True)
class Cell:
    """One table cell: its display value and an optional link."""

    value: str
    url: str | None = None


@dataclass(frozen=True)
class Record:
    """One search result, flattened for display in a table row."""

    accession: str
    url: str
    cells: tuple[Cell, ...]


@dataclass(frozen=True)
class FacetValue:
    """One value of a facet, with how many results have it."""

    value: str
    label: str
    count: int
    selected: bool = False


@dataclass(frozen=True)
class Facet:
    """A facet (e.g. Classification) and its values."""

    field: str
    label: str
    values: tuple[FacetValue, ...]


@dataclass(frozen=True)
class SearchResult:
    """One page of results, with the total and facets for the whole result set."""

    total: int
    records: tuple[Record, ...]
    facets: tuple[Facet, ...] = field(default=())


def taxon_url(taxon_id: str | int) -> str:
    """Return the ENA browser page for an NCBI taxonomy id."""
    return f"{ENA_BROWSER_VIEW_URL}/Taxon:{int(taxon_id)}"


# Query operators typed in the search box are not passed on as operators: AND and OR
# are dropped (every remaining word must match) and NOT excludes the word after it.
IGNORED_OPERATORS = frozenset({"AND", "OR", "TO"})
# EBI Search rejects wildcards on shorter words, so they must match in full.
MIN_PREFIX_LENGTH = 3


def _search_term(word: str) -> str:
    """Return the query term for one search word, matching it as a prefix where possible.

    A trailing ``*`` makes "Escherichi" match "Escherichia" and "PQ0642" match
    accessions such as "PQ064201". EBI Search rejects wildcards on words shorter
    than ``MIN_PREFIX_LENGTH`` and on words containing "-" or ".", which are
    therefore matched as typed.
    """
    if len(word) >= MIN_PREFIX_LENGTH and "-" not in word and "." not in word:
        return f"{word}*"
    return word


def build_query(text: str = "") -> str:
    """Return the EBI Search query: Swedish pathogen records, plus any search words.

    Search words are reduced to letters, digits, ".", "_" and "-", so user input
    can't make the query invalid. Every word must match (as a prefix, see
    ``_search_term``), except words after NOT or starting with "-", which must
    not match. AND, OR and TO are ignored, in any case.
    """
    included: list[str] = []
    excluded: list[str] = []
    exclude_next = False
    for raw_word in re.findall(r"[\w.\-]+", text):
        word = raw_word.lstrip("-")
        if not word:
            continue
        if word.upper() == "NOT":
            exclude_next = True
            continue
        if word.upper() in IGNORED_OPERATORS:
            continue
        exclude = exclude_next or raw_word.startswith("-")
        (excluded if exclude else included).append(_search_term(word))
        exclude_next = False
        if len(included) + len(excluded) == MAX_SEARCH_TERMS:
            break

    query = BASE_QUERY
    if included:
        query += f" AND ({' AND '.join(included)})"
    for term in excluded:
        query += f" AND NOT {term}"
    return query


def is_valid_facet_value(value: str) -> bool:
    """Return whether a facet value can be sent to EBI Search.

    Selected facets are sent comma-separated, and EBI Search rejects or misreads
    values containing commas, so those can't be offered as filters.
    """
    return bool(value) and "," not in value and len(value) <= 200


def _facets_param(selected: dict[str, list[str]]) -> str:
    """Build the ``facets`` parameter: ``field:value`` pairs, comma-separated.

    EBI Search ORs values of the same facet and ANDs different facets.
    """
    return ",".join(
        f"{facet_field}:{value}"
        for facet_field, values in selected.items()
        if facet_field in FACET_FIELDS
        for value in values
        if is_valid_facet_value(value)
    )


def _cache_key(prefix: str, params: dict[str, Any]) -> str:
    """Build a short cache key from a request's parameters."""
    digest = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()[:20]
    return f"ebi_search_{prefix}_{digest}"


def _format_value(values: object, kind: str) -> str:
    """Join a field's values for display, formatting YYYYMMDD dates as YYYY-MM-DD."""
    if not isinstance(values, list):
        values = [values] if values else []
    texts = [str(v).strip() for v in values if v not in (None, "")]
    if kind == "date":
        texts = [
            f"{t[:4]}-{t[4:6]}-{t[6:]}" if len(t) == 8 and t.isascii() and t.isdigit() else t
            for t in texts
        ]
    return "; ".join(dict.fromkeys(texts))


def _cell(column: Column, values: object) -> Cell:
    """Build the cell for ``column``, linking a single taxon id to its ENA page."""
    text = _format_value(values, column.kind)
    if column.kind == "taxon" and text.isascii() and text.isdigit():
        return Cell(value=text, url=taxon_url(text))
    return Cell(value=text)


def _parse_record(entry: dict[str, Any], data_type: DataType) -> Record | None:
    """Build a record from one EBI Search entry, or None if it has no accession."""
    fields = entry.get("fields") or {}
    accession = _format_value(fields.get("acc") or entry.get("acc") or entry.get("id"), "text")
    accession = accession.split(";")[0].strip()
    if not accession:
        return None
    cells = tuple(_cell(column, fields.get(column.field)) for column in data_type.columns)
    return Record(accession=accession, url=f"{ENA_BROWSER_VIEW_URL}/{accession}", cells=cells)


def _parse_facets(raw_facets: object, selected: dict[str, list[str]]) -> tuple[Facet, ...]:
    """Build the sidebar facets, in ``FACET_FIELDS`` order.

    Selected values are always included, even when no longer among the returned
    values (e.g. after another filter removed them), so they can be unticked.
    """
    by_field = {
        facet.get("id"): facet
        for facet in (raw_facets if isinstance(raw_facets, list) else [])
        if isinstance(facet, dict)
    }
    facets = []
    for facet_field in FACET_FIELDS:
        raw = by_field.get(facet_field)
        chosen = [v for v in selected.get(facet_field, []) if is_valid_facet_value(v)]
        if raw is None and not chosen:
            continue
        values = []
        seen = set()
        for raw_value in (raw or {}).get("facetValues") or []:
            value = str(raw_value.get("value") or "").strip()
            if not is_valid_facet_value(value):
                continue
            try:
                count = int(raw_value.get("count") or 0)
            except TypeError, ValueError:
                count = 0
            label = str(raw_value.get("label") or value).strip()
            values.append(FacetValue(value, label, count, selected=value in chosen))
            seen.add(value)
        values.extend(FacetValue(v, v, 0, selected=True) for v in chosen if v not in seen)
        if values:
            label = str((raw or {}).get("label") or facet_field.replace("_", " ").capitalize())
            facets.append(Facet(field=facet_field, label=label, values=tuple(values)))
    return tuple(facets)


def search(
    data_type: DataType,
    *,
    text: str = "",
    selected_facets: dict[str, list[str]] | None = None,
    start: int = 0,
    size: int = 25,
    sort: tuple[str, bool] | None = None,
) -> SearchResult | None:
    """Return one page of results for ``data_type``, or None if EBI Search failed.

    Args:
        data_type: Which kind of record (EBI Search domain) to search.
        text: Words from the search box, see ``build_query``.
        selected_facets: Selected facet values by facet field.
        start: Zero-based index of the first result to return.
        size: Results per page, at most ``MAX_PAGE_SIZE``.
        sort: ``(field, descending)``, ignored unless the field is sortable.
    """
    selected = selected_facets or {}
    params: dict[str, Any] = {
        "query": build_query(text),
        "format": "json",
        "fields": ",".join(data_type.fields),
        "size": max(1, min(size, MAX_PAGE_SIZE)),
        "start": max(0, start),
        "facetcount": FACET_VALUE_COUNT,
    }
    facets_param = _facets_param(selected)
    if facets_param:
        params["facets"] = facets_param
    if sort is not None and sort[0] in data_type.sortable_fields:
        params["sort"] = f"{sort[0]}:{'descending' if sort[1] else 'ascending'}"

    def compute() -> SearchResult | None:
        """Use in cache_get_or_set to run the search if cache miss."""
        data = fetch_json(
            url=f"{EBI_SEARCH_URL}/{data_type.domain}",
            params=params,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if not isinstance(data, dict) or "hitCount" not in data:
            if data is not None:
                LOGGER.error("ebi_search.invalid_response", domain=data_type.domain)
            return None
        try:
            total = int(data["hitCount"])
        except TypeError, ValueError:
            LOGGER.error("ebi_search.invalid_hit_count", domain=data_type.domain)
            return None
        entries = data.get("entries") if isinstance(data.get("entries"), list) else []
        records = (_parse_record(entry, data_type) for entry in entries if isinstance(entry, dict))
        return SearchResult(
            total=total,
            records=tuple(record for record in records if record is not None),
            facets=_parse_facets(data.get("facets"), selected),
        )

    return cache_get_or_set(
        key=_cache_key(f"search_{data_type.domain}", params),
        timeout=SEARCH_CACHE_TTL_SECONDS,
        compute=compute,
    )


def fetch_count(data_type: DataType, text: str = "") -> int | None:
    """Return how many records of ``data_type`` match the search words, or None on failure."""
    params = {"query": build_query(text), "format": "json", "size": 0, "facetcount": 0}

    def compute() -> int | None:
        """Use in cache_get_or_set to fetch the count if cache miss."""
        data = fetch_json(
            url=f"{EBI_SEARCH_URL}/{data_type.domain}",
            params=params,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if not isinstance(data, dict):
            return None
        try:
            return int(data["hitCount"])
        except KeyError, TypeError, ValueError:
            LOGGER.error("ebi_search.invalid_hit_count", domain=data_type.domain)
            return None

    return cache_get_or_set(
        key=_cache_key(f"count_{data_type.domain}", params),
        timeout=COUNT_CACHE_TTL_SECONDS,
        compute=compute,
    )
