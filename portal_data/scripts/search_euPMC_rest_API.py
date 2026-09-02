"""Search Europe PMC for publications associated with MetaboLights.

Usage:
    python search_euPMC_rest_API.py

Expects, in the same directory as this script:
    authors.csv
        CSV with an "author" column listing author names to search for.
    pathogen_infectious_disease_keywords_just_keywords.csv
        One keyword per line, used to filter results by title/abstract
        content.

Writes, to the current working directory:
    europepmc_metabolights_papers.csv   One row per matched paper.
    europepmc_metabolights_summary.csv  One row per author, with match counts.
    targets.txt                         lftp mirror targets for any
                                         MetaboLights accessions found.
                                         Consumed by fetch_metabolights.sh,
                                         which controls the local download
                                         location.
"""

from __future__ import annotations

import csv
import re
import time
from pathlib import Path

import requests

BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
BASE_FILTER = '((ACCESSION_TYPE:"metabolights") OR (LABS_PUBS:"1782"))'

script_dir = Path(__file__).resolve().parent
input_csv = script_dir / "authors.csv"


def build_query(author_name: str) -> str:
    """Build a Europe PMC query string for the given author name."""
    author_name = (author_name or "").strip()
    if not author_name:
        raise ValueError("author_name is empty")
    return f'{BASE_FILTER} AND AUTH:"{author_name}"'


def search_europe_pmc(query: str, page_size: int = 1000, sleep_s: float = 0.1) -> list[dict]:
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

        response = requests.get(BASE_URL, params=params, timeout=60)
        response.raise_for_status()
        data = response.json()

        results = data.get("resultList", {}).get("result", [])
        all_results.extend(results)

        next_cursor = data.get("nextCursorMark")
        if not results or not next_cursor or next_cursor == cursor_mark:
            break

        cursor_mark = next_cursor
        time.sleep(sleep_s)

    return all_results


def safe_get(record: dict, key: str) -> str:
    """Return record[key] as a string, or an empty string if missing or None."""
    value = record.get(key, "")
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
    """Format a single MTBLS accession as an lftp mirror target line.

    Only the remote path is included; fetch_metabolights.sh decides the
    local download location (via its DEST_ROOT), so no local path is
    written here.
    """
    return f"--recursive {METABOLIGHTS_FTP_BASE}/{accession}/"


ANNOTATIONS_API_URL = "https://www.ebi.ac.uk/europepmc/annotations_api/annotationsByArticleIds"


def fetch_textmined_metabolights_accessions(
    source: str, ext_id: str, sleep_s: float = 0.1
) -> list[str]:
    """Fetch text-mined MetaboLights accessions via the Europe PMC annotations API."""
    if not source or not ext_id:
        return []

    response = requests.get(
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
    time.sleep(sleep_s)

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


def get_metabolights_accessions(paper: dict, sleep_s: float = 0.1) -> list[str]:
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
    return fetch_textmined_metabolights_accessions(source, ext_id, sleep_s)


def flatten_paper(
    author_name: str,
    query: str,
    paper: dict,
    matched_keywords: list[str] | None = None,
) -> dict:
    """Flatten a Europe PMC result record into a row dict for CSV output."""
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
        "journal": safe_get(paper, "journalTitle"),
        "pub_year": safe_get(paper, "pubYear"),
        "first_publication_date": safe_get(paper, "firstPublicationDate"),
        "cited_by_count": safe_get(paper, "citedByCount"),
        "is_open_access": safe_get(paper, "isOpenAccess"),
        "matched_keywords": "; ".join(matched_keywords or []),
    }


def read_authors_from_csv(input_csv: str, author_column: str) -> list[str]:
    """Read unique, non-empty author names from a column in a CSV file."""
    authors = []
    seen = set()

    with Path(input_csv).open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if author_column not in reader.fieldnames:
            raise ValueError(
                f"Column '{author_column}' not found. Available columns: {reader.fieldnames}"
            )

        for row in reader:
            author = (row.get(author_column) or "").strip()
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


def main() -> None:
    """Run the Europe PMC author search and write results to CSV files."""
    input_csv = "authors.csv"
    author_column = "author"
    keywords_csv = "pathogen_infectious_disease_keywords_just_keywords.csv"
    papers_output_csv = "europepmc_metabolights_papers.csv"
    summary_output_csv = "europepmc_metabolights_summary.csv"
    targets_output_txt = "targets.txt"

    authors = read_authors_from_csv(input_csv, author_column)
    keywords = load_keywords(keywords_csv)
    keyword_pattern = build_keyword_pattern(keywords)
    print(f"Loaded {len(keywords)} keywords from {keywords_csv}")

    paper_rows = []
    summary_rows = []
    seen_accessions: set[str] = set()
    accession_targets: list[str] = []

    for idx, author_name in enumerate(authors, start=1):
        try:
            query = build_query(author_name)
            results = search_europe_pmc(query)

            filtered_count = 0
            for paper in results:
                text = " ".join([safe_get(paper, "title"), safe_get(paper, "abstractText")])
                matches = find_keyword_matches(text, keyword_pattern)
                if not matches:
                    continue
                filtered_count += 1
                paper_rows.append(flatten_paper(author_name, query, paper, matches))

                try:
                    accessions = get_metabolights_accessions(paper)
                except Exception as e:
                    src = paper.get("source", "?")
                    pid = paper.get("id", "?")
                    print(f"    annotation lookup failed for {src}:{pid}: {e}")
                    accessions = []

                for acc in accessions:
                    if acc not in seen_accessions:
                        seen_accessions.add(acc)
                        accession_targets.append(format_lftp_target(acc))

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

    paper_fieldnames = [
        "input_author",
        "query",
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
    ]

    with Path(papers_output_csv).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=paper_fieldnames)
        writer.writeheader()
        writer.writerows(paper_rows)

    summary_fieldnames = ["input_author", "query", "match_count", "filtered_count", "error"]
    with Path(summary_output_csv).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=summary_fieldnames)
        writer.writeheader()
        writer.writerows(summary_rows)

    with Path(targets_output_txt).open("w", encoding="utf-8") as f:
        f.write("\n".join(accession_targets))
        if accession_targets:
            f.write("\n")

    print()
    print(f"Wrote {len(paper_rows)} paper rows to {papers_output_csv}")
    print(f"Wrote {len(summary_rows)} summary rows to {summary_output_csv}")
    print(f"Wrote {len(accession_targets)} lftp targets to {targets_output_txt}")


if __name__ == "__main__":
    main()
