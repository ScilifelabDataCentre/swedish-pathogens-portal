"""Client for the ENA (European Nucleotide Archive) Portal API.

Fetches Swedish pathogen records from ENA for the Genomic data page. Nothing is
stored locally beyond a short-lived cache: record counts and up to
MAX_BROWSABLE_RECORDS records per pathogen and record type are requested live,
and the full set is only offered as a TSV download served by ENA itself.

API documentation:
- https://ena-docs.readthedocs.io/en/latest/retrieval/programmatic-access.html
- https://www.ebi.ac.uk/ena/portal/api/doc
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import structlog

from cms.services.api_client import fetch_json, fetch_text
from cms.services.caching import cache_get_or_set

LOGGER = structlog.get_logger(__name__)

ENA_PORTAL_API_URL = "https://www.ebi.ac.uk/ena/portal/api"
ENA_BROWSER_VIEW_URL = "https://www.ebi.ac.uk/ena/browser/view"

# INSDC country values are "Country" or "Country: region", so match on a prefix.
SWEDEN_QUERY = 'country="Sweden*"'

ENA_COUNT_CACHE_TTL_SECONDS = 6 * 60 * 60  # 6 hours
ENA_RECORDS_CACHE_TTL_SECONDS = 60 * 60  # 1 hour

# The Portal API has no offset parameter ("Unsupported param offset"), so a listing
# can't be fetched one page at a time. Instead the first MAX_BROWSABLE_RECORDS
# records are fetched in one request, cached and paged locally; anything beyond
# that is only available through the full TSV download.
MAX_BROWSABLE_RECORDS = 5_000


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
            ("tax_id", "Taxon ID"),
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
            ("tax_id", "Taxon ID"),
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
            ("tax_id", "Taxon ID"),
            ("collection_date", "Collection date"),
            ("country", "Location"),
            ("first_public", "First public"),
        ),
    ),
}

DEFAULT_RECORD_TYPE = next(iter(RECORD_TYPES))


# Columns whose values link out to another ENA browser page, by field name.
LINKED_FIELDS = {"tax_id"}


@dataclass(frozen=True)
class Cell:
    """One table cell: its display value and an optional link."""

    value: str
    url: str | None = None


def _cell(field: str, value: str) -> Cell:
    """Build the cell for ``field``, linking taxon ids to their ENA taxon page."""
    if field in LINKED_FIELDS and value.isascii() and value.isdigit():
        return Cell(value=value, url=taxon_url(int(value)))
    return Cell(value=value)


@dataclass(frozen=True)
class EnaRecord:
    """One ENA record, flattened for display in a table row.

    Attributes:
        accession: The record's primary accession.
        url: Link to the record in the ENA browser.
        cells: Cells in the same order as ``RecordType.columns``.
    """

    accession: str
    url: str
    cells: tuple[Cell, ...]

    @classmethod
    def from_ena_result(cls, result: dict[str, Any], record_type: RecordType) -> EnaRecord | None:
        """Build a record from one raw ENA search result, or None if it has no accession."""
        accession = str(result.get(record_type.accession_field) or "").strip()
        if not accession:
            return None
        cells = tuple(
            _cell(field, str(result.get(field) or "").strip()) for field, _ in record_type.columns
        )
        return cls(accession=accession, url=f"{ENA_BROWSER_VIEW_URL}/{accession}", cells=cells)


def _value_position(record_type: RecordType, field: str) -> int | None | bool:
    """Return where ``field``'s value lives in a record of ``record_type``.

    None means the accession, an int is the index into ``EnaRecord.cells`` and
    False means ``field`` isn't shown for this record type.
    """
    if field == record_type.accession_field:
        return None
    for index, (column_field, _) in enumerate(record_type.columns):
        if column_field == field:
            return index
    return False


def _value_at(record: EnaRecord, position: int | None) -> str:
    """Return the record's value at a position from ``_value_position``."""
    return record.accession if position is None else record.cells[position].value


def filter_records(
    records: list[EnaRecord], record_type: RecordType, filters: dict[str, str]
) -> list[EnaRecord]:
    """Return the records whose columns contain every filter value (case-insensitive).

    ``filters`` maps an ENA field name (the accession field or a column field) to
    the text it must contain. Unknown fields and blank values are ignored.
    """
    checks: list[tuple[int | None, str]] = []
    for field, value in filters.items():
        needle = value.strip().casefold()
        position = _value_position(record_type, field)
        if needle and position is not False:
            checks.append((position, needle))
    if not checks:
        return records

    def matches(record: EnaRecord) -> bool:
        """Return whether ``record`` passes every filter."""
        return all(needle in _value_at(record, pos).casefold() for pos, needle in checks)

    return [record for record in records if matches(record)]


_NUMBER_RE = re.compile(r"(\d+)")


def _natural_key(value: str) -> tuple[tuple[int, int | str], ...]:
    """Return a key sorting text naturally: "ERR2" before "ERR10", numbers by value.

    ISO dates ("2021-03-01") also sort correctly, as their parts are compared as numbers.
    """
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part)
        for part in _NUMBER_RE.split(value.casefold())
        if part
    )


def sort_records(
    records: list[EnaRecord], record_type: RecordType, field: str, *, descending: bool = False
) -> list[EnaRecord]:
    """Return the records sorted on ``field``, with blank values always last.

    An unknown field leaves the records in ENA's order.
    """
    position = _value_position(record_type, field)
    if position is False:
        return records
    filled = [record for record in records if _value_at(record, position)]
    blank = [record for record in records if not _value_at(record, position)]
    filled.sort(key=lambda record: _natural_key(_value_at(record, position)), reverse=descending)
    return filled + blank


def taxon_url(taxon_id: int) -> str:
    """Return the ENA browser page for an NCBI taxonomy id."""
    return f"{ENA_BROWSER_VIEW_URL}/Taxon:{int(taxon_id)}"


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


def _parse_count(body: str) -> int | None:
    """Parse the count endpoint's plain-text body.

    The body is a "count" header line, then the number on the next line, so the last
    non-blank line is taken. Returns None if that isn't a non-negative integer.
    """
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    if not lines or not (lines[-1].isascii() and lines[-1].isdigit()):
        return None
    return int(lines[-1])


def fetch_count(record_type: RecordType, query: str) -> int | None:
    """Return how many records of ``record_type`` match ``query``, or None on failure."""

    def compute() -> int | None:
        """Use in cache_get_or_set to fetch the count if cache miss."""
        body = fetch_text(
            url=f"{ENA_PORTAL_API_URL}/count",
            params={"result": record_type.result, "query": query},
        )
        if body is None:
            return None
        count = _parse_count(body)
        if count is None:
            LOGGER.error("ena.invalid_count_response", result=record_type.result, body=body[:200])
        return count

    return cache_get_or_set(
        key=_cache_key("count", record_type.result, query),
        timeout=ENA_COUNT_CACHE_TTL_SECONDS,
        compute=compute,
    )


def fetch_records(
    record_type: RecordType, query: str, *, limit: int = MAX_BROWSABLE_RECORDS
) -> list[EnaRecord] | None:
    """Return the first ``limit`` records matching ``query``, or None on failure.

    ENA returns records in a stable order, so callers page through this list
    themselves (see ``MAX_BROWSABLE_RECORDS``).
    """

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
        key=_cache_key("records", record_type.result, query, limit, *record_type.fields),
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
