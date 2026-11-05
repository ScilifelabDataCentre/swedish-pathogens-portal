"""Downloads of Genomic data search results, served from the portal itself.

The options match the central Pathogens Portal's download dialog:

- data files from ENA's Browser API: EMBL or FASTA for sequences, XML for the
  other data types;
- metadata: a list of accessions, or a TSV of the table's columns.

Each can cover the records the visitor selected, or all results of the current
search and filters. Accessions and TSV rows come from EBI Search in large pages,
so they are quick even for tens of thousands of records. Data files come from
ENA in batches and are streamed on to the visitor as they arrive; they can be
large and take minutes for big result sets, so nothing is held in memory.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from itertools import islice

import httpx
import structlog

from cms.services.api_client import CLIENT
from portal_data.ebi_search import (
    BASE_QUERY,
    EBI_SEARCH_URL,
    Column,
    DataType,
    filter_params,
    format_value,
)

LOGGER = structlog.get_logger(__name__)

ENA_BROWSER_API_URL = "https://www.ebi.ac.uk/ena/browser/api"

# Page sizes EBI Search allows per request for each format.
ACCESSION_PAGE_SIZE = 10_000
TSV_PAGE_SIZE = 1_000
# Accessions per request when looking up selected records, and per ENA data request.
SELECTED_BATCH_SIZE = 200
ENA_BATCH_SIZE = 100

EBI_TIMEOUT_SECONDS = 60
ENA_TIMEOUT_SECONDS = 180

# ENA accessions start with a letter and contain a digit, with only letters, digits,
# "_", "." and "-" (e.g. "ERX123", "GCA_001835525.1"). Requiring a digit also rules
# out query operators such as "OR" ever reaching a query.
ACCESSION_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]*[0-9][A-Za-z0-9_.\-]*")
MAX_ACCESSION_LENGTH = 40

ACCESSION_COLUMN = Column("acc", "Accession")


class DownloadError(Exception):
    """EBI Search or ENA could not provide (part of) a download."""


@dataclass(frozen=True)
class DownloadFormat:
    """A download option.

    Attributes:
        key: Name used in the download form, e.g. "fasta".
        label: Option label shown in the download dialog.
        description: One-line explanation shown under the label.
        extension: File name extension.
        content_type: The response's content type.
        kind: "ena" (data files from ENA), "accessions" or "tsv" (metadata).
    """

    key: str
    label: str
    description: str
    extension: str
    content_type: str
    kind: str


XML = DownloadFormat(
    "xml", "XML", "Metadata records in ENA's XML format", "xml", "application/xml", "ena"
)
EMBL = DownloadFormat(
    "embl",
    "EMBL",
    "Annotations and sequence in EMBL flat file format",
    "embl",
    "text/plain; charset=utf-8",
    "ena",
)
FASTA = DownloadFormat(
    "fasta", "FASTA", "Sequences in FASTA format", "fasta", "text/plain; charset=utf-8", "ena"
)
ACCESSIONS = DownloadFormat(
    "accessions",
    "List of IDs (accessions)",
    "One accession per line",
    "txt",
    "text/plain; charset=utf-8",
    "accessions",
)
TSV = DownloadFormat(
    "tsv",
    "TSV (tab-separated metadata table)",
    "The table's columns, one record per row",
    "tsv",
    "text/tab-separated-values; charset=utf-8",
    "tsv",
)

# Data file formats ENA's Browser API provides for each data type.
DATA_FORMATS: dict[str, tuple[DownloadFormat, ...]] = {
    "sequences": (EMBL, FASTA),
    "analyses": (XML,),
    "raw-reads": (XML,),
    "samples": (XML,),
    "assemblies": (XML,),
}
METADATA_FORMATS: tuple[DownloadFormat, ...] = (ACCESSIONS, TSV)


def data_formats(data_type: DataType) -> tuple[DownloadFormat, ...]:
    """Return the data file formats offered for ``data_type``."""
    return DATA_FORMATS.get(data_type.key, (XML,))


def get_format(data_type: DataType, key: str) -> DownloadFormat | None:
    """Return the download format called ``key`` if offered for ``data_type``, else None."""
    for download_format in (*data_formats(data_type), *METADATA_FORMATS):
        if download_format.key == key:
            return download_format
    return None


def parse_accessions(raw: str) -> list[str]:
    """Return the valid accessions from a comma or whitespace separated list, de-duplicated."""
    candidates = re.split(r"[\s,]+", raw.strip())
    return list(
        dict.fromkeys(
            a for a in candidates if len(a) <= MAX_ACCESSION_LENGTH and ACCESSION_RE.fullmatch(a)
        )
    )


def _batches(items: Iterable[str], size: int) -> Iterator[list[str]]:
    """Yield ``items`` in lists of at most ``size``."""
    iterator = iter(items)
    while batch := list(islice(iterator, size)):
        yield batch


def _ebi_search(data_type: DataType, params: dict[str, object]) -> str:
    """Return the body of an EBI Search request, raising DownloadError on failure."""
    url = f"{EBI_SEARCH_URL}/{data_type.domain}"
    try:
        response = CLIENT.get(url, params=params, timeout=EBI_TIMEOUT_SECONDS)
        response.raise_for_status()
    except httpx.HTTPError as e:
        LOGGER.error("ebi_download.search_failed", url=url, error=str(e))
        raise DownloadError("EBI Search could not be reached.") from e
    return response.text


def _selected_query(accessions: list[str]) -> str:
    """Return a query for exactly the given (validated) accessions, among the portal's records."""
    return f"{BASE_QUERY} AND acc:({' OR '.join(accessions)})"


