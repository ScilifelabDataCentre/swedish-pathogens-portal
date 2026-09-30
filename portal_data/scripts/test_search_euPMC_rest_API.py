"""Tests for search_euPMC_rest_API.py.

Run with: python manage.py test portal_data/scripts --settings core.settings.test
(or directly: python -m unittest test_search_euPMC_rest_API -v)

Written against the standard library's unittest (with unittest.mock) rather
than pytest, so these are actually picked up by Django's own test runner
instead of silently never running: manage.py test uses unittest's
discovery, which only executes TestCase methods, and (separately) pytest
itself wasn't a project dependency, so a pytest-based file here would fail
to even import under manage.py test. These are plain HTTP-mocked unit
tests with no database access, so no Django-specific TestCase features are
needed -- plain unittest.TestCase is enough, and pytest can still run
these too if it's ever installed, since it natively supports unittest
TestCase classes.

Everything here mocks the network layer (SESSION.get) rather than hitting
the real Europe PMC API: fast, deterministic, and doesn't depend on or add
load to an external service. Real end-to-end tests against the live API.

Requires search_euPMC_rest_API.py to be importable (same directory, or on
sys.path).
"""

from __future__ import annotations

import csv
import os
import sys
import tempfile
import time
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest import mock

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


class SepmcTestCase(unittest.TestCase):
    """Shared base class: disables real rate-limiter sleeping for every test."""

    def setUp(self) -> None:
        """Never actually sleep in tests, even if RATE_LIMITER.wait() is called."""
        self.enterContext(mock.patch.object(sepmc.RATE_LIMITER, "wait", lambda: None))

    def _patch_session(self, get_fn: Callable[..., FakeResponse]) -> None:
        """Replace sepmc.SESSION with a fake exposing only the given get_fn."""
        self.enterContext(mock.patch.object(sepmc, "SESSION", _FakeSession(get_fn)))

    def _make_tmp_dir(self) -> Path:
        """Create a temp dir, chdir into it, and restore the cwd afterwards."""
        tmp_dir = Path(self.enterContext(tempfile.TemporaryDirectory()))
        original_cwd = Path.cwd()
        os.chdir(tmp_dir)
        self.addCleanup(os.chdir, original_cwd)
        return tmp_dir


# ---------------------------------------------------------------------------
# Unit tests for pure functions -- no network involved at all
# ---------------------------------------------------------------------------


class PureFunctionTests(SepmcTestCase):
    """Unit tests for pure functions -- no network involved at all."""

    def test_build_query(self) -> None:
        """build_query wraps the base filter and rejects an empty name."""
        self.assertEqual(sepmc.build_query("Li X"), f'{sepmc.BASE_FILTER} AND AUTH:"Li X"')
        with self.assertRaises(ValueError):
            sepmc.build_query("   ")

    def test_has_strong_match(self) -> None:
        """A weak-only match is rejected; any non-weak match is accepted."""
        self.assertFalse(sepmc.has_strong_match(["host"]))
        self.assertTrue(sepmc.has_strong_match(["host", "bacteria"]))
        self.assertTrue(sepmc.has_strong_match(["pathogen"]))
        self.assertFalse(sepmc.has_strong_match([]))

    def test_format_lftp_target(self) -> None:
        """format_lftp_target builds the expected MetaboLights FTP path."""
        expected = "/pub/databases/metabolights/studies/public/MTBLS42/"
        self.assertEqual(sepmc.format_lftp_target("MTBLS42"), expected)

    def test_europepmc_max_calls_per_second_respects_both_documented_limits(self) -> None:
        """The derived single cap keeps us under both of Europe PMC's documented limits.

        Regression test for the bug where a shortened tracking window (60s ->
        15s) was compared against the still-60s-based per-minute constant,
        silently making that check unreachable and letting sustained
        throughput exceed the real per-minute limit.
        """
        self.assertLessEqual(sepmc.EUROPEPMC_MAX_CALLS_PER_SECOND, sepmc.EUROPEPMC_MAX_PER_SECOND)
        implied_per_minute = sepmc.EUROPEPMC_MAX_CALLS_PER_SECOND * 60
        self.assertLessEqual(implied_per_minute, sepmc.EUROPEPMC_MAX_PER_MINUTE)

    def test_normalize_name_strips_diacritics_and_case(self) -> None:
        """Diacritic- and case-differing spellings normalize to the same key."""
        self.assertEqual(sepmc._normalize_name("Bösch Y"), sepmc._normalize_name("Bosch y"))

    def test_sweden_flag_three_states(self) -> None:
        """_sweden_flag distinguishes Y (Sweden), N (other), and unknown ('')."""
        self.assertEqual(sepmc._sweden_flag(["Karolinska Institutet, Stockholm, Sweden."]), "Y")
        self.assertEqual(sepmc._sweden_flag(["Fudan University, China."]), "N")
        self.assertEqual(sepmc._sweden_flag([]), "")


