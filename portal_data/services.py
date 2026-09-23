"""Service functions for exporting item data for the Portal data page."""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import nh3
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

_ALLOWED_TAGS = {"p", "br", "strong", "em", "a", "ul", "ol", "li"}
_ALLOWED_ATTRIBUTES: dict[str, set[str]] = {"a": {"href", "target"}}


def _clean_html(raw: str) -> str:
    """Strip unsafe tags from HTML, keeping only a safe presentational subset."""
    sanitised_html = nh3.clean(
        raw, tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRIBUTES, link_rel=None
    )
    if sanitised_html:
        sanitised_html = re.sub(
            r"<p>\s*(<br\s*/?>\s*)*</p>", "", sanitised_html, flags=re.IGNORECASE
        )
    return sanitised_html


@dataclass(frozen=True)
class DataTypeConfig:
    """Configuration for a supported portal data type."""

    label: str
    default_facets: tuple[str, ...]


SUPPORTED_TYPES: dict[str, DataTypeConfig] = {
    "metabolomics": DataTypeConfig(
        label="Metabolomics",
        default_facets=(
            "year",
            "platforms",
            "technology",
            "factors",
            "design_types",
            "repository",
        ),
    ),
}

ACCESSION_RE = re.compile(r"^MTBLS\d+$")


def get_datatype_config(datatype: str) -> DataTypeConfig | None:
    """Return configuration for a supported data type, if available."""
    return SUPPORTED_TYPES.get(datatype)


def get_dataset_listing(
    *,
    datatype: str,
    query: str,
    filters: dict[str, list[str]],
    facet_names: list[str],
) -> dict[str, Any]:
    """Return filtered studies and facets for the listing page."""
    all_items = load_all_items(datatype)

    searched_items = apply_text_search(all_items, query)
    filtered_items = apply_facet_filters(searched_items, filters)

    facets = build_facets(
        items=searched_items,
        facet_names=facet_names,
        filters=filters,
        datatype=datatype,
    )

    return {
        "items": filtered_items,
        "facets": facets,
        "has_facets": any(bool(buckets) for buckets in facets.values()),
    }


def get_data_root() -> Path:
    """Return the configured datasets root.

    Calculated at call time so tests and environment overrides work correctly.
    """
    return Path(settings.DATASETS_ROOT).expanduser().resolve()


# Fields we include in exports:
# - key in the item dict
# - human-readable column header
EXPORT_FIELDS: list[tuple[str, str]] = [
    ("id", "Accession"),
    ("title", "Title"),
    ("pathogen", "Pathogen"),
    ("matrix", "Matrix"),
    ("instrument", "Instrument"),
    ("country", "Country"),
    ("year", "Year"),
    ("repository", "Repository"),
    ("repo_url", "Repository URL"),
]


def _normalize_items(items: Iterable[Mapping[str, object]]) -> list[dict]:
    """Normalize view items for export.

    Take whatever dicts the view passes in and return a list of clean dicts
    containing only the fields we want to export, with None -> "".
    """

    normalized: list[dict] = []

    for it in items:
        row: dict[str, object] = {}
        for key, _ in EXPORT_FIELDS:
            value = it.get(key, "")
            if value is None:
                value = ""
            row[key] = value
        normalized.append(row)

    return normalized


def build_export_tsv(
    items: Iterable[Mapping[str, object]],
    default_filename: str = "export.tsv",
) -> tuple[str, str, str]:
    """Build a TSV export from a sequence of item dicts.

    Returns: (content_str, filename, content_type)
    """

    rows = _normalize_items(items)

    buf = io.StringIO()
    writer = csv.writer(buf, delimiter="\t")

    # Header row
    writer.writerow([label for _, label in EXPORT_FIELDS])

    # Data rows
    for row in rows:
        writer.writerow([row.get(key, "") for key, _ in EXPORT_FIELDS])

    content = buf.getvalue()
    buf.close()

    filename = default_filename or "export.tsv"
    content_type = "text/tab-separated-values; charset=utf-8"
    return content, filename, content_type


def build_export_json(
    items: Iterable[Mapping[str, object]],
    default_filename: str = "export.json",
) -> tuple[str, str, str]:
    """Build a JSON export from a sequence of item dicts.

    Returns: (content_str, filename, content_type)
    """

    rows = _normalize_items(items)
    content = json.dumps(rows, indent=2, ensure_ascii=False)

    filename = default_filename or "export.json"
    content_type = "application/json; charset=utf-8"
    return content, filename, content_type


