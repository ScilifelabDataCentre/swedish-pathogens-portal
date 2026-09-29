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
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import search_euPMC_rest_API as sepmc

# ---------------------------------------------------------------------------
# Small helpers for building fake Europe PMC responses
# ---------------------------------------------------------------------------


class FakeResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(self, status_code: int = 200, json_data: dict | None = None) -> None:
        """Store the status code and JSON body this fake response returns."""
        self.status_code = status_code
        self._json_data = json_data or {}

    def raise_for_status(self) -> None:
        """Raise an HTTPError if the status code indicates a failure."""
        if self.status_code >= 400:
            raise sepmc.requests.exceptions.HTTPError(f"{self.status_code} error")

    def json(self) -> dict:
        """Return the canned JSON body."""
        return self._json_data


class _FakeSession:
    """A minimal requests.Session stand-in exposing only .get()."""

    def __init__(self, get_fn: Callable[..., FakeResponse]) -> None:
        """Wrap the given fake get() implementation."""
        self.get = get_fn


def _patch_session(monkeypatch: pytest.MonkeyPatch, get_fn: Callable[..., FakeResponse]) -> None:
    """Replace sepmc.SESSION with a fake exposing only the given get_fn."""
    monkeypatch.setattr(sepmc, "SESSION", _FakeSession(get_fn))


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
        author_affiliation = {"authorAffiliation": [{"affiliation": affiliation}]}
        paper["authorList"] = {
            "author": [
                {
                    "fullName": author_name,
                    "authorAffiliationDetailsList": author_affiliation,
                }
            ]
        }
    return paper


def make_fake_get(
    fail_authors: set[str], papers_by_author: dict[str, dict]
) -> Callable[..., FakeResponse]:
    """Build a fake SESSION.get(...).

    Raises (simulating an exhausted-retries network failure) for any
    author name appearing in `fail_authors`'s AUTH: query, and otherwise
    returns a canned single-page result for that author if one was
    registered in `papers_by_author`, else an empty result.
    """

    def fake_get(
        url: str, params: dict[str, Any] | None = None, timeout: float | None = None
    ) -> FakeResponse:  # noqa: ARG001
        query = (params or {}).get("query", "")
        for author in fail_authors:
            if f'AUTH:"{author}"' in query:
                raise sepmc.requests.exceptions.ConnectionError(
                    f"Max retries exceeded (simulated failure for {author})"
                )
        for author, paper in papers_by_author.items():
            if f'AUTH:"{author}"' in query:
                result = {"resultList": {"result": [paper]}, "nextCursorMark": None}
                return FakeResponse(200, result)
        return FakeResponse(200, {"resultList": {"result": []}, "nextCursorMark": None})

    return fake_get


