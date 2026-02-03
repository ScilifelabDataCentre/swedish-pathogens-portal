"""Django views for browsing and exporting portal data mounted on the data PVC."""

from __future__ import annotations

import logging
import mimetypes
import os
import re
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from django.conf import settings
from django.core.cache import cache
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

logger = logging.getLogger("pages.portal_data.views")

SUPPORTED_TYPES = {
    "metabolomics": {
        "label": "Metabolomics",
        "default_facets": [
            "year",
            "platforms",
            "technology",
            "factors",
            "design_types",
            "repository",
        ],
    },
}

# Root where the PVC is mounted in the web container
DATA_ROOT = Path(settings.DATASETS_ROOT).resolve()

ACCESSION_RE = re.compile(r"^MTBLS\d+$")

# -------------------------------------------------------------------
# Views
# -------------------------------------------------------------------


class DataTypeList(View):
    """List available studies for a given data type with faceted search."""

    template_name = "portal_data/index.html"

    def get(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        """Build template context for the study list page."""
        datatype = str(kwargs["datatype"])
        ctx: dict[str, object] = {}

        if datatype not in SUPPORTED_TYPES:
            ctx["error"] = f"Unknown data type: {datatype}"
            return render(request, self.template_name, ctx)

        q = request.GET.get("q", "").strip()
        page = max(int(request.GET.get("page", "1")), 1)
        size = max(int(request.GET.get("size", "25")), 1)
        facet_names = request.GET.getlist("facet") or SUPPORTED_TYPES[datatype]["default_facets"]

        filter_fields = facet_names
        filters = {f: request.GET.getlist(f) for f in filter_fields if request.GET.getlist(f)}

        # Load from PVC
        all_items = _load_all_items(datatype)

        # Apply filters + search
        filtered_items = _apply_search_and_filters(all_items, q, filters)

        # Build facets from the current result set (so facets update when search/filters change)
        facets = _build_facets(
            items=filtered_items,
            facet_names=facet_names,
            filters=filters,
            datatype=datatype,  # from view / query_data_backend
            use_cache=(not q and not filters),
        )

        # Simple paging
        start = (page - 1) * size
        end = start + size
        page_items = filtered_items[start:end]

        has_facets = any(bool(buckets) for buckets in facets.values())
        ctx["has_facets"] = has_facets

        ctx.update(
            {
                "datatype": datatype,
                "datatype_label": SUPPORTED_TYPES[datatype]["label"],
                "query": q,
                "filters": filters,
                "facets": facets,
                "items": page_items,
                "total": len(filtered_items),
                "page": page,
                "size": size,
            }
        )
        return render(request, self.template_name, ctx)


class StudyFiles(View):
    """Render a simple file browser for a study directory on the PVC.

    Logs helpful debugging info if something goes wrong.
    """

    def get(
        self, request: HttpRequest, accession: str, *args: object, **kwargs: object
    ) -> HttpResponse:
        """Render a list of files available under the given study accession."""
        datatype = str(kwargs["datatype"])
        if datatype not in SUPPORTED_TYPES:
            raise Http404("Unknown data type")

        if not ACCESSION_RE.match(accession):
            raise Http404("Invalid accession")

        # Ensure DATA_ROOT exists on the cluster
        if not DATA_ROOT.is_dir():
            logger.error("DATA_ROOT does not exist or is not a directory: %s", DATA_ROOT)
            raise Http404("Study storage not available")

        study_dir = DATA_ROOT / accession
        if not study_dir.is_dir():
            logger.warning("Study directory not present: %s", study_dir)
            raise Http404("Study not found on this node")

        try:
            files = _list_study_files(study_dir)
        except Exception as err:
            logger.exception("Unexpected error listing files for %s/%s", datatype, accession)
            raise Http404("Could not list files") from err

        return render(
            request,
            "portal_data/study_files.html",
            {
                "datatype": datatype,
                "accession": accession,
                "files": files,
            },
        )


class DownloadStudyFile(View):
    """Stream a single file from the study directory.

    Protects against path traversal by resolving the requested path and ensuring it is
    inside the study directory. Logs errors to help diagnose cluster 500s.
    """

    def get(
        self,
        request: HttpRequest,
        accession: str,
        relpath: str,
        *args: object,
        **kwargs: object,
    ) -> HttpResponse:
        """Stream a single file from the given study.

        Validating that the path stays within the study directory.
        """
        datatype = str(kwargs["datatype"])
        if datatype not in SUPPORTED_TYPES:
            raise Http404("Unknown data type")

        if not ACCESSION_RE.match(accession):
            raise Http404("Invalid accession")

        # relpath may be URL-encoded in the URL; decode it once
        relpath = unquote(relpath)
        requested_path = Path(relpath)

        if requested_path.is_absolute():
            logger.warning("Rejecting absolute relpath request: %s", relpath)
            raise Http404("Invalid file path")

        # Ensure DATA_ROOT exists
        if not DATA_ROOT.is_dir():
            logger.error("DATA_ROOT not available: %s", DATA_ROOT)
            raise Http404("Study storage not available")

        study_dir = DATA_ROOT / accession
        if not study_dir.is_dir():
            logger.warning("Study directory missing for download: %s", study_dir)
            raise Http404("Study not found on this node")

        try:
            # Use resolve(strict=False) to avoid raising for strange mount points.
            # Then verify the resolved path remains inside the study directory.
            candidate = (study_dir / requested_path).resolve(strict=False)
            study_dir_resolved = study_dir.resolve(strict=False)
        except Exception as err:
            # If resolving fails for some reason, log and abort
            logger.exception("Path resolution failed for %s %s", study_dir, relpath)
            raise Http404("Invalid file path") from err

        # Ensure the requested file is under the study directory (path traversal protection).
        if not candidate.is_relative_to(study_dir_resolved):
            logger.warning(
                "Path traversal or invalid path detected. study_dir=%s candidate=%s",
                study_dir_resolved,
                candidate,
            )
            raise Http404("Invalid file path")

        if not candidate.exists() or not candidate.is_file():
            logger.warning("Requested file not found or not a file: %s", candidate)
            raise Http404("File not found")

        # Determine content type
        content_type, _ = mimetypes.guess_type(str(candidate))
        if content_type is None:
            content_type = "application/octet-stream"

        stack = ExitStack()
        try:
            f = stack.enter_context(candidate.open("rb"))
        except Exception as err:
            stack.close()
            logger.exception("Failed to open file for streaming: %s", candidate)
            # Return 404 rather than 500 to avoid leaking details to users, but log the exception.
            raise Http404("File not accessible") from err

        response = FileResponse(
            f,
            as_attachment=True,
            filename=candidate.name,
            content_type=content_type,
        )

        # Ensure file closed when response is closed
        original_close = response.close

        def cleanup_close(*cargs: object, **ckwargs: object) -> None:
            try:
                original_close(*cargs, **ckwargs)
            finally:
                stack.close()

        response.close = cleanup_close
        return response


# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------


def _iter_study_dirs(datatype: str) -> list[Path]:
    """Yield directories that look like MetaboLights studies.

    With your current layout this will hit:
        /datasets/MTBLS1051
        /datasets/MTBLS1464
        ...
    """
    if datatype != "metabolomics":
        return []

    if not DATA_ROOT.exists():
        return []

    candidates: dict[str, Path] = {}
    for p in DATA_ROOT.iterdir():
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


def _load_all_items(datatype: str) -> list[dict]:
    """Load all public metabolomics datasets from the PVC.

    Each item dict keeps the old keys (id, repository, repo_url, etc.)
    so facets/export keep working, but now also has richer metadata.
    """
    if datatype != "metabolomics":
        return []

    if not DATA_ROOT.is_dir():
        return []

    items: list[dict] = []

    for study_dir in sorted(DATA_ROOT.iterdir(), key=lambda p: p.name):
        if not study_dir.is_dir():
            continue

        accession = study_dir.name
        if not ACCESSION_RE.match(accession):
            # Skip helper dirs like MTBLS_data, fetch_metabolights.sh, targets.txt
            continue

        inv_path = _find_investigation_file(study_dir)
        meta = _parse_investigation_file(inv_path)

        title = meta.get("study_title") or accession
        description = meta.get("study_description") or ""
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


def _apply_search_and_filters(
    items: list[dict],
    query: str,
    filters: dict[str, list[str]],
) -> list[dict]:
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


def _build_facets(
    items: list[dict[str, Any]],
    facet_names: list[str],
    filters: dict[str, list[str]] | None,
    datatype: str,
    *,
    use_cache: bool = True,
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

    # Include datatype and facet_names in the cache key
    cache_key = f"facets_{datatype}_{hash(str(sorted(facet_names)))}"
    if use_cache:
        cached: dict[str, list[dict[str, Any]]] | None = cache.get(cache_key)
        if cached is not None:
            # Update "checked" flags based on current filters before returning
            for facet, buckets in cached.items():
                active_values = set(filters.get(facet, []))
                for bucket in buckets:
                    bucket["checked"] = str(bucket["value"]) in active_values
            return cached

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

    if use_cache:
        cache.set(cache_key, facets, timeout=3600)
    return facets


def _find_investigation_file(study_dir: Path) -> Path | None:
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


def _parse_investigation_file(path: Path) -> dict[str, object]:
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


# ---- Download helper functions ---------------------------------------------------


def _list_study_files(study_dir: Path) -> list[dict[str, Any]]:
    """List all files within a study directory.

    Returns dictionaries containing relative path, size and modification time.
    Directories are not returned (files only). Skips entries that cannot be stat'ed.
    """
    files: list[dict] = []
    try:
        for root, _, filenames in os.walk(study_dir):
            for fn in filenames:
                full = Path(root) / fn
                try:
                    # produce a relative path with forward slashes
                    rel = str(full.relative_to(study_dir)).replace(os.sep, "/")
                    stat = full.stat()
                except (OSError, ValueError):
                    # skip files we can't access or relativize
                    logger.debug("Skipping file during listing: %s", full, exc_info=True)
                    continue

                files.append(
                    {
                        "relpath": rel,
                        "name": fn,
                        "size": stat.st_size,
                        "mtime": stat.st_mtime,
                    }
                )
    except Exception:
        logger.exception("Error walking study_dir %s", study_dir)
    # sort by path for stable listing
    files.sort(key=lambda f: f["relpath"])
    return files
