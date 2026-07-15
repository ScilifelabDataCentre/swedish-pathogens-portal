"""Disk-backed storage for parsed liver DE uploads (keeps Django session small)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

from django.conf import settings

SESSIONS_SUBDIR = "liver_resource_sessions"


def get_sessions_root() -> Path:
    """Return the root directory for visitor DE session payloads."""
    root = Path(settings.MEDIA_ROOT) / SESSIONS_SUBDIR
    root.mkdir(parents=True, exist_ok=True)
    return root


def new_storage_id() -> str:
    """Generate an opaque id for a new on-disk DE session folder."""
    return uuid4().hex


def write_uploads(storage_id: str, uploads: list[tuple[str, dict[str, Any]]]) -> None:
    """Persist parsed DE uploads under ``MEDIA_ROOT/liver_resource_sessions/<id>/``."""
    dest = get_sessions_root() / storage_id
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
    dest = get_sessions_root() / storage_id
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
    shutil.rmtree(get_sessions_root() / storage_id, ignore_errors=True)
