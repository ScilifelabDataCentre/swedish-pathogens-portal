"""Manifest models for portal data bundles."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class ManifestFile:
    """File entry listed in a portal data bundle manifest."""

    name: str
    path: str
    size: int | None = None
    checksum: str | None = None


@dataclass(frozen=True)
class ManifestProvenance:
    """Provenance metadata for a submitted portal data bundle."""

    submitted_by: str
    submitted_at: datetime
    notes: str | None = None


@dataclass(frozen=True)
class PortalBundleManifest:
    """Validated portal data bundle manifest."""

    id: str
    title: str
    unit: str
    datatype: str
    provenance: ManifestProvenance
    files: list[ManifestFile] = field(default_factory=list)
    pathogen: str | None = None
    repository: str = "spp-unit-bundles"
    year: int | None = None
    matrix: str | None = None
    instrument: str | None = None
    public: bool = False
    hidden: bool = False
    withdrawn: bool = False

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> PortalBundleManifest:
        """Build and validate a manifest from decoded JSON."""
        required_fields = ("id", "title", "unit", "datatype", "provenance", "files")
        missing_fields = [field_name for field_name in required_fields if field_name not in payload]

        if missing_fields:
            missing = ", ".join(missing_fields)
            msg = f"Missing required manifest field(s): {missing}"
            raise ValueError(msg)

        provenance_payload = payload["provenance"]
        if not isinstance(provenance_payload, dict):
            msg = "Manifest field provenance must be an object"
            raise ValueError(msg)

        submitted_at = provenance_payload.get("submitted_at")
        if not isinstance(submitted_at, str):
            msg = "Manifest provenance.submitted_at must be an ISO datetime string"
            raise ValueError(msg)

        try:
            parsed_submitted_at = datetime.fromisoformat(
                submitted_at.replace("Z", "+00:00"),
            )
        except ValueError as err:
            msg = "Manifest provenance.submitted_at is not a valid ISO datetime"
            raise ValueError(msg) from err

        submitted_by = provenance_payload.get("submitted_by")
        if not isinstance(submitted_by, str) or not submitted_by:
            msg = "Manifest provenance.submitted_by must be a non-empty string"
            raise ValueError(msg)

        provenance = ManifestProvenance(
            submitted_by=submitted_by,
            submitted_at=parsed_submitted_at,
            notes=_optional_string(provenance_payload.get("notes")),
        )

        files_payload = payload["files"]
        if not isinstance(files_payload, list):
            msg = "Manifest field files must be a list"
            raise ValueError(msg)

        files = [_file_from_payload(file_payload) for file_payload in files_payload]

        year = payload.get("year")
        if year is not None and not isinstance(year, int):
            msg = "Manifest field year must be an integer when provided"
            raise ValueError(msg)

        return cls(
            id=_required_string(payload, "id"),
            title=_required_string(payload, "title"),
            pathogen=_optional_string(payload.get("pathogen")),
            repository=str(payload.get("repository") or "spp-unit-bundles"),
            unit=_required_string(payload, "unit"),
            datatype=_required_string(payload, "datatype"),
            year=year,
            matrix=_optional_string(payload.get("matrix")),
            instrument=_optional_string(payload.get("instrument")),
            files=files,
            provenance=provenance,
            public=bool(payload.get("public", False)),
            hidden=bool(payload.get("hidden", False)),
            withdrawn=bool(payload.get("withdrawn", False)),
        )


def _required_string(payload: dict[str, Any], field_name: str) -> str:
    """Return a required string field from a manifest payload."""
    value = payload.get(field_name)

    if not isinstance(value, str) or not value:
        msg = f"Manifest field {field_name} must be a non-empty string"
        raise ValueError(msg)

    return value


def _optional_string(value: object) -> str | None:
    """Return a string value or None."""
    if value is None:
        return None

    if isinstance(value, str):
        return value

    return str(value)


def _file_from_payload(payload: object) -> ManifestFile:
    """Build a manifest file entry from decoded JSON."""
    if not isinstance(payload, dict):
        msg = "Each manifest file entry must be an object"
        raise ValueError(msg)

    name = _required_string(payload, "name")
    path = _required_string(payload, "path")
    size = payload.get("size")

    if size is not None and not isinstance(size, int):
        msg = f"Manifest file size for {path} must be an integer when provided"
        raise ValueError(msg)

    return ManifestFile(
        name=name,
        path=path,
        size=size,
        checksum=_optional_string(payload.get("checksum")),
    )
