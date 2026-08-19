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

SESSION_KEY = "liver_resource_de"
DEFAULT_CUTOFF = "standard"


class DeFileEntry(TypedDict):
    """One parsed DE upload for the current visitor session."""

    filename: str
    header: list[str]
    genes: list[str]
    data: dict[str, dict[str, float | None]]


class LiverDeSession(TypedDict):
    """Hydrated DE upload(s) for the current visitor."""

    cutoff: str
    files: list[DeFileEntry]


def store_de_session(
    request: HttpRequest,
    *,
    de_data: dict[str, Any],
    filename: str,
    cutoff: str = DEFAULT_CUTOFF,
) -> None:
    """Persist one parsed DE file for the visitor session."""
    store_de_uploads(request, uploads=[(filename, de_data)], cutoff=cutoff)


def store_de_uploads(
    request: HttpRequest,
    *,
    uploads: list[tuple[str, dict[str, Any]]],
    cutoff: str = DEFAULT_CUTOFF,
) -> None:
    """Persist parsed DE file(s): metadata in Django session, payloads on disk."""
    _clear_stored_payload(request)

    storage_id = new_storage_id()
    write_uploads(storage_id, uploads)
    request.session[SESSION_KEY] = {
        "storage_id": storage_id,
        "cutoff": cutoff,
        "files": [{"filename": filename} for filename, _ in uploads],
    }
    request.session.modified = True


def get_de_session(request: HttpRequest) -> LiverDeSession | None:
    """Return stored DE data for the current visitor, if any."""
    payload = request.session.get(SESSION_KEY)
    if not isinstance(payload, dict):
        return None

    cutoff = payload.get("cutoff", DEFAULT_CUTOFF)
    storage_id = payload.get("storage_id")

    if storage_id:
        try:
            uploads = read_uploads(storage_id)
        except FileNotFoundError:
            return None
        return {
            "cutoff": cutoff,
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
            "cutoff": cutoff,
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

    return {"cutoff": cutoff, "files": payload["files"]}  # type: ignore[return-value]


def get_session_cutoff(request: HttpRequest) -> str:
    """Return the active DEcutoff mode from session, or the default."""
    payload = request.session.get(SESSION_KEY)
    if not isinstance(payload, dict):
        return DEFAULT_CUTOFF
    return payload.get("cutoff", DEFAULT_CUTOFF)


def update_session_cutoff(request: HttpRequest, cutoff: str) -> None:
    """Update the stored cutoff without re-uploading the DE file."""
    payload = request.session.get(SESSION_KEY)
    if not isinstance(payload, dict):
        return
    payload["cutoff"] = cutoff
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


def _clear_stored_payload(request: HttpRequest) -> None:
    """Delete any on-disk payloads referenced by the current Django session."""
    payload = request.session.get(SESSION_KEY)
    if not isinstance(payload, dict):
        return
    storage_id = payload.get("storage_id")
    if isinstance(storage_id, str) and storage_id:
        delete_storage(storage_id)
