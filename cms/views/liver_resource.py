"""HTMX and JSON endpoints for the DINA Liver Resource dashboard.

These views support the visitor-driven workflow on ``LiverResourceDashboardPage``:
upload DE file(s), change DEcutoff, inspect module genes, load bundled examples,
and download results. Parsed DE data lives in the Django session — not in
``DashboardData`` (see PR-READINESS.md §5).

MVP endpoint map (all required unless noted):

| View | Method | MVP | User story |
|------|--------|-----|------------|
| ``upload_de`` | POST | Yes | FR-1 — upload and plot |
| ``load_example`` | GET | Yes | FR-9 — bundled examples |
| ``recompute`` | GET | Yes | FR-3 — change DEcutoff |
| ``module_detail`` | GET | Yes | FR-6 — module gene table |
| ``download_template`` | GET | Yes | FR-10 — DE template |
| ``export_module_scores`` | GET | Yes | FR-7 — module scores CSV |
| ``export_genes`` | GET | Yes | FR-7 — gene classification CSV |
"""

from __future__ import annotations

import structlog
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from dashboard_visualisation.liver_resource.analysis import (
    LEAF_TRACE_INDEX,
    LiverAnalysisResult,
    analyse_de_uploads,
    colours_for_plotly_restyle,
)
from dashboard_visualisation.liver_resource.computation import VALID_CUTOFFS, parse_de_file
from dashboard_visualisation.liver_resource.examples import get_example_uploads
from dashboard_visualisation.liver_resource.exports import (
    build_genes_csv,
    build_module_scores_csv,
    export_basename,
)
from dashboard_visualisation.liver_resource.module_detail import build_module_detail
from dashboard_visualisation.liver_resource.session import (
    DEFAULT_CUTOFF,
    de_data_from_session,
    de_uploads_from_session,
    get_de_session,
    session_filenames,
    store_de_uploads,
    update_session_cutoff,
)
from dashboard_visualisation.liver_resource.plotly_tln import DEFAULT_PLOT_HEIGHT_PX
from dashboard_visualisation.liver_resource.validators import validate_de_upload
from dashboard_visualisation.utils.plotly import plot_html_from_json

LOGGER = structlog.get_logger(__name__)


@require_POST
def upload_de(request: HttpRequest) -> HttpResponse:
    """Accept one or more DE files, validate, store in session, return TLN plot partial.

    Single file → solid-coloured module leaves. Multiple files → pie-chart leaves
    per module (researcher ``f.TLNplot`` multi-row ``ValueM`` behaviour).
    """
    uploaded_files = list(request.FILES.getlist("de_files"))
    if not uploaded_files:
        legacy = request.FILES.get("de_file")
        if legacy is not None:
            uploaded_files = [legacy]

    if not uploaded_files:
        return _render_validation_errors(request, ("Choose one or more DE files to upload.",))

    cutoff = _normalise_cutoff(request.POST.get("cutoff", DEFAULT_CUTOFF))
    validated_uploads: list[tuple[str, dict]] = []
    for uploaded in uploaded_files:
        validation = validate_de_upload(uploaded, size_bytes=uploaded.size)
        if not validation.is_valid or validation.de_data is None:
            LOGGER.info(
                "liver_resource.upload_rejected",
                filename=getattr(uploaded, "name", ""),
                error_count=len(validation.errors),
            )
            return _render_validation_errors(request, validation.errors)
        validated_uploads.append((uploaded.name, validation.de_data))

    return _store_and_render_analysis(
        request,
        uploads=validated_uploads,
        cutoff=cutoff,
        log_event="liver_resource.upload_success",
    )