@pytest.fixture(autouse=True)
def _no_real_sleeping(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never actually sleep in tests, even if a code path calls RATE_LIMITER.wait()."""
    monkeypatch.setattr(sepmc.RATE_LIMITER, "wait", lambda: None)


# ---------------------------------------------------------------------------
# Unit tests for pure functions -- no network involved at all
# ---------------------------------------------------------------------------


def test_build_query() -> None:
    """build_query wraps the base filter and rejects an empty name."""
    assert sepmc.build_query("Li X") == f'{sepmc.BASE_FILTER} AND AUTH:"Li X"'  # noqa: S101
    with pytest.raises(ValueError):
        sepmc.build_query("   ")


def test_has_strong_match() -> None:
    """A weak-only match is rejected; any non-weak match is accepted."""
    assert sepmc.has_strong_match(["host"]) is False  # noqa: S101
    assert sepmc.has_strong_match(["host", "bacteria"]) is True  # noqa: S101
    assert sepmc.has_strong_match(["pathogen"]) is True  # noqa: S101
    assert sepmc.has_strong_match([]) is False  # noqa: S101


def test_format_lftp_target() -> None:
    """format_lftp_target builds the expected MetaboLights FTP path."""
    expected = "/pub/databases/metabolights/studies/public/MTBLS42/"
    assert sepmc.format_lftp_target("MTBLS42") == expected  # noqa: S101


def test_normalize_name_strips_diacritics_and_case() -> None:
    """Diacritic- and case-differing spellings normalize to the same key."""
    assert sepmc._normalize_name("Bösch Y") == sepmc._normalize_name("Bosch y")  # noqa: S101


def test_sweden_flag_three_states() -> None:
    """_sweden_flag distinguishes Y (Sweden), N (other), and unknown ('')."""
    assert sepmc._sweden_flag(["Karolinska Institutet, Stockholm, Sweden."]) == "Y"  # noqa: S101
    assert sepmc._sweden_flag(["Fudan University, China."]) == "N"  # noqa: S101
    assert sepmc._sweden_flag([]) == ""  # noqa: S101


def test_dedupe_paper_rows_aggregates_by_source_and_id() -> None:
    """Two per-author rows for the same paper collapse into one aggregated row."""
    li_paper = make_paper("1", "Li X")
    muller_paper = make_paper("1", "Muller M")
    rows = [
        sepmc.flatten_paper("Li X", "q1", li_paper, ["bacteria"], [], ["China."]),
        sepmc.flatten_paper("Muller M", "q2", muller_paper, ["bacteria"], [], ["Sweden."]),
    ]
    # both rows describe the same paper (source=MED, epmc_id=1)
    deduped = sepmc.dedupe_paper_rows(rows)
    assert len(deduped) == 1  # noqa: S101
    assert deduped[0]["matching_author_count"] == 2  # noqa: S101
    assert "Muller M" in deduped[0]["sweden_affiliated_matching_authors"]  # noqa: S101
    assert "Li X" in deduped[0]["non_sweden_affiliated_matching_authors"]  # noqa: S101


def test_expand_deduped_row_round_trips() -> None:
    """Dedupe -> expand -> re-dedupe reproduces the exact original row."""
    li_paper = make_paper("1", "Li X")
    muller_paper = make_paper("1", "Muller M")
    rows = [
        sepmc.flatten_paper("Li X", "q1", li_paper, ["bacteria"], [], ["China."]),
        sepmc.flatten_paper("Muller M", "q2", muller_paper, ["bacteria"], [], ["Sweden."]),
    ]
    deduped_once = sepmc.dedupe_paper_rows(rows)
    expanded = sepmc.expand_deduped_row_to_author_rows(deduped_once[0])
    re_deduped = sepmc.dedupe_paper_rows(expanded)
    assert re_deduped == deduped_once  # noqa: S101


# ---------------------------------------------------------------------------
# Mocked-network tests: normal search behavior
# ---------------------------------------------------------------------------


def test_search_authors_finds_and_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    """A single matching, keyword-passing paper is found and recorded."""
    paper = make_paper("1", "Good A")
    fake_get = make_fake_get(fail_authors=set(), papers_by_author={"Good A": paper})
    _patch_session(monkeypatch, fake_get)
    pattern = sepmc.build_keyword_pattern(["bacteria", "pathogen"])

    paper_rows, summary_rows = sepmc.search_authors(["Good A"], pattern)

    assert len(paper_rows) == 1  # noqa: S101
    assert paper_rows[0]["input_author"] == "Good A"  # noqa: S101
    assert summary_rows[0]["match_count"] == 1  # noqa: S101
    assert summary_rows[0]["filtered_count"] == 1  # noqa: S101
    assert not summary_rows[0].get("error")  # noqa: S101


# ---------------------------------------------------------------------------
# The actual ask: deliberately fail a search, then verify --retry-errors
# recovers and merges the result in.
# ---------------------------------------------------------------------------


def test_search_authors_records_error_for_failing_author(monkeypatch: pytest.MonkeyPatch) -> None:
    """One author's search failing doesn't affect another author's results."""
    good_paper = make_paper("1", "Good A")
    fake_get = make_fake_get(fail_authors={"Bad B"}, papers_by_author={"Good A": good_paper})
    _patch_session(monkeypatch, fake_get)
    pattern = sepmc.build_keyword_pattern(["bacteria", "pathogen"])

    paper_rows, summary_rows = sepmc.search_authors(["Good A", "Bad B"], pattern)

    good_summary = next(r for r in summary_rows if r["input_author"] == "Good A")
    bad_summary = next(r for r in summary_rows if r["input_author"] == "Bad B")

    assert not good_summary.get("error")  # noqa: S101
    assert bad_summary.get("error")  # noqa: S101 -- deliberately failed
    assert len(paper_rows) == 1  # noqa: S101 -- only Good A's paper made it through
    assert paper_rows[0]["input_author"] == "Good A"  # noqa: S101


def test_retry_errored_authors_merges_recovered_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """--retry-errors recovers a previously-failed author and merges it in."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / sepmc.KEYWORDS_CSV).write_text("bacteria\npathogen\n")

    # --- pass 1: "Bad B" fails, write it out as a normal run would ---
    fake_get_failing = make_fake_get(fail_authors={"Bad B"}, papers_by_author={})
    _patch_session(monkeypatch, fake_get_failing)
    pattern = sepmc.build_keyword_pattern(["bacteria", "pathogen"])

    paper_rows, summary_rows = sepmc.search_authors(["Bad B"], pattern)
    deduped = sepmc.dedupe_paper_rows(paper_rows)

    with Path(sepmc.PAPERS_OUTPUT_CSV).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=sepmc.PAPER_FIELDNAMES)
        writer.writeheader()
        writer.writerows(deduped)
    with Path(sepmc.SUMMARY_OUTPUT_CSV).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=sepmc.SUMMARY_FIELDNAMES)
        writer.writeheader()
        writer.writerows(summary_rows)
    Path(sepmc.TARGETS_OUTPUT_TXT).open("w", encoding="utf-8").close()

    assert sepmc.load_errored_authors(sepmc.SUMMARY_OUTPUT_CSV) == ["Bad B"]  # noqa: S101

    # --- pass 2: "Bad B" now succeeds -- retry should recover and merge it in ---
    sweden_affiliation = "Karolinska Institutet, Stockholm, Sweden."
    recovered_paper = make_paper("42", "Bad B", affiliation=sweden_affiliation)
    papers_by_author = {"Bad B": recovered_paper}
    fake_get_succeeding = make_fake_get(fail_authors=set(), papers_by_author=papers_by_author)
    _patch_session(monkeypatch, fake_get_succeeding)

    sepmc.retry_errored_authors()

    assert sepmc.load_errored_authors(sepmc.SUMMARY_OUTPUT_CSV) == []  # noqa: S101
    with Path(sepmc.PAPERS_OUTPUT_CSV).open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert any(r["epmc_id"] == "42" for r in rows)  # noqa: S101
    recovered_row = next(r for r in rows if r["epmc_id"] == "42")
    assert recovered_row["sweden_affiliated_matching_authors"] == "Bad B"  # noqa: S101


# ---------------------------------------------------------------------------
# Exit codes: 0 clean, 3 partial (needs --retry-errors), 1 unexpected
# ---------------------------------------------------------------------------


def test_retry_errored_authors_returns_zero_when_nothing_to_retry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No error column entries at all -> nothing to retry -> returns 0."""
    monkeypatch.chdir(tmp_path)
    with Path(sepmc.SUMMARY_OUTPUT_CSV).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=sepmc.SUMMARY_FIELDNAMES)
        writer.writeheader()
        writer.writerow(
            {"input_author": "Good A", "query": "q", "match_count": 0, "filtered_count": 0}
        )

    assert sepmc.retry_errored_authors() == 0  # noqa: S101


