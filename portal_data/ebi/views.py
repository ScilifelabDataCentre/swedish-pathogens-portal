"""View functions for the Genomic data page: downloads of ENA records."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import date
from itertools import chain

import structlog
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseBadRequest,
    StreamingHttpResponse,
)
from django.views.decorators.http import require_POST

from portal_data.ebi.context import ListingState, resolve_state
from portal_data.ebi.download import (
    DownloadError,
    DownloadFormat,
    get_format,
    iter_accession_lines,
    iter_accessions,
    iter_ena_data,
    iter_tsv,
    parse_accessions,
)
from portal_data.ebi.search import DataType

LOGGER = structlog.get_logger(__name__)


def _download_chunks(
    state: ListingState, download_format: DownloadFormat, accessions: list[str] | None
) -> Iterator[bytes]:
    """Yield the download file: for the given accessions, or all results of ``state``."""

    def all_accessions() -> Iterable[str]:
        return iter_accessions(state.data_type, text=state.text, selected_facets=state.facets)

    if download_format.kind == "ena":
        yield from iter_ena_data(download_format, accessions or all_accessions())
        return
    if download_format.kind == "accessions":
        lines = iter_accession_lines(accessions or all_accessions())
    else:
        lines = iter_tsv(
            state.data_type, text=state.text, selected_facets=state.facets, accessions=accessions
        )
    for line in lines:
        yield line.encode("utf-8")


def _logged(chunks: Iterator[bytes], **log_context: object) -> Iterator[bytes]:
    """Pass the chunks on, logging a failure part-way through before re-raising it.

    Once streaming has started the response status can't change, so the error is
    re-raised to abort the connection: the browser then reports the download as
    failed, rather than saving a silently truncated file.
    """
    try:
        yield from chunks
    except DownloadError:
        LOGGER.error("genomic_data.download_interrupted", **log_context)
        raise


def download_filename(data_type: DataType, scope: str, download_format: DownloadFormat) -> str:
    """Return the download's file name, e.g. "genomic-data-raw-reads-all-2026-10-29.xml"."""
    suffix = {"accessions": "-accessions", "tsv": "-metadata"}.get(download_format.kind, "")
    return (
        f"genomic-data-{data_type.key}-{scope}{suffix}-{date.today().isoformat()}"
        f".{download_format.extension}"
    )


@require_POST
def serve_download(request: HttpRequest) -> HttpResponse:
    """Stream a download of the selected records, or all results of the current view.

    The view (data type, search words, facets) comes from the query string, as on
    the page itself. The form posts ``scope`` ("selected" or "all"), ``format``
    (see ``portal_data.ebi.download``) and, for selected records, ``ids``: the
    accessions, comma-separated.
    """
    state = resolve_state(request)
    download_format = get_format(state.data_type, request.POST.get("format", ""))
    if download_format is None:
        return HttpResponseBadRequest("Unknown download format.")

    scope = request.POST.get("scope", "")
    if scope == "selected":
        accessions = parse_accessions(request.POST.get("ids", ""))
        if not accessions:
            return HttpResponseBadRequest("No records were selected.")
    elif scope == "all":
        accessions = None
    else:
        return HttpResponseBadRequest("Choose selected records or all results.")

    log_context = {
        "data_type": state.data_type.key,
        "format": download_format.key,
        "scope": scope,
        "selected": len(accessions or []),
    }
    chunks = _download_chunks(state, download_format, accessions)
    # Fetch the first part before responding, so EBI Search or ENA being down gives
    # an error page instead of a broken file.
    try:
        first = next(chunks, b"")
    except DownloadError as e:
        LOGGER.error("genomic_data.download_failed", error=str(e), **log_context)
        return HttpResponse(
            f"{e} Please try again later.", status=502, content_type="text/plain; charset=utf-8"
        )

    LOGGER.info("genomic_data.download_started", **log_context)
    response = StreamingHttpResponse(
        _logged(chain([first], chunks), **log_context), content_type=download_format.content_type
    )
    filename = download_filename(state.data_type, scope, download_format)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