@require_GET
def load_example(request: HttpRequest, example_slug: str) -> HttpResponse:
    """Load a bundled single- or multi-file example into session and return the TLN plot.

    Sidebar exposes two examples: ``hcc-control`` (solid) and ``two-comparisons`` (pie).
    """
    example_uploads = get_example_uploads(example_slug)
    if example_uploads is None:
        return _render_validation_errors(request, (f"Unknown example dataset: {example_slug}",))

    cutoff = _normalise_cutoff(request.GET.get("cutoff", DEFAULT_CUTOFF))
    parsed_uploads = [(filename, parse_de_file(path)) for filename, path in example_uploads]
    return _store_and_render_analysis(
        request,
        uploads=parsed_uploads,
        cutoff=cutoff,
        log_event="liver_resource.example_loaded",
        example_slug=example_slug,
    )


@require_GET
def recompute(request: HttpRequest) -> HttpResponse:
    """Recompute module ratios for the session DE file(s) and active DEcutoff.

    Returns JSON for solid-leaf ``Plotly.restyle`` (default) or an HTML plot partial
    when ``Accept: text/html`` (pie-leaf mode after cutoff change).
    """
    session = get_de_session(request)
    if session is None:
        return JsonResponse(
            {"error": "Upload DE file(s) or load an example before changing cutoff."},
            status=400,
        )

    cutoff = _normalise_cutoff(request.GET.get("cutoff", session.get("cutoff", DEFAULT_CUTOFF)))
    update_session_cutoff(request, cutoff)
    analysis = analyse_de_uploads(de_uploads_from_session(session), cutoff=cutoff)

    if _wants_html_plot(request):
        return _render_plot_response(request, analysis)

    return JsonResponse(_analysis_payload(analysis))