class RateLimiterTests(SepmcTestCase):
    """Unit tests for the RateLimiter class itself."""

    def test_rate_limiter_throttles_bursts_but_not_slow_calls(self) -> None:
        """A burst over the cap is throttled; calls already under the cap are not delayed."""
        limiter = sepmc.RateLimiter(max_calls=5, period=0.5)

        start = time.monotonic()
        for _ in range(10):
            limiter.wait()
        elapsed = time.monotonic() - start
        # 10 calls against a 5-per-0.5s cap must span at least one extra window.
        self.assertGreaterEqual(elapsed, 0.4)

        # A separate limiter with calls comfortably under the cap adds no delay.
        slow_limiter = sepmc.RateLimiter(max_calls=5, period=0.5)
        start2 = time.monotonic()
        for _ in range(3):
            slow_limiter.wait()
        elapsed2 = time.monotonic() - start2
        self.assertLess(elapsed2, 0.05)


class DedupeAndExpandTests(SepmcTestCase):
    """Unit tests for dedupe_paper_rows and its inverse, expand_deduped_row_to_author_rows."""

    def test_dedupe_paper_rows_aggregates_by_source_and_id(self) -> None:
        """Two per-author rows for the same paper collapse into one aggregated row."""
        li_paper = make_paper("1", "Li X")
        muller_paper = make_paper("1", "Muller M")
        rows = [
            sepmc.flatten_paper("Li X", "q1", li_paper, ["bacteria"], [], ["China."]),
            sepmc.flatten_paper("Muller M", "q2", muller_paper, ["bacteria"], [], ["Sweden."]),
        ]
        # both rows describe the same paper (source=MED, epmc_id=1)
        deduped = sepmc.dedupe_paper_rows(rows)
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["matching_author_count"], 2)
        self.assertIn("Muller M", deduped[0]["sweden_affiliated_matching_authors"])
        self.assertIn("Li X", deduped[0]["non_sweden_affiliated_matching_authors"])

    def test_expand_deduped_row_round_trips(self) -> None:
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
        self.assertEqual(re_deduped, deduped_once)


# ---------------------------------------------------------------------------
# Mocked-network tests: normal, failing, and partial-batch search behavior.
# Includes the deliberate-failure / --retry-errors demonstration.
# ---------------------------------------------------------------------------


