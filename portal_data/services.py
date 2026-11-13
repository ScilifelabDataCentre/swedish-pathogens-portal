"""Service functions for exporting item data for the Portal data page."""

from __future__ import annotations

import csv
import errno
import hashlib
import io
import json
import logging
import os
import re
from collections.abc import Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import nh3
from django.conf import settings
from django.core.cache import cache

from cms.services.api_client import fetch_json
from portal_data.metabolights.europepmc import PAPERS_OUTPUT_CSV
from portal_data.metabolights.pathogens import load_pathogen_map, pathogens_by_accession

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
            "organisms",
            "pathogens",
            "year",
            "technology",
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


# Folder inside the datasets root where `manage.py metabolights_search` keeps its
# outputs (result CSVs and the targets.txt that metabolights_fetch reads). It sits
# next to the studies so it lives on the same persistent volume, and its name
# doesn't look like an accession, so the study listing never picks it up.
METABOLIGHTS_SEARCH_DIRNAME = "metabolights_search"


def get_metabolights_work_dir() -> Path:
    """Return the default working directory of the MetaboLights study finder."""
    return get_data_root() / METABOLIGHTS_SEARCH_DIRNAME


def ensure_writable_dir(path: Path) -> None:
    """Create path if needed, and check this process can write into it.

    Lets a job that will write there fail at once with one clear error -- e.g.
    on a read-only mount -- instead of after its slow part, or once per item.

    Raises:
        OSError: if the directory can't be created, or PermissionError if it
            exists but isn't writable.
    """
    path.mkdir(parents=True, exist_ok=True)
    if not os.access(path, os.W_OK):
        raise PermissionError(errno.EACCES, "Directory is not writable", str(path))


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


def _items_cache_key(datatype: str, data_root: Path) -> str:
    """Build the cache key for ``load_all_items``.

    The datasets root's mtime is part of the key, so adding or removing a
    study directory (e.g. when manage.py metabolights_fetch adds new studies) invalidates
    the cache immediately, and so is the mtime of the search results the
    pathogens come from, so a new metabolights_search run shows straight away.
    In-place edits to files inside an existing study directory don't touch the
    root's mtime; those are picked up when the entry expires
    (``PORTAL_DATA_CACHE_TIMEOUT``).
    """
    root_hash = hashlib.sha1(str(data_root).encode(), usedforsecurity=False).hexdigest()[:12]
    mtime_ns = data_root.stat().st_mtime_ns
    papers_csv = _search_papers_csv(data_root)
    papers_mtime_ns = papers_csv.stat().st_mtime_ns if papers_csv.is_file() else 0
    return f"portal_data:items:{datatype}:{root_hash}:{mtime_ns}:{papers_mtime_ns}"


def _search_papers_csv(data_root: Path) -> Path:
    """Return where metabolights_search writes its papers CSV under this root."""
    return data_root / METABOLIGHTS_SEARCH_DIRNAME / PAPERS_OUTPUT_CSV


def load_all_items(datatype: str) -> list[dict]:
    """Load all public metabolomics datasets from the PVC, with caching.

    Parsing every study's investigation file takes seconds once there are
    thousands of studies, so the result is cached rather than rebuilt on
    every listing request (search, filter and pagination all hit this).
    """
    if datatype != "metabolomics":
        return []

    data_root = get_data_root()
    if not data_root.is_dir():
        return []

    key = _items_cache_key(datatype, data_root)
    items = cache.get(key)
    if items is None:
        items = _scan_all_items(data_root)
        cache.set(key, items, timeout=settings.PORTAL_DATA_CACHE_TIMEOUT)
    return items


