"""View functions for the PortalDataPage."""

from __future__ import annotations

import logging

from django.http import (
    Http404,
    HttpRequest,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseNotAllowed,
)
from django.shortcuts import render

from portal_data.services import (
    ACCESSION_RE,
    get_datatype_config,
    resolve_bulk_download,
)

logger = logging.getLogger(__name__)


def serve_bulk_download(
    request: HttpRequest, page: object, datatype: str, template: str
) -> HttpResponse:
    """Resolve the POSTed study accessions to direct MetaboLights download links."""
    if get_datatype_config(datatype) is None:
        raise Http404("Unknown data type")

    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    ids = request.POST.getlist("ids")
    accessions = sorted({i for i in ids if ACCESSION_RE.match(i)})

    if not accessions:
        return HttpResponseBadRequest("No studies selected")

    results = resolve_bulk_download(accessions)

    context = {"results": results, "page": page}
    return render(request, template, context)