def _iter_study_dirs(datatype: str) -> list[Path]:
    """Yield directories that look like MetaboLights studies.

    With your current layout this will hit:
        /datasets/MTBLS1051
        /datasets/MTBLS1464
        ...
    """
    if datatype != "metabolomics":
        return []

    data_root = get_data_root()
    if not data_root.exists():
        return []

    candidates: dict[str, Path] = {}
    for p in data_root.iterdir():
        if not p.is_dir():
            continue
        name = p.name
        if not name.startswith("MTBLS"):
            continue
        # Only accept IDs like MTBLS1234, MTBLS690, etc.
        suffix = name[5:]
        if not suffix.isdigit():
            continue
        candidates[name] = p

    return [candidates[name] for name in sorted(candidates)]


def load_all_items(datatype: str) -> list[dict]:
    """Load all public metabolomics datasets from the PVC.

    Each item dict keeps the old keys (id, repository, repo_url, etc.)
    so facets/export keep working, but now also has richer metadata.
    """
    if datatype != "metabolomics":
        return []

    data_root = get_data_root()
    if not data_root.is_dir():
        return []

    items = []

    for study_dir in sorted(data_root.iterdir(), key=lambda p: p.name):
        if not study_dir.is_dir():
            continue

        accession = study_dir.name
        if not ACCESSION_RE.match(accession):
            # Skip helper dirs like MTBLS_data, fetch_metabolights.sh, targets.txt
            continue

        inv_path = find_investigation_file(study_dir)
        meta = parse_investigation_file(inv_path)

        title = meta.get("study_title") or accession
        description = _clean_html(meta.get("study_description") or "")
        public_release = meta.get("study_public_release_date")
        year = None
        if isinstance(public_release, str) and len(public_release) >= 4:
            year = public_release[:4]

        # tags may not exist in the ISA metadata; provide an empty list by default
        tags = meta.get("tags", [])

        item = {
            # IDs used by bulk selection / export
            "id": accession,
            "accession": accession,
            # Old fields the template already uses
            "title": title,
            "pathogen": "",  # not available in ISA; left empty for now
            "matrix": "",
            "instrument": "",
            "country": "",
            "year": year,
            "repository": "MetaboLights",
            "repo_accession": accession,
            "repo_url": f"https://www.ebi.ac.uk/metabolights/{accession}",
            # New metadata from i_Investigation.txt
            "description": description,
            "tags": tags,
            "public_release_date": public_release,
            "submission_date": meta.get("study_submission_date"),
            "license": meta.get("license"),
            "factors": meta.get("factors", []),
            "design_types": meta.get("design_types", []),
            "platforms": meta.get("platforms", []),
            "publication_title": meta.get("publication_title"),
            "publication_doi": meta.get("publication_doi"),
            "publication_authors": meta.get("publication_authors"),
            "technology": meta.get("technology"),
            # Local PVC location (useful for debugging or later features)
            "local_path": str(study_dir),
        }

        items.append(item)

    return items


def apply_search_and_filters(
    items: list[dict],
    query: str,
    filters: dict[str, list[str]],
) -> list[dict]:
    """Apply text search and facet filters to dataset listing items."""
    # Text search
    if query:
        q = query.lower()

        def matches_text(it: dict[str, Any]) -> bool:
            # title and id (existing behavior)
            if q in str(it.get("title", "")).lower() or q in str(it.get("id", "")).lower():
                return True
            # description
            if q in str(it.get("description", "")).lower():
                return True
            # tags (could be list or string)
            tags = it.get("tags", [])
            if isinstance(tags, str):
                if q in tags.lower():
                    return True
            else:
                for t in tags:
                    if q in str(t).lower():
                        return True
            return False

        items = [it for it in items if matches_text(it)]

    # Facet filters
    for field, values in filters.items():
        if not values:
            continue
        values_set = {str(v) for v in values}

        def matches_filter(
            it: dict[str, Any],
            *,
            _field: str = field,
            _values_set: set[str] = values_set,
        ) -> bool:
            """Check if item matches the filter for this field."""
            field_value = it.get(_field)
            if field_value is None:
                return False
            # Handle list values (e.g., platforms, factors, design_types)
            if isinstance(field_value, list):
                # If any value in the list matches any filter value, include the item
                return any(str(v) in _values_set for v in field_value if v is not None and v != "")
            else:
                # Scalar value (e.g., year, repository, technology)
                return str(field_value) in _values_set

        items = [it for it in items if matches_filter(it)]

    return items


