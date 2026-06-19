"""HTMX endpoints for the DINA Liver Resource dashboard."""

from __future__ import annotations

import structlog
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from cms.services.liver_resource.analysis import (
    LEAF_TRACE_INDEX,
    LiverAnalysisResult,
    analyse_de_data,
)
from cms.services.liver_resource.computation import VALID_CUTOFFS
from cms.services.liver_resource.session import (
    DEFAULT_CUTOFF,
    get_de_session,
    store_de_session,
)
from cms.services.liver_resource.validators import validate_de_upload
from dashboard_visualisation.utils.plotly import plot_html_from_json

LOGGER = structlog.get_logger(__name__)
DEFAULT_PLOT_HEIGHT_PX = 700


@require_POST
def upload_de(request: HttpRequest) -> HttpResponse:
    """Validate an uploaded DE file, store it in session, and return the TLN plot."""
    uploaded = request.FILES.get("de_file")
    if uploaded is None:
        return _render_validation_errors(request, ("Choose a DE file to upload.",))

    cutoff = request.POST.get("cutoff", DEFAULT_CUTOFF)
    if cutoff not in VALID_CUTOFFS:
        cutoff = DEFAULT_CUTOFF

    validation = validate_de_upload(uploaded, size_bytes=uploaded.size)
    if not validation.is_valid or validation.de_data is None:
        LOGGER.info(
            "liver_resource.upload_rejected",
            filename=getattr(uploaded, "name", ""),
            error_count=len(validation.errors),
        )
        return _render_validation_errors(request, validation.errors)

    store_de_session(
        request,
        de_data=validation.de_data,
        filename=uploaded.name,
        cutoff=cutoff,
    )
    analysis = analyse_de_data(
        validation.de_data,
        filename=uploaded.name,
        cutoff=cutoff,
    )
    LOGGER.info(
        "liver_resource.upload_success",
        filename=uploaded.name,
        cutoff=cutoff,
        gene_count=analysis.gene_count,
        up_count=analysis.up_count,
        down_count=analysis.down_count,
    )
    return _render_plot_response(request, analysis)


def _render_validation_errors(
    request: HttpRequest,
    errors: tuple[str, ...] | list[str],
) -> HttpResponse:
    return render(
        request,
        "cms/partials/liver_validation_errors.html",
        {"errors": errors},
        status=400,
    )


def _render_plot_response(request: HttpRequest, analysis: LiverAnalysisResult) -> HttpResponse:
    plot_html = plot_html_from_json(
        analysis.figure_json,
        height=f"{DEFAULT_PLOT_HEIGHT_PX}px",
        include_plotlyjs=False,
    )
    return render(
        request,
        "cms/partials/liver_tln_plot.html",
        {
            "plot_html": plot_html,
            "height": DEFAULT_PLOT_HEIGHT_PX,
            "leaf_trace_index": LEAF_TRACE_INDEX,
            "analysis": analysis,
            "has_session": get_de_session(request) is not None,
        },
    )