def _scan_all_items(data_root: Path) -> list[dict]:
    """Build listing items by parsing each study's investigation file.

    Each item dict keeps the old keys (id, repository, repo_url, etc.)
    so facets/export keep working, but now also has richer metadata.
    Pathogens come from the latest metabolights_search results, if any.
    """
    items = []
    study_pathogens = pathogens_by_accession(_search_papers_csv(data_root), load_pathogen_map())

    for study_dir in sorted(data_root.iterdir(), key=lambda p: p.name):
        if not study_dir.is_dir():
            continue

        accession = study_dir.name
        if not ACCESSION_RE.match(accession):
            # Skip anything that isn't a study folder, e.g. MTBLS_data or stray files
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
            # From the s_*.txt sample file(s), not the investigation file
            "organisms": parse_sample_organisms(study_dir),
            # From the keywords that matched this study's papers in the search
            "pathogens": study_pathogens.get(accession, []),
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


# Values of Characteristics[Organism] that label control samples (blanks, growth
# medium, solvent) or missing data rather than an organism. Compared lowercased.
_NON_ORGANISM_VALUES = frozenset(
    {
        "blank",
        "medium",
        "growth medium",
        "solvent",
        "none",
        "na",
        "n/a",
        "not applicable",
        "not available",
        "unknown",
        "-",
    }
)
_ORGANISM_COLUMN = "characteristics[organism]"

# "Genus species", optionally followed by more: the shape normalize_organism
# looks for. The species may be "sp."/"spp." (genus-level). Case is ignored so
# that "escherichia coli" and "Escherichia Coli" are recognised too.
_BINOMIAL_RE = re.compile(r"^([A-Za-z]{3,})\s+([A-Za-z]{3,}|spp?\.)(?:\s+(.+))?$")
# A word after the species that starts a below-species rank: everything from
# it on is dropped ("Mycobacterium avium subsp. paratuberculosis").
_INFRASPECIFIC_MARKERS = frozenset(
    {
        "strain",
        "str.",
        "substr.",
        "subsp.",
        "ssp.",
        "serovar",
        "ser.",
        "var.",
        "pv.",
        "pathovar",
        "bv.",
        "biovar",
        "isolate",
        "clone",
        "genotype",
        "atcc",
        "nctc",
        "dsm",
        "ccug",
    }
)


def _is_strain_code(token: str) -> bool:
    """Return True for a token that reads as a strain/isolate code, not a word.

    E.g. "E1777", "K-12", "O157:H7", "C57BL/6", "(ATCC" or "ETEC"/"MRSA" --
    anything with a digit or code punctuation, or an all-caps abbreviation.
    """
    return (
        any(c.isdigit() for c in token)
        or any(c in ":/-()[]#" for c in token)
        or (len(token) >= 2 and token.isalpha() and token.isupper())
    )


def normalize_organism(name: str) -> str:
    """Reduce an organism name to its species, so strains share one facet entry.

    "Escherichia coli E1777" and "Escherichia coli K-12" both become
    "Escherichia coli", and so does "Escherichia coli strain O157:H7";
    "Mycobacterium avium subsp. paratuberculosis" becomes "Mycobacterium
    avium". The genus is capitalised and the species lowercased.

    Only a name shaped like "Genus species" is touched, and only when what
    follows the species is a below-species rank or a run of strain codes.
    Anything else is kept as written, because shortening it would change its
    meaning: hybrids ("Populus tremula x Populus tremuloides"), genus-only
    names ("Gomphrena"), and names that aren't binomials at all, such as most
    viruses ("Severe acute respiratory syndrome coronavirus 2", "Influenza A
    virus (H1N1)").
    """
    name = " ".join(name.split())
    match = _BINOMIAL_RE.match(name)
    if not match:
        return name
    genus, species, rest = match.groups()
    if rest:
        tokens = rest.split()
        is_rank = tokens[0].casefold() in _INFRASPECIFIC_MARKERS
        if not is_rank and not all(_is_strain_code(t) for t in tokens):
            return name
    return f"{genus.capitalize()} {species.lower()}"


