"""Session storage for visitor-uploaded liver DE data."""

from __future__ import annotations

from typing import Any, TypedDict

from django.http import HttpRequest

SESSION_KEY = "liver_resource_de"
DEFAULT_CUTOFF = "standard"


class DeFileEntry(TypedDict):
    """One parsed DE upload stored in the visitor session."""

    filename: str
    header: list[str]
    genes: list[str]
    data: dict[str, dict[str, float | None]]


class LiverDeSession(TypedDict):
    """Serialisable DE upload(s) stored in the visitor session."""

    cutoff: str
    files: list[DeFileEntry]


def store_de_session(
    request: HttpRequest,
    *,
    de_data: dict[str, Any],
    filename: str,
    cutoff: str = DEFAULT_CUTOFF,
) -> None:
    """Persist one parsed DE file in the visitor session."""
    store_de_uploads(request, uploads=[(filename, de_data)], cutoff=cutoff)


def store_de_uploads(
    request: HttpRequest,
    *,
    uploads: list[tuple[str, dict[str, Any]]],
    cutoff: str = DEFAULT_CUTOFF,
) -> None:
    """Persist one or more parsed DE files in the visitor session."""
    request.session[SESSION_KEY] = {
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
    request.session.modified = True


def get_de_session(request: HttpRequest) -> LiverDeSession | None:
    """Return stored DE data for the current visitor, if any."""
    payload = request.session.get(SESSION_KEY)
    if not isinstance(payload, dict):
        return None

    if "files" not in payload and "filename" in payload:
        payload = {
            "cutoff": payload.get("cutoff", DEFAULT_CUTOFF),
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

    return payload  # type: ignore[return-value]


def get_session_cutoff(request: HttpRequest) -> str:
    """Return the active DEcutoff mode from session, or the default."""
    session = get_de_session(request)
    if session is None:
        return DEFAULT_CUTOFF
    return session.get("cutoff", DEFAULT_CUTOFF)


def update_session_cutoff(request: HttpRequest, cutoff: str) -> None:
    """Update the stored cutoff without re-uploading the DE file."""
    session = get_de_session(request)
    if session is None:
        return
    session["cutoff"] = cutoff
    request.session[SESSION_KEY] = session
    request.session.modified = True


def clear_de_session(request: HttpRequest) -> None:
    """Remove uploaded DE data from the visitor session."""
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
