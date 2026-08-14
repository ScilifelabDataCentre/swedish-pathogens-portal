"""RECOVAC dashboard visualisation (zip of named source workbooks).

Editors upload a single ``.zip`` whose members match the filenames used by the
legacy pandas scripts. Plot builders land in a later commit; this module
validates that zip contract so ``DashboardData`` can accept the upload.
"""

from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path
from typing import Any

from dashboard_visualisation.utils.uploads import (
    SourceFile,
    is_field_file,
    rewind_source_file,
)

REQUIRED_ZIP_STEMS: tuple[str, ...] = (
    "vacc_pop_18plus",
    "vacc_pop_18-59",
    "vacc_pop_60plus",
    "iva_vacc_18plus",
    "iva_vacc_18-59",
    "iva_vacc_60plus",
    "cm_cvd_cardio_vacc_SciLifeLab",
    "cm_dm_vacc_SciLifeLab",
    "cm_resp_dis1_vacc_SciLifeLab",
    "cm_sos_cancer_vacc_SciLifeLab",
    "cm_cvd_cardio_covid_vacc_SciLifeLab",
    "cm_dm_covid_vacc_SciLifeLab",
    "cm_resp_dis1_covid_vacc_SciLifeLab",
    "cm_sos_cancer_covid_vacc_SciLifeLab",
)

_ALLOWED_MEMBER_EXTENSIONS = {".csv", ".xls", ".xlsx"}
_SKIP_NAME_PARTS = {"__macosx"}


def _source_filename(source_file: SourceFile, filename: str) -> str:
    """Return a display filename for the upload."""
    if filename:
        return filename
    return getattr(source_file, "name", "") or ""


def _file_extension(name: str) -> str:
    """Return the lowercased suffix including the leading dot, or empty."""
    if "." not in Path(name).name:
        return ""
    return Path(name).suffix.lower()


def _read_source_bytes(source_file: SourceFile) -> bytes:
    """Read the upload into memory and rewind file-like objects."""
    rewind_source_file(source_file)
    if isinstance(source_file, (str, Path)):
        return Path(source_file).read_bytes()

    if is_field_file(source_file) and getattr(source_file, "name", None):
        with source_file.open("rb") as handle:
            return handle.read()

    if not hasattr(source_file, "read"):
        raise TypeError(f"Unsupported file type for zip reading: {type(source_file)!r}")

    rewind_source_file(source_file)
    raw = source_file.read()
    rewind_source_file(source_file)
    if isinstance(raw, str):
        return raw.encode("utf-8")
    return raw


def _is_skipped_zip_name(member_name: str) -> bool:
    """Return True for directories and junk zip entries (macOS metadata)."""
    path = Path(member_name)
    parts_lower = {part.lower() for part in path.parts}
    if parts_lower & _SKIP_NAME_PARTS:
        return True
    if member_name.endswith("/"):
        return True
    name = path.name
    return not name or name.startswith(".") or name.startswith("__")


def _index_zip_members(archive: zipfile.ZipFile) -> dict[str, str] | str:
    """Map required stems to zip member paths, or return an error string."""
    by_stem: dict[str, str] = {}
    for member_name in archive.namelist():
        if _is_skipped_zip_name(member_name):
            continue
        basename = Path(member_name).name
        extension = _file_extension(basename)
        if extension not in _ALLOWED_MEMBER_EXTENSIONS:
            return (
                f'"{basename}" in the zip is not a supported table '
                f"({', '.join(sorted(_ALLOWED_MEMBER_EXTENSIONS))})."
            )
        stem = Path(basename).stem
        if stem in by_stem:
            return f'The zip contains more than one file for "{stem}".'
        by_stem[stem] = member_name
    return by_stem


def _member_is_readable_table(archive: zipfile.ZipFile, member_name: str) -> str | None:
    """Return an error when a zip member is empty or not a headered table."""
    basename = Path(member_name).name
    try:
        payload = archive.read(member_name)
    except zipfile.BadZipFile as exc:
        return f'Could not read "{basename}" in the zip: {exc}'

    if not payload.strip():
        return f'"{basename}" in the zip is empty.'

    extension = _file_extension(basename)
    if extension != ".csv":
        return None

    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        return f'"{basename}" in the zip is not valid UTF-8 text.'

    try:
        rows = list(csv.reader(io.StringIO(text)))
    except csv.Error as exc:
        return f'Could not parse "{basename}" in the zip: {exc}'

    if len(rows) < 2:
        return f'"{basename}" in the zip must have a header row and at least one data row.'
    return None


def validate_source_file(
    source_file: SourceFile,
    *,
    filename: str = "",
    size_bytes: int | None = None,
) -> str | None:
    """Validate a RECOVAC DashboardData source upload (zip of named tables).

    Used by the registry instead of the generic CSV path. Members may be
    ``.xlsx`` (production) or ``.csv`` with the same stem (tests / CSV export).
    """
    name = _source_filename(source_file, filename)
    if _file_extension(name) != ".zip":
        display = name or "the uploaded file"
        return (
            f'"{display}" is not supported for the RECOVAC dashboard. '
            "Upload a .zip containing the 14 named source workbooks."
        )

    if size_bytes == 0:
        return "The uploaded zip file is empty."

    try:
        raw = _read_source_bytes(source_file)
    except (OSError, TypeError, ValueError) as exc:
        return f"Could not read the uploaded zip: {exc}"

    if not raw:
        return "The uploaded zip file is empty."

    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        return "The uploaded file is not a valid zip archive."

    with archive:
        indexed = _index_zip_members(archive)
        if isinstance(indexed, str):
            return indexed

        missing = [f"{stem}.xlsx" for stem in REQUIRED_ZIP_STEMS if stem not in indexed]
        if missing:
            return "Missing required files in the zip: " + ", ".join(missing)

        for stem in REQUIRED_ZIP_STEMS:
            member_error = _member_is_readable_table(archive, indexed[stem])
            if member_error:
                return member_error

    return None


def generate_figures(source_file: SourceFile) -> dict[str, Any]:
    """Return no figures until the Polars plot builders are added.

    Zip validation already ran at upload time. An empty dict keeps
    ``DashboardData.save`` from crashing; the existing admin warning for
    empty regeneration applies until plot builders land.
    """
    rewind_source_file(source_file)
    return {}
