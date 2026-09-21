"""Search Europe PMC for publications associated with MetaboLights.

Usage:
    python search_euPMC_rest_API.py
    python search_euPMC_rest_API.py --retry-errors

--retry-errors re-runs the search only for authors whose row in
europepmc_metabolights_summary.csv has a non-empty error (e.g. a
transient "too many 503 error responses" from Europe PMC), and merges
the results into the existing papers/summary/targets output files
instead of doing a full re-run. Safe to run repeatedly.

Expects, in the same directory as this script:
    publications.csv
        CSV with an "Authors" column per publication, holding a
        comma-separated list of authors in "Lastname Initials" form
        (e.g. "Keller T, Etana A, Bosch Y"). Unique author names are
        extracted across all rows and searched individually.
    pathogen_infectious_disease_keywords_just_keywords.csv
        One keyword per line, used to filter results by title/abstract
        content. A handful of overly generic keywords (see WEAK_KEYWORDS)
        are only counted as a match when they co-occur with a more
        specific keyword, since on their own they show up across
        unrelated fields (plant genomics, yeast biology, cardiology, ...).

Writes, to the current working directory:
    europepmc_metabolights_papers.csv   One row per unique paper (deduplicated
                                         across every author query that found
                                         it). matching_authors lists every
                                         distinct input author that matched,
                                         and matching_author_count is how many
                                         -- a high count usually means a large
                                         multi-author paper matched through a
                                         common-surname collision rather than
                                         a genuinely stronger hit (Europe
                                         PMC's AUTH filter matches on name
                                         text alone, with no affiliation
                                         check). sweden_affiliated_matching_authors
                                         and non_sweden_affiliated_matching_authors
                                         split those matched names by whether
                                         Europe PMC's per-author affiliation
                                         data (available for MEDLINE records
                                         from 2014 on) mentions Sweden -- if
                                         a paper's matches are all in the
                                         "non_sweden" column and none in
                                         "sweden", especially alongside a
                                         high matching_author_count, that's a
                                         strong sign of a surname collision
                                         rather than a real hit. Both columns
                                         can be empty if no affiliation data
                                         was available at all (unknown, not
                                         necessarily non-Swedish).
                                         matching_authors_affiliations gives
                                         the raw "Name: affiliation" text for
                                         every matched author with data, for
                                         manual review. metabolights_accessions
                                         lists any MetaboLights accession(s)
                                         (curated or text-mined) found for
                                         that paper, if any -- empty means
                                         the paper matched on author +
                                         keyword only, with no confirmed
                                         MetaboLights dataset link.
    europepmc_metabolights_summary.csv  One row per author, with match counts.
    targets.txt                         lftp mirror targets for any
                                         MetaboLights accessions found.
                                         Consumed by fetch_metabolights.sh,
                                         which controls the local download
                                         location.

Requests to Europe PMC are throttled by a shared RateLimiter to stay within
their documented per-IP limits (10 requests/second, 500 requests/minute),
and reuse a single requests.Session (with automatic retry/backoff on
429/5xx responses) instead of opening a new connection per call.
"""

from __future__ import annotations

import argparse
import csv
import re
import time
import unicodedata
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
BASE_FILTER = '((ACCESSION_TYPE:"metabolights") OR (LABS_PUBS:"1782"))'

PAPERS_OUTPUT_CSV = "europepmc_metabolights_papers.csv"
SUMMARY_OUTPUT_CSV = "europepmc_metabolights_summary.csv"
TARGETS_OUTPUT_TXT = "targets.txt"
KEYWORDS_CSV = "pathogen_infectious_disease_keywords_just_keywords.csv"

