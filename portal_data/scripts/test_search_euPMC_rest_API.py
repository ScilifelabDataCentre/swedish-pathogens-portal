"""Tests for search_euPMC_rest_API.py.

Run with: pytest test_search_euPMC_rest_API.py -v

Everything here mocks the network layer (SESSION.get) rather than hitting
the real Europe PMC API: fast, deterministic, and doesn't depend on or add
load to an external service. See the module docstring discussion in chat
for why real end-to-end tests against the live API are better kept as an
occasional manual/scheduled smoke test rather than part of this suite.

Requires search_euPMC_rest_API.py to be importable (same directory, or on
sys.path).
"""

from __future__ import annotations

import csv

import pytest

import search_euPMC_rest_API as sepmc


# ---------------------------------------------------------------------------
# Small helpers for building fake Europe PMC responses
# ---------------------------------------------------------------------------


class FakeResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(self, status_code: int = 200, json_data: dict | None = None):
        self.status_code = status_code
        self._json_data = json_data or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise sepmc.requests.exceptions.HTTPError(f"{self.status_code} error")

    def json(self) -> dict:
        return self._json_data


def make_paper(
    epmc_id: str,
    author_name: str,
    title: str = "A bacterial pathogen study",
    abstract: str = "bacteria pathogen infection",
    affiliation: str | None = None,
) -> dict:
    """Build a minimal paper dict matching Europe PMC's documented core schema."""
    paper = {
        "id": epmc_id,
        "source": "MED",
        "title": title,
        "abstractText": abstract,
        "authorString": author_name,
        "pubYear": "2024",
        "hasTMAccessionNumbers": "N",
        "dbCrossReferenceList": {"dbCrossReference": []},
    }
    if affiliation:
        paper["authorList"] = {
            "author": [
                {
                    "fullName": author_name,
                    "authorAffiliationDetailsList": {"authorAffiliation": [{"affiliation": affiliation}]},
                }
            ]
        }
    return paper


def make_fake_get(fail_authors: set[str], papers_by_author: dict[str, dict]):
    """Build a fake SESSION.get(...).

    Raises (simulating an exhausted-retries network failure) for any
    author name appearing in `fail_authors`'s AUTH: query, and otherwise
    returns a canned single-page result for that author if one was
    registered in `papers_by_author`, else an empty result.
    """

    def fake_get(url, params=None, timeout=None):  # noqa: ARG001
        query = (params or {}).get("query", "")
        for author in fail_authors:
            if f'AUTH:"{author}"' in query:
                raise sepmc.requests.exceptions.ConnectionError(
                    f"Max retries exceeded (simulated failure for {author})"
                )
        for author, paper in papers_by_author.items():
            if f'AUTH:"{author}"' in query:
                return FakeResponse(200, {"resultList": {"result": [paper]}, "nextCursorMark": None})
        return FakeResponse(200, {"resultList": {"result": []}, "nextCursorMark": None})

    return fake_get


@pytest.fixture(autouse=True)
def _no_real_sleeping(monkeypatch):
    """Never actually sleep in tests, even if a code path calls RATE_LIMITER.wait()."""
    monkeypatch.setattr(sepmc.RATE_LIMITER, "wait", lambda: None)


# ---------------------------------------------------------------------------
# Unit tests for pure functions -- no network involved at all
# ---------------------------------------------------------------------------


def test_build_query():
    assert sepmc.build_query("Li X") == f'{sepmc.BASE_FILTER} AND AUTH:"Li X"'
    with pytest.raises(ValueError):
        sepmc.build_query("   ")


def test_has_strong_match():
    assert sepmc.has_strong_match(["host"]) is False
    assert sepmc.has_strong_match(["host", "bacteria"]) is True
    assert sepmc.has_strong_match(["pathogen"]) is True
    assert sepmc.has_strong_match([]) is False


def test_format_lftp_target():
    assert sepmc.format_lftp_target("MTBLS42") == "/pub/databases/metabolights/studies/public/MTBLS42/"


def test_normalize_name_strips_diacritics_and_case():
    assert sepmc._normalize_name("Bösch Y") == sepmc._normalize_name("Bosch y")


def test_sweden_flag_three_states():
    assert sepmc._sweden_flag(["Karolinska Institutet, Stockholm, Sweden."]) == "Y"
    assert sepmc._sweden_flag(["Fudan University, China."]) == "N"
    assert sepmc._sweden_flag([]) == ""


def test_dedupe_paper_rows_aggregates_by_source_and_id():
    rows = [
        sepmc.flatten_paper("Li X", "q1", make_paper("1", "Li X"), ["bacteria"], [], ["China."]),
        sepmc.flatten_paper("Muller M", "q2", make_paper("1", "Muller M"), ["bacteria"], [], ["Sweden."]),
    ]
    # both rows describe the same paper (source=MED, epmc_id=1)
    deduped = sepmc.dedupe_paper_rows(rows)
    assert len(deduped) == 1
    assert deduped[0]["matching_author_count"] == 2
    assert "Muller M" in deduped[0]["sweden_affiliated_matching_authors"]
    assert "Li X" in deduped[0]["non_sweden_affiliated_matching_authors"]


