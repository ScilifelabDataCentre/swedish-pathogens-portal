"""Service functions for exporting item data for the Portal data page."""

from __future__ import annotations

import csv
import io
import json
import logging
from collections.abc import Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

logger = logging.getLogger("pages.portal_data.services")

METABOLIGHTS_WS_BASE = "https://www.ebi.ac.uk/metabolights/ws"
# Keep each generated download URL comfortably under common server/proxy URL
# length limits (typically 2000-8000 chars), even after url-encoding filenames.
MAX_FILE_QUERY_LENGTH = 1800

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


def _metabolights_get(path: str, params: Mapping[str, str] | None = None) -> dict:
    """GET a JSON endpoint from the public MetaboLights web service.

    No authentication is sent or required: every caller here only ever reads
    public-study data.
    """
    url = f"{METABOLIGHTS_WS_BASE}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"
    request = Request(url, headers={"Accept": "application/json"})  # noqa: S310
    with urlopen(request, timeout=15) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def _list_study_directory(accession: str, directory: str | None = None) -> dict:
    """Return the raw 'files/tree' payload for one level of a public study.

    Passing 'directory' lists a named sub-directory (e.g. the raw-data 'FILES'
    folder) instead of the study root. The root call's payload also carries the
    study's 'obfuscationCode', which the download endpoint needs.
    """
    params = {"location": "study", "include_sub_dir": "false"}
    if directory:
        params["directory"] = directory
    return _metabolights_get(f"/studies/{accession}/files/tree", params=params)


def collect_study_download_info(accession: str) -> tuple[str | None, list[str]]:
    """Return (obfuscation_code, file_paths) for a public study.

    ISA-Tab metadata files sit at the study root; raw/derived data files sit one
    directory down (e.g. under 'FILES'). This walks the root and recurses one
    level into any sub-directory entry found there, matching MetaboLights' usual
    study layout - deeper nesting, if a study happens to have any, is not
    followed. The obfuscation code comes back alongside the root listing itself
    - MetaboLights' download endpoint is keyed on it (not on any fixed keyword),
    even for public studies.
    """
    root = _list_study_directory(accession)
    obfuscation_code = root.get("obfuscationCode")

    paths: list[str] = []
    for entry in root.get("study") or []:
        if entry.get("status") == "unreferenced":
            continue
        name = entry.get("file")
        if entry.get("type") == "directory":
            if not name:
                continue
            sub_data = _list_study_directory(accession, directory=name)
            for sub_entry in sub_data.get("study") or []:
                if sub_entry.get("status") == "unreferenced":
                    continue
                if sub_entry.get("type") == "directory":
                    continue
                sub_path = sub_entry.get("relative_path") or sub_entry.get("file")
                if sub_path:
                    paths.append(sub_path)
        else:
            path = entry.get("relative_path") or name
            if path:
                paths.append(path)

    return obfuscation_code, paths


def build_download_urls(
    accession: str, obfuscation_code: str, file_paths: Iterable[str]
) -> list[str]:
    """Build one or more direct MetaboLights zip-download URLs for the given files.

    MetaboLights' download endpoint takes a comma-separated 'file' query
    parameter; for studies with many files that list is split across multiple
    URLs so no single request line gets unreasonably long.
    """
    urls: list[str] = []
    batch: list[str] = []
    batch_length = 0

    def flush_batch() -> None:
        if not batch:
            return
        file_param = quote(",".join(batch), safe="")
        urls.append(
            f"{METABOLIGHTS_WS_BASE}/studies/{accession}/download/"
            f"{obfuscation_code}?file={file_param}"
        )

    for path in file_paths:
        added_length = len(quote(path, safe="")) + 1  # +1 for the comma separator
        if batch and batch_length + added_length > MAX_FILE_QUERY_LENGTH:
            flush_batch()
            batch = []
            batch_length = 0
        batch.append(path)
        batch_length += added_length

    flush_batch()
    return urls


def _resolve_one_study(accession: str) -> dict:
    """Resolve a single study to its direct MetaboLights download URL(s)."""
    result: dict = {"accession": accession, "urls": [], "error": None}
    try:
        obfuscation_code, file_paths = collect_study_download_info(accession)
    except (HTTPError, URLError, TimeoutError, ValueError, OSError) as err:
        logger.warning("Failed to list files for %s: %s", accession, err)
        result["error"] = "Could not reach MetaboLights to list this study's files."
        return result

    if not obfuscation_code:
        logger.warning("No obfuscation code returned by MetaboLights for %s", accession)
        result["error"] = "MetaboLights did not return a download code for this study."
        return result

    if not file_paths:
        result["error"] = "No downloadable files were found for this study."
        return result

    result["urls"] = build_download_urls(accession, obfuscation_code, file_paths)
    return result


def resolve_bulk_download(accessions: Iterable[str]) -> list[dict]:
    """Resolve each selected study to one or more direct MetaboLights download URLs.

    Every URL points straight at MetaboLights' own server: the end user's browser
    downloads the resulting zip(s) directly and no study data passes through our
    server. Studies are resolved concurrently since each one needs its own
    (small, metadata-only) round trip to MetaboLights.
    """
    accessions = list(accessions)
    with ThreadPoolExecutor(max_workers=min(8, len(accessions)) or 1) as pool:
        results = list(pool.map(_resolve_one_study, accessions))
    by_accession = {r["accession"]: r for r in results}
    return [by_accession[accession] for accession in accessions]


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