# --- Accessions --------------------------------------------------------------------------


def iter_accessions(
    data_type: DataType, *, text: str = "", selected_facets: dict[str, list[str]] | None = None
) -> Iterator[str]:
    """Yield the accession of every record matching the search and facets.

    EBI Search returns up to ``ACCESSION_PAGE_SIZE`` accessions per request, so
    even tens of thousands of records only take a few requests.
    """
    base = filter_params(text, selected_facets)
    start = 0
    while True:
        body = _ebi_search(
            data_type,
            {**base, "format": "idlist", "size": ACCESSION_PAGE_SIZE, "start": start},
        )
        page = [line.strip() for line in body.splitlines() if line.strip()]
        yield from page
        if len(page) < ACCESSION_PAGE_SIZE:
            return
        start += ACCESSION_PAGE_SIZE


def iter_accession_lines(accessions: Iterable[str]) -> Iterator[str]:
    """Yield the accessions as lines of a text file."""
    for accession in accessions:
        yield f"{accession}\n"


# --- Metadata TSV --------------------------------------------------------------------------


def _tsv_line(values: list[str]) -> str:
    """Return one TSV line, quoting values only where needed."""
    buffer = io.StringIO()
    csv.writer(buffer, delimiter="\t", lineterminator="\n").writerow(values)
    return buffer.getvalue()


def _tsv_rows(body: str, columns: list[Column]) -> list[str]:
    """Return the formatted TSV lines for one EBI Search TSV response.

    EBI Search quotes every value and repeats its header on every page; the
    header is dropped and values are formatted as in the table (e.g. dates).
    """
    rows = list(csv.reader(io.StringIO(body), delimiter="\t", quotechar='"'))
    if not rows:
        return []
    header = rows[0]
    lines = []
    for row in rows[1:]:
        if not any(row):
            continue
        by_field = dict(zip(header, row, strict=False))
        lines.append(_tsv_line([format_value(by_field.get(c.field, ""), c.kind) for c in columns]))
    return lines


def iter_tsv(
    data_type: DataType,
    *,
    text: str = "",
    selected_facets: dict[str, list[str]] | None = None,
    accessions: list[str] | None = None,
) -> Iterator[str]:
    """Yield a TSV of the table's columns: the given accessions, or all matching records."""
    columns = [ACCESSION_COLUMN, *data_type.columns]
    fields = ",".join(column.field for column in columns)
    yield _tsv_line([column.label for column in columns])

    if accessions is not None:
        for batch in _batches(accessions, SELECTED_BATCH_SIZE):
            body = _ebi_search(
                data_type,
                {
                    "query": _selected_query(batch),
                    "format": "tsv",
                    "fields": fields,
                    "size": len(batch),
                },
            )
            yield from _tsv_rows(body, columns)
        return

    base = filter_params(text, selected_facets)
    start = 0
    while True:
        body = _ebi_search(
            data_type,
            {**base, "format": "tsv", "fields": fields, "size": TSV_PAGE_SIZE, "start": start},
        )
        rows = _tsv_rows(body, columns)
        yield from rows
        if len(rows) < TSV_PAGE_SIZE:
            return
        start += TSV_PAGE_SIZE