@require_GET
def module_detail(request: HttpRequest, module_id: int) -> HttpResponse:
    """Return an HTML fragment listing genes overlapping a TLN module (htmx target).

    Uses the first uploaded file when multiple comparisons are in session (follow-up:
    per-file module detail).
    """
    session = get_de_session(request)
    if session is None:
        return render(
            request,
            "cms/pages/liver_resource/partials/session_required.html",
            {
                "message": "Upload DE file(s) or load an example to inspect module genes.",
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
            "cms/pages/liver_resource/partials/session_required.html",
            {"message": f"Module {module_id} was not found."},
            status=404,
        )

    return render(
        request,
        "cms/pages/liver_resource/partials/module_detail.html",
        {"detail": detail, "source_filename": session_filenames(session)[0]},
    )


@require_GET
def download_template(request: HttpRequest) -> HttpResponse:
    """Serve the bundled DE upload template (tab-separated limma-style header)."""
    from dashboard_visualisation.liver_resource.reference_data import get_template_path

    template_path = get_template_path()
    if not template_path.is_file():
        return HttpResponse("Template file not found.", status=404, content_type="text/plain")

    response = HttpResponse(
        template_path.read_text(encoding="utf-8"),
        content_type="text/tab-separated-values; charset=utf-8",
    )
    response["Content-Disposition"] = 'attachment; filename="DE_upload_template.txt"'
    return response


@require_GET
def export_module_scores(request: HttpRequest) -> HttpResponse:
    """Download module scores CSV (R ``*_module_scores.csv`` format) for the session.

    MVP requirement FR-7. Uses the first file when multiple comparisons are loaded.
    """
    session, error_response = _require_session_for_export(request)
    if error_response is not None:
        return error_response

    cutoff = _normalise_cutoff(request.GET.get("cutoff", session.get("cutoff", DEFAULT_CUTOFF)))
    de_data = de_data_from_session(session)
    content = build_module_scores_csv(de_data, cutoff)
    filename = f"{export_basename(session_filenames(session)[0])}_module_scores.csv"
    return _csv_attachment_response(filename, content)


@require_GET
def export_genes(request: HttpRequest) -> HttpResponse:
    """Download gene classification CSV (R ``*_genes.csv`` format) for the session.

    MVP requirement FR-7. Uses the first file when multiple comparisons are loaded.
    """
    session, error_response = _require_session_for_export(request)
    if error_response is not None:
        return error_response

    cutoff = _normalise_cutoff(request.GET.get("cutoff", session.get("cutoff", DEFAULT_CUTOFF)))
    de_data = de_data_from_session(session)
    content = build_genes_csv(de_data, cutoff)
    filename = f"{export_basename(session_filenames(session)[0])}_genes.csv"
    return _csv_attachment_response(filename, content)


def _require_session_for_export(request: HttpRequest) -> tuple[dict | None, HttpResponse | None]:
    """Return session payload or a 400 plain-text response when no upload exists."""
    session = get_de_session(request)
    if session is None:
        return None, HttpResponse(
            "Upload DE file(s) or load an example before downloading results.",
            status=400,
            content_type="text/plain; charset=utf-8",
        )
    return session, None


def _csv_attachment_response(filename: str, content: str) -> HttpResponse:
    """Build a CSV download response with Content-Disposition attachment."""
    response = HttpResponse(content, content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _normalise_cutoff(cutoff: str) -> str:
    """Map unknown cutoff values to the default DEcutoff mode."""
    if cutoff in VALID_CUTOFFS:
        return cutoff
    return DEFAULT_CUTOFF


def _store_and_render_analysis(
    request: HttpRequest,
    *,
    uploads: list[tuple[str, dict]],
    cutoff: str,
    log_event: str,
    example_slug: str | None = None,
) -> HttpResponse:
    """Persist uploads in session, run analysis, log, and return the plot partial."""
    store_de_uploads(request, uploads=uploads, cutoff=cutoff)
    analysis = analyse_de_uploads(uploads, cutoff=cutoff)
    log_kwargs = {
        "filenames": [filename for filename, _ in uploads],
        "file_count": len(uploads),
        "cutoff": cutoff,
        "plot_mode": analysis.plot_mode,
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
    """Render field-level upload errors for the htmx ``#liver-validation-errors`` target."""
    return render(
        request,
        "cms/pages/liver_resource/partials/validation_errors.html",
        {"errors": errors},
        status=400,
    )


def _render_plot_response(request: HttpRequest, analysis: LiverAnalysisResult) -> HttpResponse:
    """Convert analysis figure JSON to HTML and render the ``#liver-tln-panel`` partial."""
    plot_html = plot_html_from_json(
        analysis.figure_json,
        height=f"{DEFAULT_PLOT_HEIGHT_PX}px",
        include_plotlyjs=False,
    )
    return render(
        request,
        "cms/pages/liver_resource/partials/tln_plot.html",
        {
            "plot_html": plot_html,
            "height": DEFAULT_PLOT_HEIGHT_PX,
            "leaf_trace_index": LEAF_TRACE_INDEX,
            "analysis": analysis,
            "has_session": get_de_session(request) is not None,
        },
    )


def _wants_html_plot(request: HttpRequest) -> bool:
    """True when the client requests a full plot HTML partial (pie-mode cutoff recompute)."""
    accept = request.headers.get("Accept", "")
    return "text/html" in accept and "application/json" not in accept.split(",")[0]


def _analysis_payload(analysis: LiverAnalysisResult) -> dict[str, object]:
    """Build JSON for solid-leaf cutoff recompute (``Plotly.restyle`` in liver_resource.js)."""
    primary = analysis.comparisons[0]
    return {
        "plot_mode": analysis.plot_mode,
        "ratios": {str(module_id): value for module_id, value in primary.ratios.items()},
        "colours": {str(module_id): value for module_id, value in primary.colours.items()},
        "colours_array": colours_for_plotly_restyle(primary.colours),
        "stats": {
            "n_up": primary.up_count,
            "n_down": primary.down_count,
            "cutoff": analysis.cutoff,
            "filename": analysis.filename,
            "gene_count": primary.gene_count,
            "file_count": len(analysis.comparisons),
            "plot_mode": analysis.plot_mode,
            "filenames": [comparison.filename for comparison in analysis.comparisons],
        },
        "leaf_trace_index": LEAF_TRACE_INDEX,
    }