def test_expand_deduped_row_round_trips():
    rows = [
        sepmc.flatten_paper("Li X", "q1", make_paper("1", "Li X"), ["bacteria"], [], ["China."]),
        sepmc.flatten_paper("Muller M", "q2", make_paper("1", "Muller M"), ["bacteria"], [], ["Sweden."]),
    ]
    deduped_once = sepmc.dedupe_paper_rows(rows)
    expanded = sepmc.expand_deduped_row_to_author_rows(deduped_once[0])
    re_deduped = sepmc.dedupe_paper_rows(expanded)
    assert re_deduped == deduped_once


# ---------------------------------------------------------------------------
# Mocked-network tests: normal search behavior
# ---------------------------------------------------------------------------


def test_search_authors_finds_and_filters(monkeypatch):
    paper = make_paper("1", "Good A")
    monkeypatch.setattr(
        sepmc,
        "SESSION",
        type("FakeSession", (), {"get": staticmethod(make_fake_get(fail_authors=set(), papers_by_author={"Good A": paper}))})(),
    )
    pattern = sepmc.build_keyword_pattern(["bacteria", "pathogen"])

    paper_rows, summary_rows = sepmc.search_authors(["Good A"], pattern)

    assert len(paper_rows) == 1
    assert paper_rows[0]["input_author"] == "Good A"
    assert summary_rows[0]["match_count"] == 1
    assert summary_rows[0]["filtered_count"] == 1
    assert not summary_rows[0].get("error")


# ---------------------------------------------------------------------------
# The actual ask: deliberately fail a search, then verify --retry-errors
# recovers and merges the result in.
# ---------------------------------------------------------------------------


def test_search_authors_records_error_for_failing_author(monkeypatch):
    good_paper = make_paper("1", "Good A")
    fake_get = make_fake_get(fail_authors={"Bad B"}, papers_by_author={"Good A": good_paper})
    monkeypatch.setattr(sepmc, "SESSION", type("FakeSession", (), {"get": staticmethod(fake_get)})())
    pattern = sepmc.build_keyword_pattern(["bacteria", "pathogen"])

    paper_rows, summary_rows = sepmc.search_authors(["Good A", "Bad B"], pattern)

    good_summary = next(r for r in summary_rows if r["input_author"] == "Good A")
    bad_summary = next(r for r in summary_rows if r["input_author"] == "Bad B")

    assert not good_summary.get("error")
    assert bad_summary.get("error")  # deliberately failed
    assert len(paper_rows) == 1  # only Good A's paper made it through
    assert paper_rows[0]["input_author"] == "Good A"


def test_retry_errored_authors_merges_recovered_result(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / sepmc.KEYWORDS_CSV).write_text("bacteria\npathogen\n")

    # --- pass 1: "Bad B" fails, write it out as a normal run would ---
    fake_get_failing = make_fake_get(fail_authors={"Bad B"}, papers_by_author={})
    monkeypatch.setattr(sepmc, "SESSION", type("FakeSession", (), {"get": staticmethod(fake_get_failing)})())
    pattern = sepmc.build_keyword_pattern(["bacteria", "pathogen"])

    paper_rows, summary_rows = sepmc.search_authors(["Bad B"], pattern)
    deduped = sepmc.dedupe_paper_rows(paper_rows)

    with open(sepmc.PAPERS_OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=sepmc.PAPER_FIELDNAMES)
        writer.writeheader()
        writer.writerows(deduped)
    with open(sepmc.SUMMARY_OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=sepmc.SUMMARY_FIELDNAMES)
        writer.writeheader()
        writer.writerows(summary_rows)
    with open(sepmc.TARGETS_OUTPUT_TXT, "w", encoding="utf-8"):
        pass

    assert sepmc.load_errored_authors(sepmc.SUMMARY_OUTPUT_CSV) == ["Bad B"]

    # --- pass 2: "Bad B" now succeeds -- retry should recover and merge it in ---
    recovered_paper = make_paper("42", "Bad B", affiliation="Karolinska Institutet, Stockholm, Sweden.")
    fake_get_succeeding = make_fake_get(fail_authors=set(), papers_by_author={"Bad B": recovered_paper})
    monkeypatch.setattr(sepmc, "SESSION", type("FakeSession", (), {"get": staticmethod(fake_get_succeeding)})())

    sepmc.retry_errored_authors()

    assert sepmc.load_errored_authors(sepmc.SUMMARY_OUTPUT_CSV) == []
    with open(sepmc.PAPERS_OUTPUT_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert any(r["epmc_id"] == "42" for r in rows)
    recovered_row = next(r for r in rows if r["epmc_id"] == "42")
    assert recovered_row["sweden_affiliated_matching_authors"] == "Bad B"
