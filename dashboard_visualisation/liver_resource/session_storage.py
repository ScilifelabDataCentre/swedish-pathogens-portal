"""Disk-backed storage for parsed liver DE uploads (keeps Django session small).

Visitor DE payloads live under ``settings.LIVER_SESSION_ROOT``, which must be
outside the publicly served ``MEDIA_ROOT`` tree (R1 Option A).
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

from django.conf import settings

# Directory leaf name (used only in docs / legacy references). Actual root is
# ``settings.LIVER_SESSION_ROOT`` and must not sit under ``MEDIA_ROOT``.
SESSIONS_SUBDIR = "liver_resource_sessions"
_STORAGE_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def get_sessions_root() -> Path:
    """Return the private root directory for visitor DE session payloads."""
    root = Path(settings.LIVER_SESSION_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    return root


def new_storage_id() -> str:
    """Generate an opaque id for a new on-disk DE session folder."""
    return uuid4().hex


def _validated_storage_id(storage_id: str) -> str:
    """Reject non-hex ids so path joins cannot escape the sessions root."""
    if not _STORAGE_ID_RE.fullmatch(storage_id):
        msg = f"Invalid liver DE storage id {storage_id!r}."
        raise ValueError(msg)
    return storage_id


def _storage_dir(storage_id: str) -> Path:
    return get_sessions_root() / _validated_storage_id(storage_id)


def write_uploads(storage_id: str, uploads: list[tuple[str, dict[str, Any]]]) -> None:
    """Persist parsed DE uploads under ``LIVER_SESSION_ROOT/<id>/``."""
    dest = _storage_dir(storage_id)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)

    manifest = [{"filename": filename} for filename, _ in uploads]
    (dest / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    for index, (filename, de_data) in enumerate(uploads):
        payload = {
            "filename": filename,
            "header": de_data["header"],
            "genes": de_data["genes"],
            "data": de_data["data"],
        }
        (dest / f"{index}.json").write_text(json.dumps(payload), encoding="utf-8")


def read_uploads(storage_id: str) -> list[tuple[str, dict[str, Any]]]:
    """Load parsed DE uploads previously stored for ``storage_id``."""
    dest = _storage_dir(storage_id)
    manifest_path = dest / "manifest.json"
    if not manifest_path.is_file():
        msg = f"Liver DE session data not found for id {storage_id!r}."
        raise FileNotFoundError(msg)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    uploads: list[tuple[str, dict[str, Any]]] = []
    for index, entry in enumerate(manifest):
        payload = json.loads((dest / f"{index}.json").read_text(encoding="utf-8"))
        filename = entry.get("filename") or payload.get("filename") or f"upload-{index}.txt"
        de_data = {
            "header": payload["header"],
            "genes": payload["genes"],
            "data": payload["data"],
        }
        uploads.append((filename, de_data))
    return uploads


def delete_storage(storage_id: str) -> None:
    """Remove on-disk DE data for a visitor session."""
    try:
        dest = _storage_dir(storage_id)
    except ValueError:
        return
    shutil.rmtree(dest, ignore_errors=True)
