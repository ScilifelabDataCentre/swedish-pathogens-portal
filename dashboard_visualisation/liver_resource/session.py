"""Session storage for visitor-uploaded liver DE data."""

from __future__ import annotations

from typing import Any, TypedDict

from django.http import HttpRequest

from dashboard_visualisation.liver_resource.session_storage import (
    delete_storage,
    new_storage_id,
    read_uploads,
    write_uploads,
)
from dashboard_visualisation.liver_resource.thresholds import (
    DEFAULT_ADJ_P,
    DEFAULT_LOGFC_FOLD,
    DEFAULT_THRESHOLD_KEY,
    parse_adj_p,
    parse_logfc_fold,
    threshold_key,
)

SESSION_KEY = "liver_resource_de"
# Backward-compatible alias used by older DashboardData / import sites.
DEFAULT_CUTOFF = DEFAULT_THRESHOLD_KEY


class DeFileEntry(TypedDict):
    """One parsed DE upload for the current visitor session."""

    filename: str
    header: list[str]
    genes: list[str]
    data: dict[str, dict[str, float | None]]


class LiverDeSession(TypedDict):
    """Hydrated DE upload(s) for the current visitor."""

    adj_p: float
    logfc_fold: float
    cutoff: str
    files: list[DeFileEntry]


def store_de_session(
    request: HttpRequest,
    *,
    de_data: dict[str, Any],
    filename: str,
    adj_p: float = DEFAULT_ADJ_P,
    logfc_fold: float = DEFAULT_LOGFC_FOLD,
    cutoff: str | None = None,
) -> None:
    """Persist one parsed DE file for the visitor session."""
    del cutoff  # Accepted for call-site compatibility; thresholds win.
    store_de_uploads(
        request,
        uploads=[(filename, de_data)],
        adj_p=adj_p,
        logfc_fold=logfc_fold,
    )


def store_de_uploads(
    request: HttpRequest,
    *,
    uploads: list[tuple[str, dict[str, Any]]],
    adj_p: float = DEFAULT_ADJ_P,
    logfc_fold: float = DEFAULT_LOGFC_FOLD,
    cutoff: str | None = None,
) -> None:
    """Persist parsed DE file(s): metadata in Django session, payloads on disk."""
    del cutoff
    _clear_stored_payload(request)

    adj_p = parse_adj_p(adj_p)
    logfc_fold = parse_logfc_fold(logfc_fold)
    storage_id = new_storage_id()
    write_uploads(storage_id, uploads)
    request.session[SESSION_KEY] = {
        "storage_id": storage_id,
        "adj_p": adj_p,
        "logfc_fold": logfc_fold,
        "cutoff": threshold_key(adj_p, logfc_fold),
        "files": [{"filename": filename} for filename, _ in uploads],
    }
    request.session.modified = True


def get_de_session(request: HttpRequest) -> LiverDeSession | None:
    """Return stored DE data for the current visitor, if any."""
    payload = request.session.get(SESSION_KEY)
    if not isinstance(payload, dict):
        return None

    adj_p, logfc_fold = _thresholds_from_payload(payload)
    storage_id = payload.get("storage_id")

    if storage_id:
        try:
            uploads = read_uploads(storage_id)
        except FileNotFoundError:
            return None
        return {
            "adj_p": adj_p,
            "logfc_fold": logfc_fold,
            "cutoff": threshold_key(adj_p, logfc_fold),
            "files": [
                {
                    "filename": filename,
                    "header": de_data["header"],
                    "genes": de_data["genes"],
                    "data": de_data["data"],
                }
                for filename, de_data in uploads
            ],
        }

    if "files" not in payload and "filename" in payload:
        payload = {
            "adj_p": adj_p,
            "logfc_fold": logfc_fold,
            "cutoff": threshold_key(adj_p, logfc_fold),
            "files": [
                {
                    "filename": payload["filename"],
                    "header": payload["header"],
                    "genes": payload["genes"],
                    "data": payload["data"],
                }
            ],
        }

    if not payload.get("files"):
        return None

    return {
        "adj_p": adj_p,
        "logfc_fold": logfc_fold,
        "cutoff": threshold_key(adj_p, logfc_fold),
        "files": payload["files"],
    }  # type: ignore[return-value]