class SearchAuthorsTests(SepmcTestCase):
    """Mocked-network tests for search_authors."""

    def test_search_authors_finds_and_filters(self) -> None:
        """A single matching, keyword-passing paper is found and recorded."""
        paper = make_paper("1", "Good A")
        fake_get = make_fake_get(fail_authors=set(), papers_by_author={"Good A": paper})
        self._patch_session(fake_get)
        pattern = sepmc.build_keyword_pattern(["bacteria", "pathogen"])

        paper_rows, summary_rows = sepmc.search_authors(["Good A"], pattern)

        self.assertEqual(len(paper_rows), 1)
        self.assertEqual(paper_rows[0]["input_author"], "Good A")
        self.assertEqual(summary_rows[0]["match_count"], 1)
        self.assertEqual(summary_rows[0]["filtered_count"], 1)
        self.assertFalse(summary_rows[0].get("error"))

    def test_search_authors_records_error_for_failing_author(self) -> None:
        """One author's search failing doesn't affect another author's results."""
        good_paper = make_paper("1", "Good A")
        fake_get = make_fake_get(fail_authors={"Bad B"}, papers_by_author={"Good A": good_paper})
        self._patch_session(fake_get)
        pattern = sepmc.build_keyword_pattern(["bacteria", "pathogen"])

        paper_rows, summary_rows = sepmc.search_authors(["Good A", "Bad B"], pattern)

        good_summary = next(r for r in summary_rows if r["input_author"] == "Good A")
        bad_summary = next(r for r in summary_rows if r["input_author"] == "Bad B")

        self.assertFalse(good_summary.get("error"))
        self.assertTrue(bad_summary.get("error"))  # deliberately failed
        self.assertEqual(len(paper_rows), 1)  # only Good A's paper made it through
        self.assertEqual(paper_rows[0]["input_author"], "Good A")

    def test_search_authors_records_error_when_annotation_lookup_fails(self) -> None:
        """A failing text-mined-accession lookup marks the author as errored too.

        Swallowing this (recording accessions=[] instead) would be
        indistinguishable from "this paper genuinely has no accession" and
        would never be caught by --retry-errors.
        """
        paper = make_paper("1", "Good A")
        paper["hasTMAccessionNumbers"] = "Y"  # forces the annotations API fallback

        def fake_get(
            url: str, params: dict[str, Any] | None = None, timeout: float | None = None
        ) -> FakeResponse:
            if url == sepmc.ANNOTATIONS_API_URL:
                raise sepmc.requests.exceptions.ConnectionError("simulated annotations API failure")
            query = (params or {}).get("query", "")
            if 'AUTH:"Good A"' in query:
                result = {"resultList": {"result": [paper]}, "nextCursorMark": None}
                return FakeResponse(200, result)
            return FakeResponse(200, {"resultList": {"result": []}, "nextCursorMark": None})

        self._patch_session(fake_get)
        pattern = sepmc.build_keyword_pattern(["bacteria", "pathogen"])

        paper_rows, summary_rows = sepmc.search_authors(["Good A"], pattern)

        self.assertTrue(summary_rows[0].get("error"))
        self.assertEqual(paper_rows, [])  # the failing paper never got recorded

    def test_search_authors_discards_partial_batch_on_mid_batch_failure(self) -> None:
        """If paper 2 of 2 fails, paper 1's already-processed row is discarded too.

        paper_rows should only gain an author's rows once their whole batch
        succeeds -- otherwise a mid-batch failure would leave a partial,
        silently-incomplete set of that author's papers in the output.
        """
        paper_ok = make_paper("1", "Good A", title="First paper, lookup succeeds")
        paper_fails = make_paper("2", "Good A", title="Second paper, lookup fails")
        paper_fails["hasTMAccessionNumbers"] = "Y"  # forces the annotations API fallback

        def fake_get(
            url: str, params: dict[str, Any] | None = None, timeout: float | None = None
        ) -> FakeResponse:
            if url == sepmc.ANNOTATIONS_API_URL:
                raise sepmc.requests.exceptions.ConnectionError("simulated annotations API failure")
            query = (params or {}).get("query", "")
            if 'AUTH:"Good A"' in query:
                result = {
                    "resultList": {"result": [paper_ok, paper_fails]},
                    "nextCursorMark": None,
                }
                return FakeResponse(200, result)
            return FakeResponse(200, {"resultList": {"result": []}, "nextCursorMark": None})

        self._patch_session(fake_get)
        pattern = sepmc.build_keyword_pattern(["bacteria", "pathogen"])

        paper_rows, summary_rows = sepmc.search_authors(["Good A"], pattern)

        self.assertTrue(summary_rows[0].get("error"))
        self.assertEqual(paper_rows, [])  # paper 1's row must not linger either


