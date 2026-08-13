"""Upload I/O helpers: source files, hashing, and CSV read/validation."""

import csv
import hashlib
import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

import polars as pl
from django.db.models.fields.files import FieldFile

type SourceFile = str | Path | BinaryIO


def is_field_file(source_file: object) -> bool:
    """Return True when ``source_file`` is a Django storage-backed ``FieldFile``."""
    return isinstance(source_file, FieldFile)


def rewind_source_file(source_file: SourceFile) -> None:
    """Reset a file-like object to the start before reading (no-op for paths)."""
    if isinstance(source_file, (str, Path)):
        return
    if is_field_file(source_file) and getattr(source_file, "name", None):
        return
    if hasattr(source_file, "seek"):
        try:
            source_file.seek(0)
        except ValueError, OSError:
            return


def _resolve_hash_target(file_obj: object) -> object:
    """Return the object whose bytes should be hashed.

    For an uncommitted Django ``FieldFile`` (a new admin upload not yet saved),
    hash the pending upload directly so we do not read the previous file from
    storage by mistake.
    """
    if is_field_file(file_obj):
        committed = getattr(file_obj, "_committed", True)
        pending = getattr(file_obj, "file", None)
        if not committed and pending is not None:
            return pending
    return file_obj


def calculate_file_hash(file_obj: BinaryIO | object) -> str:
    """Return a SHA-256 hex digest for a file-like object or Django ``FieldFile``."""
    file_obj = _resolve_hash_target(file_obj)
    hasher = hashlib.sha256()

    if is_field_file(file_obj) and getattr(file_obj, "name", None):
        with file_obj.storage.open(file_obj.name, "rb") as handle:
            while True:
                chunk = handle.read(65536)
                if not chunk:
                    break
                hasher.update(chunk)
        return hasher.hexdigest()

    if hasattr(file_obj, "chunks"):
        for chunk in file_obj.chunks():
            hasher.update(chunk)
        if hasattr(file_obj, "seek"):
            file_obj.seek(0)
        return hasher.hexdigest()

    if hasattr(file_obj, "read"):
        position = file_obj.tell() if hasattr(file_obj, "tell") else None
        while True:
            chunk = file_obj.read(65536)
            if not chunk:
                break
            hasher.update(chunk)
        if position is not None:
            file_obj.seek(position)
        elif hasattr(file_obj, "seek"):
            file_obj.seek(0)
        return hasher.hexdigest()

    if hasattr(file_obj, "path") and file_obj.path:
        with Path(file_obj.path).open("rb") as handle:
            while True:
                chunk = handle.read(65536)
                if not chunk:
                    break
                hasher.update(chunk)
        return hasher.hexdigest()

    raise TypeError("Unsupported file type for hashing.")


def detect_csv_delimiter(content: str) -> str:
    """Detect comma, semicolon, or tab delimiters (common in EU locale exports)."""
    sample = content[:8192]
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
    except csv.Error:
        header = next((line for line in content.splitlines() if line.strip()), "")
        if header.count(";") >= 2:
            return ";"
        if header.count("\t") >= 2:
            return "\t"
        return ","


def read_source_text(source_file: SourceFile) -> str:
    """Read dashboard source file content as UTF-8 text."""
    if isinstance(source_file, (str, Path)):
        return Path(source_file).read_text(encoding="utf-8-sig")

    if is_field_file(source_file) and getattr(source_file, "name", None):
        with source_file.open("rb") as handle:
            return handle.read().decode("utf-8-sig")

    rewind_source_file(source_file)
    if not hasattr(source_file, "read"):
        raise TypeError(f"Unsupported file type for CSV reading: {type(source_file)!r}")

    raw = source_file.read()
    rewind_source_file(source_file)
    if isinstance(raw, bytes):
        return raw.decode("utf-8-sig")
    return raw


def read_csv_dataframe(
    source_file: SourceFile, columns: list[str] | None = None, null_values: list[str] | None = None
) -> pl.DataFrame:
    """Parse a dashboard CSV upload into a DataFrame."""
    content = read_source_text(source_file)
    delimiter = detect_csv_delimiter(content)
    return pl.read_csv(
        io.BytesIO(content.encode("utf-8")),
        separator=delimiter,
        columns=columns,
        null_values=null_values,
    )


@dataclass
class CsvValidationResult:
    """Result of validating an uploaded CSV file."""

    is_valid: bool
    errors: list[str] = field(default_factory=list)
    row_count: int = 0
    columns: list[str] = field(default_factory=list)


def validate_csv(file: BinaryIO) -> CsvValidationResult:
    """Validate that a file is non-empty UTF-8 CSV with a header and data rows."""
    try:
        content = read_source_text(file)
    except UnicodeDecodeError, TypeError:
        return CsvValidationResult(is_valid=False, errors=["File is not valid UTF-8 text."])

    if not content.strip():
        return CsvValidationResult(is_valid=False, errors=["File is empty."])

    delimiter = detect_csv_delimiter(content)
    try:
        reader = csv.reader(io.StringIO(content), delimiter=delimiter)
        rows = list(reader)
    except csv.Error as exc:
        return CsvValidationResult(is_valid=False, errors=[f"CSV parsing error: {exc}"])

    if len(rows) < 2:
        return CsvValidationResult(
            is_valid=False,
            errors=["CSV must have a header row and at least one data row."],
        )

    return CsvValidationResult(
        is_valid=True,
        row_count=len(rows) - 1,
        columns=[column.strip() for column in rows[0]],
    )