PAPER_FIELDNAMES = [
    "matching_authors",
    "matching_author_count",
    "sweden_affiliated_matching_authors",
    "non_sweden_affiliated_matching_authors",
    "epmc_id",
    "source",
    "pmid",
    "pmcid",
    "doi",
    "title",
    "author_string",
    "journal",
    "pub_year",
    "first_publication_date",
    "cited_by_count",
    "is_open_access",
    "matched_keywords",
    "metabolights_accessions",
    "matching_authors_affiliations",
]
SUMMARY_FIELDNAMES = ["input_author", "query", "match_count", "filtered_count", "error"]


def build_query(author_name: str) -> str:
    """Build a Europe PMC query string for the given author name."""
    author_name = (author_name or "").strip()
    if not author_name:
        raise ValueError("author_name is empty")
    return f'{BASE_FILTER} AND AUTH:"{author_name}"'


# Europe PMC's documented per-IP limits: 10 requests/second, 500 requests/minute.
EUROPEPMC_MAX_PER_SECOND = 10
EUROPEPMC_MAX_PER_MINUTE = 500


class RateLimiter:
    """Throttles calls to at most `max_per_second`/`max_per_minute`.

    Tracks recent call timestamps and sleeps only the shortfall needed to
    stay under whichever window (1s or 60s) is tighter at the moment --
    unlike a fixed per-call sleep, this adds no delay at all when normal
    request latency already keeps you under the limit, and only slows
    down once you're actually approaching it.
    """

    def __init__(self, max_per_second: int, max_per_minute: int) -> None:
        """Set the two throttling windows to enforce."""
        self._max_per_second = max_per_second
        self._max_per_minute = max_per_minute
        self._recent_calls: list[float] = []

    def wait(self) -> None:
        """Block, if needed, until another call is allowed under both windows."""
        now = time.monotonic()
        self._recent_calls = [t for t in self._recent_calls if now - t < 60]

        wait_for = 0.0
        last_second = [t for t in self._recent_calls if now - t < 1]
        if len(last_second) >= self._max_per_second:
            wait_for = max(wait_for, 1 - (now - last_second[0]))
        if len(self._recent_calls) >= self._max_per_minute:
            wait_for = max(wait_for, 60 - (now - self._recent_calls[0]))

        if wait_for > 0:
            time.sleep(wait_for)
            now = time.monotonic()

        self._recent_calls.append(now)


RATE_LIMITER = RateLimiter(EUROPEPMC_MAX_PER_SECOND, EUROPEPMC_MAX_PER_MINUTE)