def get_session_cutoff(request: HttpRequest) -> str:
    """Return the active threshold key for the session (DashboardData lookup)."""
    adj_p, logfc_fold = get_session_thresholds(request)
    return threshold_key(adj_p, logfc_fold)


def get_session_thresholds(request: HttpRequest) -> tuple[float, float]:
    """Return active Adj P.val and LogFC fold for the visitor session."""
    payload = request.session.get(SESSION_KEY)
    if not isinstance(payload, dict):
        return DEFAULT_ADJ_P, DEFAULT_LOGFC_FOLD
    return _thresholds_from_payload(payload)


def update_session_cutoff(
    request: HttpRequest,
    cutoff: str | None = None,
    *,
    adj_p: float | None = None,
    logfc_fold: float | None = None,
) -> None:
    """Update stored thresholds without re-uploading the DE file."""
    payload = request.session.get(SESSION_KEY)
    if not isinstance(payload, dict):
        return

    current_adj, current_fold = _thresholds_from_payload(payload)
    if adj_p is None and logfc_fold is None and cutoff:
        # Legacy callers may still pass a threshold key; ignore unknown keys.
        if "_" in cutoff:
            left, _, right = cutoff.partition("_")
            adj_p = parse_adj_p(left, default=current_adj)
            logfc_fold = parse_logfc_fold(right, default=current_fold)
        else:
            adj_p, logfc_fold = current_adj, current_fold

    next_adj = parse_adj_p(adj_p if adj_p is not None else current_adj)
    next_fold = parse_logfc_fold(logfc_fold if logfc_fold is not None else current_fold)
    payload["adj_p"] = next_adj
    payload["logfc_fold"] = next_fold
    payload["cutoff"] = threshold_key(next_adj, next_fold)
    request.session[SESSION_KEY] = payload
    request.session.modified = True


def clear_de_session(request: HttpRequest) -> None:
    """Remove uploaded DE data from the visitor session and disk."""
    _clear_stored_payload(request)
    if SESSION_KEY in request.session:
        del request.session[SESSION_KEY]
        request.session.modified = True


def de_data_from_session(session: LiverDeSession) -> dict[str, Any]:
    """Rebuild the parsed DE dict for the first uploaded file."""
    return de_entry_to_data(session["files"][0])


def de_uploads_from_session(session: LiverDeSession) -> list[tuple[str, dict[str, Any]]]:
    """Rebuild all parsed DE uploads stored in the session."""
    return [(entry["filename"], de_entry_to_data(entry)) for entry in session["files"]]


def session_filenames(session: LiverDeSession) -> list[str]:
    """Return uploaded filenames in session order."""
    return [entry["filename"] for entry in session["files"]]


def de_entry_to_data(entry: DeFileEntry) -> dict[str, Any]:
    """Rebuild the parsed DE dict used by computation services."""
    return {
        "header": entry["header"],
        "genes": entry["genes"],
        "data": entry["data"],
    }


def _thresholds_from_payload(payload: dict[str, Any]) -> tuple[float, float]:
    """Read Option B thresholds, mapping legacy ``cutoff=standard`` to defaults."""
    if "adj_p" in payload or "logfc_fold" in payload:
        return (
            parse_adj_p(payload.get("adj_p", DEFAULT_ADJ_P)),
            parse_logfc_fold(payload.get("logfc_fold", DEFAULT_LOGFC_FOLD)),
        )

    legacy = payload.get("cutoff")
    if legacy in (None, "standard", DEFAULT_THRESHOLD_KEY):
        return DEFAULT_ADJ_P, DEFAULT_LOGFC_FOLD
    if isinstance(legacy, str) and "_" in legacy:
        left, _, right = legacy.partition("_")
        return parse_adj_p(left), parse_logfc_fold(right)
    return DEFAULT_ADJ_P, DEFAULT_LOGFC_FOLD


def _clear_stored_payload(request: HttpRequest) -> None:
    """Delete any on-disk payloads referenced by the current Django session."""
    payload = request.session.get(SESSION_KEY)
    if not isinstance(payload, dict):
        return
    storage_id = payload.get("storage_id")
    if isinstance(storage_id, str) and storage_id:
        delete_storage(storage_id)