def build_facets(
    items: list[dict[str, Any]],
    facet_names: list[str],
    filters: dict[str, list[str]] | None,
    datatype: str,
) -> dict[str, list[dict[str, Any]]]:
    """Build facet buckets for a given datatype.

    items:
        Full list of items (dicts) for this datatype.
    facet_names:
        Keys in each item to facet on, e.g. ["pathogen", "country", "year"].
    filters:
        Currently active filters (used to mark 'checked' buckets).
    datatype:
        Slug/name of the datatype, e.g. "metabolomics".
    """
    # Normalise inputs
    items = list(items)
    filters = filters or {}

    facets: dict[str, list[dict[str, Any]]] = {}

    for facet in facet_names:
        counts: dict[str, int] = {}

        for it in items:
            value = it.get(facet)
            if value in (None, "", [], {}):
                continue

            # Handle list-valued fields (e.g. platforms, design_types)
            if isinstance(value, list):
                for v in value:
                    if v not in (None, ""):
                        key = str(v)
                        counts[key] = counts.get(key, 0) + 1
            else:
                key = str(value)
                counts[key] = counts.get(key, 0) + 1

        buckets = list(counts.items())

        # For the "year" facet prefer numeric descending (most recent first),
        # but only if all keys look like integers; otherwise fall back to
        # string-based descending sort. All other facets are sorted ascending.
        if facet == "year" and buckets:

            def _is_integer_string(s: str) -> bool:
                return re.fullmatch(r"-?\d+", s) is not None

            if all(_is_integer_string(k) for k, _ in buckets):
                buckets.sort(key=lambda kv: int(kv[0]), reverse=True)
            else:
                buckets.sort(key=lambda kv: kv[0], reverse=True)
        else:
            buckets.sort(key=lambda kv: kv[0])

        active_values = set(filters.get(facet, []))
        facets[facet] = [
            {"value": value, "count": count, "checked": str(value) in active_values}
            for value, count in buckets
        ]

    return facets


def find_investigation_file(study_dir: Path) -> Path | None:
    """Prefer the latest investigation file under METADATA_REVISIONS, falling back to top-level."""
    rev_root = study_dir / "METADATA_REVISIONS"
    if rev_root.is_dir():
        rev_dirs = sorted(
            [p for p in rev_root.iterdir() if p.is_dir()],
            key=lambda p: p.name,
        )
        for rev_dir in reversed(rev_dirs):
            candidate = rev_dir / "i_Investigation.txt"
            if candidate.is_file():
                return candidate

    candidate = study_dir / "i_Investigation.txt"
    if candidate.is_file():
        return candidate

    return None


def parse_investigation_file(path: Path) -> dict[str, object]:
    """Very simple ISA-tab parser focusing on the STUDY rows we care about."""
    meta: dict[str, object] = {}

    if path is None or not path.is_file():
        return meta

    try:
        with path.open(encoding="utf-8") as f:
            for raw in f:
                line = raw.rstrip("\n")
                if not line or "\t" not in line:
                    continue

                cols = [c.strip() for c in line.split("\t")]
                key = cols[0]
                values = [c for c in cols[1:] if c]

                if not values:
                    continue

                if key == "Study Title":
                    meta["study_title"] = values[0]
                elif key == "Study Description":
                    meta["study_description"] = values[0]
                elif key == "Study Submission Date":
                    meta["study_submission_date"] = values[0]
                elif key == "Study Public Release Date":
                    meta["study_public_release_date"] = values[0]
                elif key == "Comment[License]":
                    meta["license"] = values[0]
                elif key == "Study Publication Title":
                    meta["publication_title"] = values[0]
                elif key == "Study Publication DOI":
                    meta["publication_doi"] = values[0]
                elif key == "Study Publication Author List":
                    meta["publication_authors"] = values[0]
                elif key == "Study Factor Name":
                    meta["factors"] = values
                elif key == "Study Design Type":
                    meta["design_types"] = values
                elif key == "Study Assay Technology Platform":
                    meta["platforms"] = values
                elif key == "Study Assay Technology Type":
                    meta["technology"] = values[0]
    except FileNotFoundError:
        pass

    return meta


def list_study_files(study_dir: Path) -> list[dict[str, Any]]:
    """Return metadata for files contained in a study directory."""
    files: list[dict[str, Any]] = []

    for root, _, filenames in os.walk(study_dir):
        for filename in filenames:
            full = Path(root) / filename

            try:
                relpath = str(full.relative_to(study_dir)).replace(os.sep, "/")
                stat = full.stat()
            except (OSError, ValueError) as err:
                logger.debug(
                    f"Skipping file during listing: '{full}' due to Error: {err}", exc_info=True
                )
                continue

            files.append(
                {
                    "relpath": relpath,
                    "name": filename,
                    "size": stat.st_size,
                    "mtime": datetime.fromtimestamp(
                        stat.st_mtime,
                        tz=timezone.get_current_timezone(),
                    ),
                }
            )

    files.sort(key=lambda file: file["relpath"])
    return files