def _build_session() -> requests.Session:
    """Build a requests.Session reused for every call.

    Keeps the TCP/TLS connection alive instead of renegotiating it per
    request, and automatically retries (with backoff, honouring
    Retry-After) on 429/5xx instead of losing an author's results to a
    transient throttle or server error.
    """
    session = requests.Session()
    retry = Retry(
        total=5,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        respect_retry_after_header=True,
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


SESSION = _build_session()


def search_europe_pmc(query: str, page_size: int = 1000) -> list[dict]:
    """Retrieve all Europe PMC results for a query using cursor pagination.

    Returns a list of result records.
    """
    cursor_mark = "*"
    all_results = []

    while True:
        params = {
            "query": query,
            "format": "json",
            "pageSize": page_size,
            "cursorMark": cursor_mark,
            "resultType": "core",
        }

        RATE_LIMITER.wait()
        response = SESSION.get(BASE_URL, params=params, timeout=60)
        response.raise_for_status()
        data = response.json()

        results = data.get("resultList", {}).get("result", [])
        all_results.extend(results)

        next_cursor = data.get("nextCursorMark")
        if not results or not next_cursor or next_cursor == cursor_mark:
            break

        cursor_mark = next_cursor

    return all_results


def safe_get(record: dict, key: str) -> str:
    """Return record[key] as a string, or an empty string if missing or None."""
    value = record.get(key, "")
    if value is None:
        return ""
    return value


def safe_get_nested(record: dict, *keys: str) -> str:
    """Return a nested value as a string, or an empty string if missing.

    Returns "" if any level along the path is missing or None, e.g.
    safe_get_nested(paper, "journalInfo", "journal", "title").
    """
    value: object = record
    for key in keys:
        if not isinstance(value, dict):
            return ""
        value = value.get(key)
    if value is None:
        return ""
    return value


METABOLIGHTS_FTP_BASE = "/pub/databases/metabolights/studies/public"


def extract_metabolights_accessions(paper: dict) -> list[str]:
    """Return all MetaboLights accession IDs (MTBLS*) linked to a paper record."""
    accessions = []
    db_refs = paper.get("dbCrossReferenceList", {}).get("dbCrossReference", [])
    for ref in db_refs:
        if ref.get("type", "").upper() == "METABOLIGHTS":
            for acc in ref.get("accessionList", {}).get("accession", []):
                value = (acc.get("value") or "").strip()
                if value.upper().startswith("MTBLS"):
                    accessions.append(value.upper())
    return accessions


def format_lftp_target(accession: str) -> str:
    """Format a single MTBLS accession as an lftp target line (remote path only).

    fetch_metabolights.sh decides the local download location, so no local
    path is written here. There is also no leading flag: fetch_metabolights.sh
    fetches a single file (i_Investigation.txt) per study rather than
    mirroring a whole directory, so a recurse/no-recurse flag no longer
    applies.
    """
    return f"{METABOLIGHTS_FTP_BASE}/{accession}/"


ANNOTATIONS_API_URL = "https://www.ebi.ac.uk/europepmc/annotations_api/annotationsByArticleIds"


def fetch_textmined_metabolights_accessions(source: str, ext_id: str) -> list[str]:
    """Fetch text-mined MetaboLights accessions via the Europe PMC annotations API."""
    if not source or not ext_id:
        return []

    RATE_LIMITER.wait()
    response = SESSION.get(
        ANNOTATIONS_API_URL,
        params={
            "articleIds": f"{source}:{ext_id}",
            "type": "Accession Numbers",
            "format": "JSON",
        },
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()

    accessions = []
    seen = set()
    for article in payload:
        for ann in article.get("annotations", []):
            for tag in ann.get("tags", []):
                name = (tag.get("name") or "").strip().upper()
                uri = (tag.get("uri") or "").lower()
                if name.startswith("MTBLS") and "metabolights" in uri and name not in seen:
                    seen.add(name)
                    accessions.append(name)
    return accessions


def get_metabolights_accessions(paper: dict) -> list[str]:
    """Get all MetaboLights accessions for a paper.

    Checks curated cross-references first (no API call). Falls back to the
    Europe PMC annotations API for text-mined accessions when the paper's
    `hasTMAccessionNumbers` flag is set.
    """
    accessions = extract_metabolights_accessions(paper)
    if accessions:
        return accessions
    if paper.get("hasTMAccessionNumbers") != "Y":
        return []
    source = paper.get("source") or ""
    ext_id = paper.get("id") or paper.get("pmid") or ""
    return fetch_textmined_metabolights_accessions(source, ext_id)


def _normalize_name(name: str) -> str:
    """Fold a name to a comparable form: strip diacritics, collapse whitespace, lowercase.

    Used to match our own "Lastname Initials" strings against Europe
    PMC's authorList fullName field, which should normally already be in
    the same format but may differ slightly in accenting or spacing.
    """
    name = unicodedata.normalize("NFKD", name or "")
    name = "".join(c for c in name if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", name).strip().casefold()


def get_author_affiliations(paper: dict) -> dict[str, list[str]]:
    """Map each author's fullName to their list of affiliation strings.

    Only populated for resultType=core records, and only for MEDLINE
    records from 2014 onward (per Europe PMC's docs) -- a paper with no
    affiliation data at all doesn't necessarily mean its authors lack one.
    Keys are normalized via _normalize_name for reliable lookup.
    """
    affiliations: dict[str, list[str]] = {}
    authors = paper.get("authorList", {}).get("author", [])
    for author in authors:
        full_name = (author.get("fullName") or "").strip()
        if not full_name:
            continue
        details = author.get("authorAffiliationDetailsList", {}).get("authorAffiliation", [])
        author_affils = [
            (d.get("affiliation") or "").strip()
            for d in details
            if (d.get("affiliation") or "").strip()
        ]
        if author_affils:
            key = _normalize_name(full_name)
            affiliations.setdefault(key, []).extend(author_affils)
    return affiliations


def get_affiliation_for_author(affiliations: dict[str, list[str]], author_name: str) -> list[str]:
    """Look up the specific matched author's affiliation(s) on this paper.

    Looks up by normalized name, and only that author (not just any
    co-author's). Returns [] if no affiliation data was found for that
    author on this paper.
    """
    return affiliations.get(_normalize_name(author_name), [])


def _sweden_flag(author_affiliations: list[str]) -> str:
    """Return "Y"/"N"/"" for whether the affiliations mention Sweden.

    "Y" if any affiliation mentions Sweden, "N" if affiliation data
    exists but none does, "" if no affiliation data was found at all for
    that author on this paper (unknown, not necessarily non-Swedish).
    """
    if not author_affiliations:
        return ""
    return "Y" if any("sweden" in a.lower() for a in author_affiliations) else "N"


def flatten_paper(
    author_name: str,
    query: str,
    paper: dict,
    matched_keywords: list[str] | None = None,
    metabolights_accessions: list[str] | None = None,
    author_affiliations: list[str] | None = None,
) -> dict:
    """Flatten a Europe PMC result record into a row dict for CSV output.

    author_affiliations should be the specific matched author's own
    affiliation string(s) on this paper (see get_affiliation_for_author),
    not just any co-author's -- empty means no affiliation data was found
    for that author on this record.
    """
    return {
        "input_author": author_name,
        "query": query,
        "epmc_id": safe_get(paper, "id"),
        "source": safe_get(paper, "source"),
        "pmid": safe_get(paper, "pmid"),
        "pmcid": safe_get(paper, "pmcid"),
        "doi": safe_get(paper, "doi"),
        "title": safe_get(paper, "title"),
        "author_string": safe_get(paper, "authorString"),
        "journal": safe_get_nested(paper, "journalInfo", "journal", "title"),
        "pub_year": safe_get(paper, "pubYear"),
        "first_publication_date": safe_get(paper, "firstPublicationDate"),
        "cited_by_count": safe_get(paper, "citedByCount"),
        "is_open_access": safe_get(paper, "isOpenAccess"),
        "matched_keywords": "; ".join(matched_keywords or []),
        "metabolights_accessions": "; ".join(metabolights_accessions or []),
        "author_affiliation": "; ".join(author_affiliations or []),
        "author_sweden_affiliation": _sweden_flag(author_affiliations or []),
    }


def dedupe_paper_rows(paper_rows: list[dict]) -> list[dict]:
    """Collapse rows for the same paper into one row per paper.

    The same paper can be found once per matching input author (a
    large multi-author paper may match dozens of them), which both
    inflates the row count and buries a useful signal: when a paper
    matches many distinct author names, that's often a common-surname
    collision (e.g. "Li X", "Wang X") rather than a genuinely stronger
    hit, since Europe PMC's AUTH filter matches on name text alone with
    no affiliation check. This groups by (source, epmc_id), keeps the
    paper-level fields as-is (they don't vary between duplicate rows of
    the same paper), and replaces the per-author `input_author`/`query`/
    `author_affiliation`/`author_sweden_affiliation` fields with:
      - matching_authors / matching_author_count: every distinct author
        that matched, in order of first appearance, and how many.
      - sweden_affiliated_matching_authors: which of those specifically
        have a Sweden-mentioning affiliation on this paper -- empty means
        none of the matched names look genuinely Swedish here, a strong
        signal (especially combined with a high matching_author_count)
        that the match is a surname collision rather than a real hit.
      - non_sweden_affiliated_matching_authors: matched authors whose
        affiliation is known and does NOT mention Sweden (as opposed to
        no affiliation data being available at all).
      - matching_authors_affiliations: "Name: affiliation" for every
        matched author where affiliation data was found, for manual
        review.
    """
    grouped: dict[tuple[str, str], dict] = {}
    order: list[tuple[str, str]] = []
    author_matches: dict[tuple[str, str], list[tuple[str, str, str]]] = {}

    for row in paper_rows:
        key = (row["source"], row["epmc_id"])
        author_matches.setdefault(key, []).append(
            (
                row["input_author"],
                row.get("author_sweden_affiliation", ""),
                row.get("author_affiliation", ""),
            )
        )
        if key not in grouped:
            new_row = dict(row)
            for field in (
                "query",
                "input_author",
                "author_affiliation",
                "author_sweden_affiliation",
            ):
                new_row.pop(field, None)
            grouped[key] = new_row
            order.append(key)

    deduped = []
    for key in order:
        row = grouped[key]
        matches = author_matches[key]

        seen_authors: list[str] = []
        for author, _flag, _aff in matches:
            if author not in seen_authors:
                seen_authors.append(author)

        sweden_authors = list(dict.fromkeys(a for a, flag, _ in matches if flag == "Y"))
        non_sweden_authors = list(dict.fromkeys(a for a, flag, _ in matches if flag == "N"))
        affiliation_detail = [f"{a}: {aff}" for a, _flag, aff in matches if aff]

        row["matching_authors"] = "; ".join(seen_authors)
        row["matching_author_count"] = len(seen_authors)
        row["sweden_affiliated_matching_authors"] = "; ".join(sweden_authors)
        row["non_sweden_affiliated_matching_authors"] = "; ".join(non_sweden_authors)
        row["matching_authors_affiliations"] = " | ".join(affiliation_detail)
        deduped.append(row)

    return deduped


def _parse_affiliation_detail(field: str) -> dict[str, str]:
    """Parse a matching_authors_affiliations field back into a dict.

    The field looks like "Name: affiliation | Name: affiliation"; this
    returns {name: affiliation}.
    """
    result: dict[str, str] = {}
    for part in (field or "").split(" | "):
        if ": " in part:
            name, aff = part.split(": ", 1)
            result[name.strip()] = aff.strip()
    return result


def expand_deduped_row_to_author_rows(row: dict) -> list[dict]:
    """Reverse dedupe_paper_rows for one already-deduped paper row.

    Rebuilds one row per matched author, in flatten_paper's per-author-match
    shape. Used so a retry run can merge newly found matches into an
    existing deduped papers CSV (and re-run dedupe_paper_rows over the
    combination) without needing to keep the original pre-dedup rows
    around between runs.
    """
    sweden_authors = {
        a.strip()
        for a in (row.get("sweden_affiliated_matching_authors") or "").split(";")
        if a.strip()
    }
    non_sweden_authors = {
        a.strip()
        for a in (row.get("non_sweden_affiliated_matching_authors") or "").split(";")
        if a.strip()
    }
    affiliations = _parse_affiliation_detail(row.get("matching_authors_affiliations") or "")

    shared_fields = {
        k: v
        for k, v in row.items()
        if k
        not in (
            "matching_authors",
            "matching_author_count",
            "sweden_affiliated_matching_authors",
            "non_sweden_affiliated_matching_authors",
            "matching_authors_affiliations",
        )
    }

    expanded = []
    for name in (row.get("matching_authors") or "").split(";"):
        name = name.strip()
        if not name:
            continue
        if name in sweden_authors:
            flag = "Y"
        elif name in non_sweden_authors:
            flag = "N"
        else:
            flag = ""
        expanded_row = dict(shared_fields)
        expanded_row["input_author"] = name
        expanded_row["author_sweden_affiliation"] = flag
        expanded_row["author_affiliation"] = affiliations.get(name, "")
        expanded.append(expanded_row)
    return expanded


def load_errored_authors(summary_csv: str) -> list[str]:
    """Return authors whose row in a previous run's summary CSV has an error.

    E.g. a transient network/server failure. Returned in order of first
    appearance, deduplicated.
    """
    authors = []
    seen = set()
    with Path(summary_csv).open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            author = (row.get("input_author") or "").strip()
            error = (row.get("error") or "").strip()
            if author and error and author not in seen:
                seen.add(author)
                authors.append(author)
    return authors


def retry_errored_authors(
    papers_csv: str = PAPERS_OUTPUT_CSV,
    summary_csv: str = SUMMARY_OUTPUT_CSV,
    targets_txt: str = TARGETS_OUTPUT_TXT,
    keywords_csv: str = KEYWORDS_CSV,
) -> None:
    """Re-run the search for authors that errored in a previous run.

    Merges the results into the existing output files instead of starting
    over. Safe to run repeatedly -- authors that still error stay marked
    as errored for the next retry.
    """
    errored_authors = load_errored_authors(summary_csv)
    if not errored_authors:
        print(f"No errored authors found in {summary_csv}. Nothing to retry.")
        return

    print(f"Retrying {len(errored_authors)} previously-errored author(s)...")
    keywords = load_keywords(keywords_csv)
    keyword_pattern = build_keyword_pattern(keywords)

    new_paper_rows, new_summary_rows = search_authors(errored_authors, keyword_pattern)

    existing_paper_rows = []
    if Path(papers_csv).exists():
        with Path(papers_csv).open(newline="", encoding="utf-8-sig") as f:
            existing_paper_rows = list(csv.DictReader(f))

    expanded_existing = [
        r for row in existing_paper_rows for r in expand_deduped_row_to_author_rows(row)
    ]
    deduped_paper_rows = dedupe_paper_rows(expanded_existing + new_paper_rows)

    with Path(papers_csv).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=PAPER_FIELDNAMES)
        writer.writeheader()
        writer.writerows(deduped_paper_rows)

    existing_summary_rows = []
    if Path(summary_csv).exists():
        with Path(summary_csv).open(newline="", encoding="utf-8-sig") as f:
            existing_summary_rows = list(csv.DictReader(f))

    retried_set = set(errored_authors)
    merged_summary_rows = [
        r for r in existing_summary_rows if r.get("input_author") not in retried_set
    ]
    merged_summary_rows.extend(new_summary_rows)

    with Path(summary_csv).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDNAMES)
        writer.writeheader()
        writer.writerows(merged_summary_rows)

    accession_targets = accession_targets_from_paper_rows(deduped_paper_rows)
    with Path(targets_txt).open("w", encoding="utf-8") as f:
        f.write("\n".join(accession_targets))
        if accession_targets:
            f.write("\n")

    still_errored = sum(1 for r in new_summary_rows if r.get("error"))
    print()
    print(f"Retried {len(errored_authors)} author(s); {still_errored} still errored.")
    print(f"Merged papers CSV now has {len(deduped_paper_rows)} unique papers ({papers_csv}).")
    print(f"Rewrote {summary_csv} and {targets_txt}.")


def read_authors_from_publications_csv(
    input_csv: str, authors_column: str = "Authors"
) -> list[str]:
    """Read unique, non-empty author names out of a publications CSV file.

    Each row's `authors_column` holds a comma-separated list of authors in
    "Lastname Initials" form (e.g. "Keller T, Etana A, Bosch Y"). This
    splits that list and collects the unique names across all rows, in
    order of first appearance.
    """
    authors = []
    seen = set()

    with Path(input_csv).open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if authors_column not in reader.fieldnames:
            raise ValueError(
                f"Column '{authors_column}' not found. Available columns: {reader.fieldnames}"
            )

        for row in reader:
            raw_authors = (row.get(authors_column) or "").strip()
            if not raw_authors:
                continue
            for author in raw_authors.split(","):
                author = author.strip()
                if not author:
                    continue
                if author not in seen:
                    seen.add(author)
                    authors.append(author)

    return authors


def load_keywords(path: str) -> list[str]:
    """Load unique, non-empty keywords from a one-per-line text file."""
    keywords = []
    seen = set()
    with Path(path).open(encoding="utf-8-sig") as f:
        for line in f:
            kw = line.strip()
            if not kw:
                continue
            lower = kw.lower()
            if lower not in seen:
                seen.add(lower)
                keywords.append(kw)
    return keywords


def is_uppercase_abbrev(keyword: str) -> bool:
    """Return True for short pure-letter all-caps strings (likely abbreviations).

    Such keywords (e.g. GAS, AIDS, MAC, MRSA) should match case-sensitively to
    avoid colliding with common lowercase English words.
    """
    return keyword.isascii() and keyword.isalpha() and keyword.isupper() and 2 <= len(keyword) <= 6


def build_keyword_pattern(keywords: list[str]) -> re.Pattern[str]:
    """Build a regex matching any keyword.

    Short all-caps alphabetic abbreviations are matched case-sensitively to avoid
    collisions with common English words (e.g. GAS, the abbreviation for Group A
    Streptococcus, vs. 'gas' in 'gas chromatography'). All other keywords are
    matched case-insensitively.
    """
    if not keywords:
        raise ValueError("keywords list is empty")

    # Sort by length descending so longer alternatives are tried first.
    cs = sorted([kw for kw in keywords if is_uppercase_abbrev(kw)], key=len, reverse=True)
    ci = sorted([kw for kw in keywords if not is_uppercase_abbrev(kw)], key=len, reverse=True)

    parts = []
    if cs:
        parts.append("|".join(re.escape(kw) for kw in cs))
    if ci:
        parts.append(r"(?i:" + "|".join(re.escape(kw) for kw in ci) + r")")
    return re.compile(r"\b(?:" + "|".join(parts) + r")\b")


def find_keyword_matches(text: str, pattern: re.Pattern[str]) -> list[str]:
    """Return matched keywords in order of first appearance, deduplicated."""
    if not text:
        return []
    seen_lower = set()
    found = []
    for m in pattern.finditer(text):
        val = m.group(0)
        key = val.lower()
        if key not in seen_lower:
            seen_lower.add(key)
            found.append(val)
    return found


# These keywords are too generic on their own to reliably indicate
# pathogen/infectious-disease relevance -- they show up constantly in
# unrelated fields (e.g. "host" in plant biology, "strain" in yeast
# genetics, "assembly" in any genome paper, "exposure" in toxicology,
# "case" in "case study"/"case-control"). A paper matched on nothing but
# these is treated as a non-match; combined with a more specific keyword
# (e.g. "host" + "bacteria") it's still counted as a real hit.
WEAK_KEYWORDS = {"host", "exposure", "case", "assembly", "strain"}


def has_strong_match(matches: list[str]) -> bool:
    """Return True if at least one match is not in WEAK_KEYWORDS."""
    return any(m.lower() not in WEAK_KEYWORDS for m in matches)


def search_authors(
    authors: list[str], keyword_pattern: re.Pattern[str]
) -> tuple[list[dict], list[dict]]:
    """Search Europe PMC for each author in turn.

    Returns (paper_rows, summary_rows): paper_rows are per-(author, paper)
    match dicts in flatten_paper's shape (not yet deduped -- see
    dedupe_paper_rows), and summary_rows are one dict per author with its
    match/filtered counts, or an "error" key if the search itself failed.
    """
    paper_rows = []
    summary_rows = []

    for idx, author_name in enumerate(authors, start=1):
        try:
            query = build_query(author_name)
            results = search_europe_pmc(query)

            filtered_count = 0
            for paper in results:
                text = " ".join([safe_get(paper, "title"), safe_get(paper, "abstractText")])
                matches = find_keyword_matches(text, keyword_pattern)
                if not matches or not has_strong_match(matches):
                    continue
                filtered_count += 1

                try:
                    accessions = get_metabolights_accessions(paper)
                except Exception as e:
                    src = paper.get("source", "?")
                    pid = paper.get("id", "?")
                    print(f"    annotation lookup failed for {src}:{pid}: {e}")
                    accessions = []

                affiliations = get_author_affiliations(paper)
                author_affils = get_affiliation_for_author(affiliations, author_name)

                paper_rows.append(
                    flatten_paper(author_name, query, paper, matches, accessions, author_affils)
                )

            print(
                f"[{idx}/{len(authors)}] {author_name}: "
                f"{len(results)} matches, {filtered_count} after keyword filter"
            )

            summary_rows.append(
                {
                    "input_author": author_name,
                    "query": query,
                    "match_count": len(results),
                    "filtered_count": filtered_count,
                }
            )

        except Exception as e:
            print(f"[{idx}/{len(authors)}] ERROR for {author_name}: {e}")
            summary_rows.append(
                {
                    "input_author": author_name,
                    "query": "",
                    "match_count": "",
                    "filtered_count": "",
                    "error": str(e),
                }
            )

    return paper_rows, summary_rows


def accession_targets_from_paper_rows(paper_rows: list[dict]) -> list[str]:
    """Collect unique lftp target lines from a list of paper rows.

    Reads each (deduped) row's metabolights_accessions field, in order of
    first appearance.
    """
    seen: set[str] = set()
    targets: list[str] = []
    for row in paper_rows:
        for acc in (row.get("metabolights_accessions") or "").split(";"):
            acc = acc.strip()
            if acc and acc not in seen:
                seen.add(acc)
                targets.append(format_lftp_target(acc))
    return targets


def main() -> None:
    """Run the Europe PMC author search and write results to CSV files."""
    parser = argparse.ArgumentParser(
        description="Search Europe PMC for MetaboLights-linked publications."
    )
    parser.add_argument(
        "--retry-errors",
        action="store_true",
        help=(
            "Instead of a full run, re-run the search only for authors that "
            f"errored in the previous run (per the error column in "
            f"{SUMMARY_OUTPUT_CSV}), and merge the results into the existing "
            "output files rather than starting over."
        ),
    )
    args = parser.parse_args()

    if args.retry_errors:
        retry_errored_authors()
        return

    input_csv = "publications.csv"
    authors_column = "Authors"

    authors = read_authors_from_publications_csv(input_csv, authors_column)
    keywords = load_keywords(KEYWORDS_CSV)
    keyword_pattern = build_keyword_pattern(keywords)
    print(f"Loaded {len(keywords)} keywords from {KEYWORDS_CSV}")

    paper_rows, summary_rows = search_authors(authors, keyword_pattern)
    deduped_paper_rows = dedupe_paper_rows(paper_rows)

    with Path(PAPERS_OUTPUT_CSV).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=PAPER_FIELDNAMES)
        writer.writeheader()
        writer.writerows(deduped_paper_rows)

    with Path(SUMMARY_OUTPUT_CSV).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDNAMES)
        writer.writeheader()
        writer.writerows(summary_rows)

    accession_targets = accession_targets_from_paper_rows(deduped_paper_rows)
    with Path(TARGETS_OUTPUT_TXT).open("w", encoding="utf-8") as f:
        f.write("\n".join(accession_targets))
        if accession_targets:
            f.write("\n")

    print()
    print(
        f"Wrote {len(deduped_paper_rows)} unique papers "
        f"(from {len(paper_rows)} author-paper matches) to {PAPERS_OUTPUT_CSV}"
    )
    print(f"Wrote {len(summary_rows)} summary rows to {SUMMARY_OUTPUT_CSV}")
    print(f"Wrote {len(accession_targets)} lftp targets to {TARGETS_OUTPUT_TXT}")


if __name__ == "__main__":
    main()