def parse_sample_organisms(study_dir: Path) -> list[str]:
    """Return the distinct organisms in a study's s_*.txt sample file(s).

    Reads the Characteristics[Organism] column of each sample file at the
    top of the study directory (where metabolights_fetch saves them). A cell
    can name several organisms separated by ";" (e.g. a co-culture), and
    placeholders for control samples such as "blank" or "Medium" are
    dropped. Each name is reduced to its species by normalize_organism, so
    strains of one species share a facet entry, and names that still differ
    only in case are merged, keeping the first spelling seen.

    Returns [] if there is no sample file or no organism column -- e.g. for
    a study fetched before sample files were downloaded.
    """
    organisms: dict[str, str] = {}
    for path in sorted(study_dir.glob("s_*.txt")):
        try:
            with path.open(encoding="utf-8-sig", errors="replace", newline="") as f:
                reader = csv.reader(f, delimiter="\t")
                header = next(reader, [])
                columns = [i for i, h in enumerate(header) if h.strip().lower() == _ORGANISM_COLUMN]
                if not columns:
                    continue
                for row in reader:
                    for i in columns:
                        if i >= len(row):
                            continue
                        for value in row[i].split(";"):
                            name = " ".join(value.split())
                            if not name or name.casefold() in _NON_ORGANISM_VALUES:
                                continue
                            name = normalize_organism(name)
                            organisms.setdefault(name.casefold(), name)
        except (OSError, csv.Error) as error:
            logger.warning("Could not read sample file %s: %s", path, error)
    return sorted(organisms.values(), key=str.casefold)


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


METABOLIGHTS_WS_BASE = "https://www.ebi.ac.uk/metabolights/ws"


def _list_study_directory(accession: str, directory: str | None = None) -> dict[str, Any] | None:
    """Return the raw 'files/tree' payload for one level of a public study.

    Passing 'directory' lists a named sub-directory (e.g. the raw-data 'FILES'
    folder) instead of the study root. Returns None if MetaboLights could not
    be reached or returned an invalid response.
    """
    params = {"location": "study", "include_sub_dir": "false"}
    if directory:
        params["directory"] = directory
    return fetch_json(f"{METABOLIGHTS_WS_BASE}/studies/{accession}/files/tree", params=params)


def _collect_study_file_paths(accession: str) -> list[dict[str, str]] | None:
    """Return every downloadable file for a public study, tagged by category.

    ISA-Tab metadata files sit at the study root and are tagged 'metadata';
    raw/derived data files sit one directory down (e.g. under 'FILES') and are
    tagged 'raw'. This walks the root and recurses one level into any
    sub-directory entry found there, matching MetaboLights' usual study layout
    - deeper nesting, if a study happens to have any, is not followed. The
    category lets the page group a study's links instead of showing one flat
    list, since a study's metadata and raw data serve different purposes.

    Returns None if MetaboLights could not be reached to list the study root.
    """
    root = _list_study_directory(accession)
    if root is None:
        return None

    files: list[dict[str, str]] = []
    for entry in root.get("study") or []:
        if entry.get("status") == "unreferenced":
            continue
        name = entry.get("file")
        if entry.get("type") == "directory":
            if not name:
                continue
            sub_data = _list_study_directory(accession, directory=name)
            if sub_data is None:
                continue
            for sub_entry in sub_data.get("study") or []:
                if sub_entry.get("status") == "unreferenced":
                    continue
                if sub_entry.get("type") == "directory":
                    continue
                sub_path = sub_entry.get("relative_path") or sub_entry.get("file")
                if sub_path:
                    files.append({"path": sub_path, "category": "raw"})
        else:
            path = entry.get("relative_path") or name
            if path:
                files.append({"path": path, "category": "metadata"})

    return files