def _dedupe_filename(filename: str, seen: dict[str, int]) -> str:
    """Disambiguate a repeated suggested filename within one study's entries.

    Mirrors how browsers themselves handle a name collision, so a second file
    that would otherwise overwrite the first becomes 'name (1).ext' instead.
    """
    count = seen.get(filename, 0)
    seen[filename] = count + 1
    if count == 0:
        return filename
    stem, dot, ext = filename.rpartition(".")
    return f"{stem} ({count}){dot}{ext}" if dot else f"{filename} ({count})"


def _categorize_relpath(relpath: str) -> str:
    """Classify a study file as 'metadata' (study root) or 'raw' (any subdirectory).

    ISA-Tab metadata files (i_/s_/a_/m_ prefixed) sit directly in the study
    directory; raw/derived data files sit in a subdirectory such as RAW_FILES,
    DERIVED_FILES or FILES, so a relpath containing "/" is raw/derived data.
    """
    return "raw" if "/" in relpath else "metadata"


def resolve_bulk_download(accessions: Iterable[str]) -> list[dict[str, Any]]:
    """Resolve each selected study to its local files, grouped by category.

    Every file already lives on this node's PVC-mounted DATASETS_ROOT, so this
    reuses the same listing used by the single-study file browser
    (list_study_files) - no external calls are made. Each file entry also
    carries a suggested save-as filename prefixed with the study accession,
    since plain filenames like 'i_Investigation.txt' repeat across studies and
    a browser saving several studies' files into one flat Downloads folder
    needs some other way to keep them straight.
    """
    data_root = get_data_root()
    results: list[dict[str, Any]] = []

    for accession in accessions:
        result: dict[str, Any] = {
            "accession": accession,
            "metadata_files": [],
            "raw_files": [],
            "error": None,
        }

        if not ACCESSION_RE.match(accession):
            result["error"] = "Invalid accession."
            results.append(result)
            continue

        study_dir = data_root / accession
        if not study_dir.is_dir():
            result["error"] = "Study not found on this node."
            results.append(result)
            continue

        try:
            files = list_study_files(study_dir)
        except OSError as err:
            logger.warning("Failed to list files for %s: %s", accession, err)
            result["error"] = "Could not list this study's files."
            results.append(result)
            continue

        if not files:
            result["error"] = "No downloadable files were found for this study."
            results.append(result)
            continue

        seen: dict[str, int] = {}
        for f in files:
            entry = {
                "relpath": f["relpath"],
                "filename": _dedupe_filename(f"{accession}_{f['name']}", seen),
            }
            if _categorize_relpath(f["relpath"]) == "metadata":
                result["metadata_files"].append(entry)
            else:
                result["raw_files"].append(entry)

        results.append(result)

    return results


def apply_text_search(items: list[dict], query: str) -> list[dict]:
    """Apply text search to dataset listing items."""
    if not query:
        return items

    q = query.lower()

    def matches_text(it: dict[str, Any]) -> bool:
        if q in str(it.get("title", "")).lower():
            return True

        if q in str(it.get("id", "")).lower():
            return True

        if q in str(it.get("accession", "")).lower():
            return True

        if q in str(it.get("description", "")).lower():
            return True

        tags = it.get("tags", [])
        if isinstance(tags, str):
            return q in tags.lower()

        return any(q in str(tag).lower() for tag in tags)

    return [it for it in items if matches_text(it)]


def apply_facet_filters(
    items: list[dict],
    filters: dict[str, list[str]],
) -> list[dict]:
    """Apply selected facet filters to dataset listing items."""
    if not filters:
        return items

    filtered_items = items

    for field, values in filters.items():
        if not values:
            continue

        values_set = {str(v) for v in values}

        def matches_filter(
            it: dict[str, Any],
            *,
            _field: str = field,
            _values_set: set[str] = values_set,
        ) -> bool:
            field_value = it.get(_field)

            if field_value is None:
                return False

            if isinstance(field_value, list):
                return any(str(v) in _values_set for v in field_value if v is not None and v != "")

            return str(field_value) in _values_set

        filtered_items = [it for it in filtered_items if matches_filter(it)]

    return filtered_items
