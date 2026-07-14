"""Validation for DINA Liver Resource DE file uploads."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

from dashboard_visualisation.liver_resource.computation import parse_de_file

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MIN_GENE_ROWS = 100
REQUIRED_COLUMNS = ("logFC", "adj.P.Val")
ENSEMBL_ID_PATTERN = re.compile(r"^ENSG\d+$")

type UploadSource = str | Path | BinaryIO


@dataclass(frozen=True)
class DeValidationResult:
    """Outcome of validating an uploaded DE file."""

    is_valid: bool
    errors: tuple[str, ...] = field(default_factory=tuple)
    de_data: dict | None = None
    gene_count: int = 0


def validate_de_upload(
    source: UploadSource,
    *,
    size_bytes: int | None = None,
) -> DeValidationResult:
    """Validate an uploaded DE file and return parsed data when valid."""
    if size_bytes is not None and size_bytes > MAX_UPLOAD_BYTES:
        return DeValidationResult(
            is_valid=False,
            errors=(
                f"File is too large ({size_bytes // (1024 * 1024)} MB). "
                f"Maximum allowed size is {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
            ),
        )

    try:
        de_data = parse_de_file(source)
    except UnicodeDecodeError:
        return DeValidationResult(
            is_valid=False,
            errors=("File must be UTF-8 encoded plain text.",),
        )
    except OSError as exc:
        return DeValidationResult(is_valid=False, errors=(f"Could not read file: {exc}",))

    errors = validate_de_data(de_data)
    if errors:
        return DeValidationResult(is_valid=False, errors=tuple(errors))

    return DeValidationResult(
        is_valid=True,
        de_data=de_data,
        gene_count=len(de_data["genes"]),
    )


def validate_de_data(de_data: dict) -> list[str]:
    """Return field-level validation errors for parsed DE data."""
    errors: list[str] = []
    header = de_data.get("header", [])
    genes = de_data.get("genes", [])

    if not header:
        errors.append("File is empty or missing a header row.")
        return errors

    missing_columns = [column for column in REQUIRED_COLUMNS if column not in header]
    if missing_columns:
        errors.append(
            "Missing required columns: "
            + ", ".join(missing_columns)
            + ". Expected columns include logFC and adj.P.Val."
        )

    if len(genes) < MIN_GENE_ROWS:
        errors.append(
            f"File contains only {len(genes)} gene rows. "
            f"Upload the full gene list from your experiment (at least {MIN_GENE_ROWS} rows)."
        )

    if len(genes) != len(set(genes)):
        errors.append("Duplicate Ensembl gene IDs found. Each gene must appear only once.")

    invalid_ids = [gene_id for gene_id in genes[:50] if not ENSEMBL_ID_PATTERN.match(gene_id)]
    if invalid_ids:
        sample = invalid_ids[0]
        errors.append(
            f"Gene IDs must be human Ensembl IDs (e.g. ENSG00000000003). Invalid example: {sample}."
        )

    if genes and not errors:
        sample_gene = genes[0]
        sample_row = de_data["data"][sample_gene]
        if sample_row.get("logFC") is None:
            errors.append("Column logFC must contain numeric values.")
        if sample_row.get("adj.P.Val") is None:
            errors.append("Column adj.P.Val must contain numeric values.")

    return errors