def test_retry_errored_authors_returns_count_still_erroring(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An author that still fails on retry leaves the return value non-zero."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / sepmc.KEYWORDS_CSV).write_text("bacteria\npathogen\n")
    with Path(sepmc.SUMMARY_OUTPUT_CSV).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=sepmc.SUMMARY_FIELDNAMES)
        writer.writeheader()
        writer.writerow({"input_author": "Bad B", "query": "", "error": "boom"})
    Path(sepmc.PAPERS_OUTPUT_CSV).open("w", encoding="utf-8").close()
    Path(sepmc.TARGETS_OUTPUT_TXT).open("w", encoding="utf-8").close()

    # still fails on retry too
    _patch_session(monkeypatch, make_fake_get(fail_authors={"Bad B"}, papers_by_author={}))

    assert sepmc.retry_errored_authors() == 1  # noqa: S101


def test_main_returns_3_when_an_author_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A full run with one failing author exits 3, not 0."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["search_euPMC_rest_API.py"])
    (tmp_path / sepmc.KEYWORDS_CSV).write_text("bacteria\npathogen\n")
    (tmp_path / "publications.csv").write_text('Authors\n"Good A, Bad B"\n')

    good_paper = make_paper("1", "Good A")
    fake_get = make_fake_get(fail_authors={"Bad B"}, papers_by_author={"Good A": good_paper})
    _patch_session(monkeypatch, fake_get)

    assert sepmc.main() == 3  # noqa: S101


def test_main_returns_0_when_everything_succeeds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A full run with no failing authors exits 0."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["search_euPMC_rest_API.py"])
    (tmp_path / sepmc.KEYWORDS_CSV).write_text("bacteria\npathogen\n")
    (tmp_path / "publications.csv").write_text('Authors\n"Good A"\n')

    good_paper = make_paper("1", "Good A")
    fake_get = make_fake_get(fail_authors=set(), papers_by_author={"Good A": good_paper})
    _patch_session(monkeypatch, fake_get)

    assert sepmc.main() == 0  # noqa: S101


def test_main_returns_1_on_unexpected_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A missing required input file is an unexpected failure -> exit 1."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["search_euPMC_rest_API.py"])
    # deliberately do NOT create publications.csv

    assert sepmc.main() == 1  # noqa: S101
