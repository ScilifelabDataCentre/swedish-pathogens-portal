"""Session storage for visitor-uploaded liver DE data."""

from __future__ import annotations

from typing import Any, TypedDict

from django.http import HttpRequest

SESSION_KEY = "liver_resource_de"
DEFAULT_CUTOFF = "standard"


class LiverDeSession(TypedDict):
    """Serialisable DE upload stored in the visitor session."""

    filename: str
    cutoff: str
    header: list[str]
    genes: list[str]
    data: dict[str, dict[str, float | None]]


def store_de_session(
    request: HttpRequest,
    *,
    de_data: dict[str, Any],
    filename: str,
    cutoff: str = DEFAULT_CUTOFF,
) -> None:
    """Persist parsed DE data in the visitor session."""
    request.session[SESSION_KEY] = {
        "filename": filename,
        "cutoff": cutoff,
        "header": de_data["header"],
        "genes": de_data["genes"],
        "data": de_data["data"],
    }
    request.session.modified = True


def get_de_session(request: HttpRequest) -> LiverDeSession | None:
    """Return stored DE data for the current visitor, if any."""
    payload = request.session.get(SESSION_KEY)
    if not isinstance(payload, dict):
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
    """Rebuild the parsed DE dict used by computation services."""
    return {
        "header": session["header"],
        "genes": session["genes"],
        "data": session["data"],
    }