class RetryErroredAuthorsTests(SepmcTestCase):
    """Tests for retry_errored_authors and its merge-back-into-CSV behavior."""

    def test_retry_errored_authors_merges_recovered_result(self) -> None:
        """--retry-errors recovers a previously-failed author and merges it in."""
        self._make_tmp_dir()
        Path(sepmc.KEYWORDS_CSV).write_text("bacteria\npathogen\n")

        # --- pass 1: "Bad B" fails, write it out as a normal run would ---
        fake_get_failing = make_fake_get(fail_authors={"Bad B"}, papers_by_author={})
        self._patch_session(fake_get_failing)
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

        self.assertEqual(sepmc.load_errored_authors(sepmc.SUMMARY_OUTPUT_CSV), ["Bad B"])

        # --- pass 2: "Bad B" now succeeds -- retry should recover and merge it in ---
        sweden_affiliation = "Karolinska Institutet, Stockholm, Sweden."
        recovered_paper = make_paper("42", "Bad B", affiliation=sweden_affiliation)
        papers_by_author = {"Bad B": recovered_paper}
        fake_get_succeeding = make_fake_get(fail_authors=set(), papers_by_author=papers_by_author)
        self._patch_session(fake_get_succeeding)

        sepmc.retry_errored_authors()

        self.assertEqual(sepmc.load_errored_authors(sepmc.SUMMARY_OUTPUT_CSV), [])
        with Path(sepmc.PAPERS_OUTPUT_CSV).open(newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        self.assertTrue(any(r["epmc_id"] == "42" for r in rows))
        recovered_row = next(r for r in rows if r["epmc_id"] == "42")
        self.assertEqual(recovered_row["sweden_affiliated_matching_authors"], "Bad B")

    def test_retry_errored_authors_returns_zero_when_nothing_to_retry(self) -> None:
        """No error column entries at all -> nothing to retry -> returns 0."""
        self._make_tmp_dir()
        with Path(sepmc.SUMMARY_OUTPUT_CSV).open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=sepmc.SUMMARY_FIELDNAMES)
            writer.writeheader()
            writer.writerow(
                {"input_author": "Good A", "query": "q", "match_count": 0, "filtered_count": 0}
            )

        self.assertEqual(sepmc.retry_errored_authors(), 0)

    def test_retry_errored_authors_returns_count_still_erroring(self) -> None:
        """An author that still fails on retry leaves the return value non-zero."""
        self._make_tmp_dir()
        Path(sepmc.KEYWORDS_CSV).write_text("bacteria\npathogen\n")
        with Path(sepmc.SUMMARY_OUTPUT_CSV).open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=sepmc.SUMMARY_FIELDNAMES)
            writer.writeheader()
            writer.writerow({"input_author": "Bad B", "query": "", "error": "boom"})
        Path(sepmc.PAPERS_OUTPUT_CSV).open("w", encoding="utf-8").close()
        Path(sepmc.TARGETS_OUTPUT_TXT).open("w", encoding="utf-8").close()

        # still fails on retry too
        self._patch_session(make_fake_get(fail_authors={"Bad B"}, papers_by_author={}))

        self.assertEqual(sepmc.retry_errored_authors(), 1)


# ---------------------------------------------------------------------------
# Exit codes: 0 clean, 3 partial (needs --retry-errors), 1 unexpected
# ---------------------------------------------------------------------------


class MainExitCodeTests(SepmcTestCase):
    """Exit codes: 0 clean, 3 partial (needs --retry-errors), 1 unexpected."""

    def test_main_returns_3_when_an_author_errors(self) -> None:
        """A full run with one failing author exits 3, not 0."""
        self._make_tmp_dir()
        self.enterContext(mock.patch.object(sys, "argv", ["search_euPMC_rest_API.py"]))
        Path(sepmc.KEYWORDS_CSV).write_text("bacteria\npathogen\n")
        Path("publications.csv").write_text('Authors\n"Good A, Bad B"\n')

        good_paper = make_paper("1", "Good A")
        fake_get = make_fake_get(fail_authors={"Bad B"}, papers_by_author={"Good A": good_paper})
        self._patch_session(fake_get)

        self.assertEqual(sepmc.main(), 3)

    def test_main_returns_0_when_everything_succeeds(self) -> None:
        """A full run with no failing authors exits 0."""
        self._make_tmp_dir()
        self.enterContext(mock.patch.object(sys, "argv", ["search_euPMC_rest_API.py"]))
        Path(sepmc.KEYWORDS_CSV).write_text("bacteria\npathogen\n")
        Path("publications.csv").write_text('Authors\n"Good A"\n')

        good_paper = make_paper("1", "Good A")
        fake_get = make_fake_get(fail_authors=set(), papers_by_author={"Good A": good_paper})
        self._patch_session(fake_get)

        self.assertEqual(sepmc.main(), 0)

    def test_main_returns_1_on_unexpected_failure(self) -> None:
        """A missing required input file is an unexpected failure -> exit 1."""
        self._make_tmp_dir()
        self.enterContext(mock.patch.object(sys, "argv", ["search_euPMC_rest_API.py"]))
        # deliberately do NOT create publications.csv

        self.assertEqual(sepmc.main(), 1)


if __name__ == "__main__":
    unittest.main()