def _build_download_urls(
    accession: str, files: Iterable[Mapping[str, str]]
) -> list[dict[str, str]]:
    """Build one direct MetaboLights zip-download entry per given file, tagged by category.

    MetaboLights' download endpoint accepts a comma-separated 'file' query
    parameter for multiple files, but its server-side implementation uses that
    raw, comma-joined value as the literal filename of the zip it builds on
    disk - so combining even a handful of files reliably blows past the ~255
    byte filename limit most filesystems enforce (confirmed: a real study's 9
    metadata files alone came to 403 bytes and crashed the endpoint with
    "File name too long"). Requesting one file per URL sidesteps that
    regardless of file count or name length, at the cost of more separate
    downloads per study.

    Each entry also carries a suggested save-as filename prefixed with the
    study accession. MetaboLights names every study's investigation file
    'i_Investigation.txt' and reuses other filename patterns across studies
    too, so with no per-study folder to tell them apart, a browser saving
    several studies' files into one flat Downloads folder needs some other
    way to keep them straight.
    """
    seen: dict[str, int] = {}
    entries: list[dict[str, str]] = []
    for file_info in files:
        path = file_info["path"]
        url = f"{METABOLIGHTS_WS_BASE}/studies/{accession}/download?file={quote(path, safe='')}"
        basename = path.rsplit("/", 1)[-1]
        filename = _dedupe_filename(f"{accession}_{basename}", seen)
        entries.append({"url": url, "filename": filename, "category": file_info["category"]})
    return entries


def _resolve_one_study(accession: str) -> dict[str, Any]:
    """Resolve a single study to its direct MetaboLights download URL(s), grouped by category."""
    result: dict[str, Any] = {
        "accession": accession,
        "metadata_files": [],
        "raw_files": [],
        "error": None,
    }

    if not ACCESSION_RE.match(accession):
        result["error"] = "Invalid accession."
        return result

    files = _collect_study_file_paths(accession)
    if files is None:
        result["error"] = "Could not reach MetaboLights to list this study's files."
        return result

    if not files:
        result["error"] = "No downloadable files were found for this study."
        return result

    for entry in _build_download_urls(accession, files):
        target = (
            result["metadata_files"] if entry["category"] == "metadata" else result["raw_files"]
        )
        target.append({"url": entry["url"], "filename": entry["filename"]})

    return result


def resolve_bulk_download(accessions: Iterable[str]) -> list[dict[str, Any]]:
    """Resolve each selected study to one or more direct MetaboLights download URLs.

    Every URL points straight at MetaboLights' own server: the end user's
    browser downloads the resulting file(s) directly and no study data passes
    through this portal. Studies are resolved concurrently since each one
    needs its own (small, metadata-only) round trip to MetaboLights.
    """
    accessions = list(accessions)
    with ThreadPoolExecutor(max_workers=min(8, len(accessions)) or 1) as pool:
        results = list(pool.map(_resolve_one_study, accessions))
    by_accession = {r["accession"]: r for r in results}
    return [by_accession[accession] for accession in accessions]


# Item fields the free-text search looks in: the identifiers, the study's own
# text, and the metadata parsed from i_Investigation.txt (see
# parse_investigation_file), so that e.g. a study whose factor is "HbA1c" is found
# by searching "HbA1c" even when neither its title nor description mentions it.
# Each may hold a string or a list of strings. Paths, URLs and dates are left out
# on purpose: matching on them would only produce noise.
SEARCH_FIELDS = (
    "id",
    "accession",
    "title",
    "description",
    "tags",
    "factors",
    "design_types",
    "platforms",
    "technology",
    "organisms",
    "pathogens",
    "publication_title",
    "publication_authors",
    "publication_doi",
)


def _search_values(value: object) -> list[str]:
    """Return a field's searchable text: one string per value, lowercased."""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v).lower() for v in value if v is not None]
    return [str(value).lower()]


def apply_text_search(items: list[dict], query: str) -> list[dict]:
    """Keep the items where any SEARCH_FIELDS value contains query (case-insensitive)."""
    if not query:
        return items

    q = query.lower()

    def matches_text(it: dict[str, Any]) -> bool:
        return any(q in text for field in SEARCH_FIELDS for text in _search_values(it.get(field)))

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