# --- ENA data files ----------------------------------------------------------------------------

_XML_DECLARATION_RE = re.compile(r"^\s*<\?xml[^>]*\?>\s*")
_XML_ROOT_RE = re.compile(
    r"^\s*<(?P<tag>[A-Za-z_][\w.\-]*)(?:\s[^>]*?)?(?:/>|>(?P<inner>.*)</(?P=tag)>)\s*$",
    re.S,
)


def _split_xml(body: str) -> tuple[str, str]:
    """Return ``(root tag, inner XML)`` of one ENA XML response, e.g. an EXPERIMENT_SET.

    Each batch from ENA is a complete document with its own root element, so the
    batches' contents are merged under a single root to keep the file valid XML.
    """
    body = _XML_DECLARATION_RE.sub("", body)
    match = _XML_ROOT_RE.match(body)
    if not match:
        raise DownloadError("ENA returned an unexpected XML response.")
    return match["tag"], (match["inner"] or "").strip("\n")


class _EnaRejectedError(Exception):
    """ENA rejected a batch of accessions (a 4xx response)."""


def _post_ena(download_format: DownloadFormat, batch: list[str]) -> bytes:
    """Return one batch of ENA records, retrying once on server or network errors.

    ENA's Browser API takes the accessions as JSON in a POST (a form post is
    rejected with "415 Unsupported Media Type"). Raises ``_EnaRejectedError`` if ENA
    rejects the accessions, and ``DownloadError`` if it can't be reached.
    """
    url = f"{ENA_BROWSER_API_URL}/{download_format.key}"
    payload = {"accessions": ",".join(batch), "download": False, "gzip": False}
    last_error: Exception | None = None
    for _attempt in range(2):
        try:
            response = CLIENT.post(url, json=payload, timeout=ENA_TIMEOUT_SECONDS)
        except httpx.HTTPError as e:
            last_error = e
            continue
        if response.is_success:
            return response.content
        if response.is_client_error:
            raise _EnaRejectedError(response.text[:200])
        last_error = httpx.HTTPStatusError(
            f"HTTP {response.status_code}", request=response.request, response=response
        )
    LOGGER.error("ebi_download.ena_failed", url=url, size=len(batch), error=str(last_error))
    raise DownloadError("ENA could not be reached.") from last_error


def _fetch_ena(download_format: DownloadFormat, batch: list[str]) -> list[bytes]:
    """Return the ENA responses for a batch, skipping accessions ENA rejects.

    ENA rejects a whole batch if any accession in it is unknown, or (for EMBL and
    FASTA) not of the same kind as the first one. A rejected batch is split in
    half and retried, so only the offending accessions are left out.
    """
    try:
        return [_post_ena(download_format, batch)]
    except _EnaRejectedError as e:
        if len(batch) == 1:
            LOGGER.warning("ebi_download.ena_rejected", accession=batch[0], error=str(e))
            return []
    middle = len(batch) // 2
    return _fetch_ena(download_format, batch[:middle]) + _fetch_ena(download_format, batch[middle:])


def iter_ena_data(download_format: DownloadFormat, accessions: Iterable[str]) -> Iterator[bytes]:
    """Yield the ENA data file for ``accessions``, fetched in batches of ``ENA_BATCH_SIZE``.

    EMBL and FASTA batches are simply concatenated. XML batches are merged under
    one root element, so the result is a single valid XML document.
    """
    if download_format.key != "xml":
        for batch in _batches(accessions, ENA_BATCH_SIZE):
            yield from _fetch_ena(download_format, batch)
        return

    root = None
    for batch in _batches(accessions, ENA_BATCH_SIZE):
        for body in _fetch_ena(download_format, batch):
            tag, inner = _split_xml(body.decode("utf-8"))
            if root is None:
                root = tag
                yield f'<?xml version="1.0" encoding="UTF-8"?>\n<{root}>\n'.encode()
            if inner:
                yield f"{inner}\n".encode()
    if root is not None:
        yield f"</{root}>\n".encode()
