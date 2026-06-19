"""HTMX endpoints for the DINA Liver Resource dashboard."""

from __future__ import annotations

import structlog
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from cms.services.liver_resource.analysis import (
    LEAF_TRACE_INDEX,
    LiverAnalysisResult,
    analyse_de_data,
    colours_for_plotly_restyle,
)
from cms.services.liver_resource.computation import VALID_CUTOFFS, parse_de_file
from cms.services.liver_resource.examples import get_example_path
from cms.services.liver_resource.exports import (
    build_genes_csv,
    build_module_scores_csv,
    export_basename,
)
from cms.services.liver_resource.module_detail import build_module_detail
from cms.services.liver_resource.session import (
    DEFAULT_CUTOFF,
    de_data_from_session,
    get_de_session,
    store_de_session,
    update_session_cutoff,
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

    cutoff = _normalise_cutoff(request.POST.get("cutoff", DEFAULT_CUTOFF))
    validation = validate_de_upload(uploaded, size_bytes=uploaded.size)
    if not validation.is_valid or validation.de_data is None:
        LOGGER.info(
            "liver_resource.upload_rejected",
            filename=getattr(uploaded, "name", ""),
            error_count=len(validation.errors),
        )
        return _render_validation_errors(request, validation.errors)

    return _store_and_render_analysis(
        request,
        de_data=validation.de_data,
        filename=uploaded.name,
        cutoff=cutoff,
        log_event="liver_resource.upload_success",
    )


@require_GET
def load_example(request: HttpRequest, example_slug: str) -> HttpResponse:
    """Load a bundled example DE file into session and return the TLN plot."""
    example_path = get_example_path(example_slug)
    if example_path is None:
        return _render_validation_errors(request, (f"Unknown example dataset: {example_slug}",))

    cutoff = _normalise_cutoff(request.GET.get("cutoff", DEFAULT_CUTOFF))
    de_data = parse_de_file(example_path)
    return _store_and_render_analysis(
        request,
        de_data=de_data,
        filename=example_path.name,
        cutoff=cutoff,
        log_event="liver_resource.example_loaded",
        example_slug=example_slug,
    )


@require_GET
def recompute(request: HttpRequest) -> HttpResponse:
    """Recompute module ratios and colours for the session DE file and cutoff."""
    session = get_de_session(request)
    if session is None:
        return JsonResponse(
            {"error": "Upload a DE file or load an example before changing cutoff."},
            status=400,
        )

    cutoff = _normalise_cutoff(request.GET.get("cutoff", session.get("cutoff", DEFAULT_CUTOFF)))
    update_session_cutoff(request, cutoff)
    de_data = de_data_from_session(session)
    analysis = analyse_de_data(de_data, filename=session["filename"], cutoff=cutoff)

    return JsonResponse(
        {
            "ratios": {str(module_id): value for module_id, value in analysis.ratios.items()},
            "colours": {str(module_id): value for module_id, value in analysis.colours.items()},
            "colours_array": colours_for_plotly_restyle(analysis.colours),
            "stats": {
                "n_up": analysis.up_count,
                "n_down": analysis.down_count,
                "cutoff": analysis.cutoff,
                "filename": analysis.filename,
                "gene_count": analysis.gene_count,
            },
            "leaf_trace_index": LEAF_TRACE_INDEX,
        }
    )


@require_GET
def module_detail(request: HttpRequest, module_id: int) -> HttpResponse:
    """Return an HTML fragment with genes for one TLN module."""
    session = get_de_session(request)
    if session is None:
        return render(
            request,
            "cms/partials/liver_session_required.html",
            {
                "message": "Upload a DE file or load an example to inspect module genes.",
            },
            status=400,
        )

    cutoff = _normalise_cutoff(request.GET.get("cutoff", session.get("cutoff", DEFAULT_CUTOFF)))
    detail = build_module_detail(
        de_data_from_session(session),
        module_id=module_id,
        cutoff=cutoff,
    )
    if detail is None:
        return render(
            request,
            "cms/partials/liver_session_required.html",
            {"message": f"Module {module_id} was not found."},
            status=404,
        )

    return render(
        request,
        "cms/partials/liver_module_detail.html",
        {"detail": detail},
    )


@require_GET
def export_module_scores(request: HttpRequest) -> HttpResponse:
    """Download module scores CSV for the current session analysis."""
    session, error_response = _require_session_for_export(request)
    if error_response is not None:
        return error_response

    cutoff = _normalise_cutoff(request.GET.get("cutoff", session.get("cutoff", DEFAULT_CUTOFF)))
    de_data = de_data_from_session(session)
    content = build_module_scores_csv(de_data, cutoff)
    filename = f"{export_basename(session['filename'])}_module_scores.csv"
    return _csv_attachment_response(filename, content)


@require_GET
def export_genes(request: HttpRequest) -> HttpResponse:
    """Download gene classification CSV for the current session analysis."""
    session, error_response = _require_session_for_export(request)
    if error_response is not None:
        return error_response

    cutoff = _normalise_cutoff(request.GET.get("cutoff", session.get("cutoff", DEFAULT_CUTOFF)))
    de_data = de_data_from_session(session)
    content = build_genes_csv(de_data, cutoff)
    filename = f"{export_basename(session['filename'])}_genes.csv"
    return _csv_attachment_response(filename, content)


def _require_session_for_export(request: HttpRequest) -> tuple[dict | None, HttpResponse | None]:
    session = get_de_session(request)
    if session is None:
        return None, HttpResponse(
            "Upload a DE file or load an example before downloading results.",
            status=400,
            content_type="text/plain; charset=utf-8",
        )
    return session, None


def _csv_attachment_response(filename: str, content: str) -> HttpResponse:
    response = HttpResponse(content, content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _normalise_cutoff(cutoff: str) -> str:
    if cutoff in VALID_CUTOFFS:
        return cutoff
    return DEFAULT_CUTOFF


def _store_and_render_analysis(
    request: HttpRequest,
    *,
    de_data: dict,
    filename: str,
    cutoff: str,
    log_event: str,
    example_slug: str | None = None,
) -> HttpResponse:
    store_de_session(request, de_data=de_data, filename=filename, cutoff=cutoff)
    analysis = analyse_de_data(de_data, filename=filename, cutoff=cutoff)
    log_kwargs = {
        "filename": filename,
        "cutoff": cutoff,
        "gene_count": analysis.gene_count,
        "up_count": analysis.up_count,
        "down_count": analysis.down_count,
    }
    if example_slug is not None:
        log_kwargs["example_slug"] = example_slug
    LOGGER.info(log_event, **log_kwargs)
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
