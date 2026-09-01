"""Shared utility views for the project.

Endpoints defined here are used across the system.
"""

from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_http_methods

from cms.services.ebi_index import build_index

EBI_INDEX_CACHE_CONTROL = "public, max-age=3600"


def healthz(_request: HttpRequest) -> JsonResponse:
    """Health check endpoint.

    Used for monitoring uptime of the service.
    Always returns a JSON object indicating that the service is running.

    Args:
        _request: Incoming HTTP request object (not used)

    Returns:
        JsonResponse: A JSON response indicating service status.
            Always returns 200 OK with {"status": "ok"} unless there is a server issue.

    """
    return JsonResponse({"status": "ok"})


@require_http_methods(["GET", "HEAD"])
def ebi_index(_request: HttpRequest) -> JsonResponse:
    """Public EBI catalogue JSON for EMBL-EBI (`national-portals-sweden`).

    Unauthenticated. GET and HEAD only. Envelope comes from env (fixed name,
    release fields). Entries are live dashboards with EBI panel values filled.
    """
    response = JsonResponse(build_index(), json_dumps_params={"ensure_ascii": False})
    response["Cache-Control"] = EBI_INDEX_CACHE_CONTROL
    return response
