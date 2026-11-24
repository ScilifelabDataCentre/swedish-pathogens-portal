"""Tests for portal_data.metabolights.europepmc and the metabolights_search command.

Written against the standard library's unittest (with unittest.mock) rather
than pytest, since Django's test runner (manage.py test) only collects
unittest-style tests. These are plain HTTP-mocked unit tests with no
database access, so SimpleTestCase is enough.

Everything here mocks the network layer -- the shared httpx client is
swapped for one backed by httpx.MockTransport -- rather than hitting the
real Europe PMC API: fast, deterministic, and doesn't depend on or add
load to an external service. Real end-to-end tests against the live API
are better kept as an occasional manual/scheduled smoke test rather than
part of this suite.
"""

from __future__ import annotations

import csv
import io
import logging
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest import mock

import httpx
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from cms.services import api_client
from portal_data.metabolights import europepmc as sepmc

# ---------------------------------------------------------------------------
# Small helpers for building fake Europe PMC responses
# ---------------------------------------------------------------------------


class FakeResponse:
    """A canned response: status code, JSON body and optional headers."""

    def __init__(
        self,
        status_code: int = 200,
        json_data: dict | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Store what the mock transport should answer with."""
        self.status_code = status_code
        self.json_data = json_data or {}
        self.headers = headers or {}


def mock_client(get_fn: Callable[..., FakeResponse]) -> httpx.Client:
    """Build a real httpx.Client whose requests are answered by get_fn.

    get_fn is called as get_fn(url, params=..., timeout=None) with the URL
    minus its query string and the query parameters as a dict, and returns
    a FakeResponse -- or raises, e.g. httpx.ConnectError, to simulate a
    network failure.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url.copy_with(query=None))
        canned = get_fn(url, params=dict(request.url.params), timeout=None)
        return httpx.Response(canned.status_code, json=canned.json_data, headers=canned.headers)

    return httpx.Client(transport=httpx.MockTransport(handler))


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


def researcher(family: str, initials: str, n_publications: int = 1, **extra: object) -> dict:
    """Build a researcher record shaped like publications.scilifelab.se/researchers_json."""
    return {
        "family": family,
        "given": "",
        "initials": initials,
        "orcid": None,
        "affiliations": [],
        "n_publications": n_publications,
        **extra,
    }


def make_fake_get(
    fail_authors: set[str],
    papers_by_author: dict[str, dict],
    researchers: list[dict] | None = None,
) -> Callable[..., FakeResponse]:
    """Build a fake get(...) for mock_client.

    Raises (simulating an exhausted-retries network failure) for any
    author name appearing in `fail_authors`'s AUTH: query, and otherwise
    returns a canned single-page result for that author if one was
    registered in `papers_by_author`, else an empty result. Requests for
    the SciLifeLab researcher list get `researchers`.
    """

    def fake_get(
        url: str, params: dict[str, Any] | None = None, timeout: float | None = None
    ) -> FakeResponse:  # noqa: ARG001
        if url == sepmc.RESEARCHERS_JSON_URL:
            return FakeResponse(200, {"entity": "researchers", "researchers": researchers or []})
        query = (params or {}).get("query", "")
        for author in fail_authors:
            if f'AUTH:"{author}"' in query:
                raise httpx.ConnectError(f"Max retries exceeded (simulated failure for {author})")
        for author, paper in papers_by_author.items():
            if f'AUTH:"{author}"' in query:
                result = {"resultList": {"result": [paper]}, "nextCursorMark": None}
                return FakeResponse(200, result)
        return FakeResponse(200, {"resultList": {"result": []}, "nextCursorMark": None})

    return fake_get


class SepmcTestCase(SimpleTestCase):
    """Shared base class: disables real rate-limiter sleeping for every test."""

    def setUp(self) -> None:
        """Never actually sleep in tests: no rate-limiter or retry waits."""
        self.enterContext(mock.patch.object(sepmc.RATE_LIMITER, "wait", lambda: None))
        self.retry_sleeps: list[float] = []
        self.enterContext(mock.patch.object(sepmc, "_retry_sleep", self.retry_sleeps.append))

    def _patch_session(self, get_fn: Callable[..., FakeResponse]) -> None:
        """Answer every request on the shared httpx client with get_fn."""
        client = mock_client(get_fn)
        self.addCleanup(client.close)
        self.enterContext(mock.patch.object(api_client, "CLIENT", client))

    def _make_tmp_dir(self) -> Path:
        """Create a temp dir that is removed after the test."""
        return Path(self.enterContext(tempfile.TemporaryDirectory()))

    @staticmethod
    def _write_keywords(directory: Path) -> Path:
        """Write a small keyword list into directory and return its path."""
        path = directory / "keywords.csv"
        path.write_text("bacteria\npathogen\n")
        return path


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

    def test_study_ftp_path(self) -> None:
        """study_ftp_path builds the expected MetaboLights FTP path."""
        expected = "/pub/databases/metabolights/studies/public/MTBLS42/"
        self.assertEqual(sepmc.study_ftp_path("MTBLS42"), expected)

    def test_longer_keyword_beats_an_abbreviation_it_starts_with(self) -> None:
        """'SARS-CoV-2' is matched as itself, not as the case-sensitive 'SARS'."""
        pattern = sepmc.build_keyword_pattern(["SARS", "SARS-CoV-2", "GAS", "bacteria"])

        self.assertEqual(
            sepmc.find_keyword_matches("Metabolic effects of SARS-CoV-2 infection", pattern),
            ["SARS-CoV-2"],
        )
        self.assertEqual(sepmc.find_keyword_matches("The 2003 SARS outbreak", pattern), ["SARS"])
        # Abbreviations stay case-sensitive; other keywords don't.
        self.assertEqual(sepmc.find_keyword_matches("gas chromatography", pattern), [])
        self.assertEqual(sepmc.find_keyword_matches("BACTERIA", pattern), ["BACTERIA"])

    def test_bundled_keywords_file_exists(self) -> None:
        """The default keyword list ships next to the module."""
        self.assertTrue(sepmc.DEFAULT_KEYWORDS_CSV.is_file())
        self.assertTrue(sepmc.load_keywords(sepmc.DEFAULT_KEYWORDS_CSV))

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
                raise httpx.ConnectError("simulated annotations API failure")
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
                raise httpx.ConnectError("simulated annotations API failure")
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
        tmp_dir = self._make_tmp_dir()
        keywords = self._write_keywords(tmp_dir)
        summary_csv = tmp_dir / sepmc.SUMMARY_OUTPUT_CSV
        papers_csv = tmp_dir / sepmc.PAPERS_OUTPUT_CSV

        # --- pass 1: "Bad B" fails, written out by a normal run ---
        publications = tmp_dir / sepmc.PUBLICATIONS_CSV
        publications.write_text('Authors\n"Bad B"\n')
        self._patch_session(make_fake_get(fail_authors={"Bad B"}, papers_by_author={}))
        first = sepmc.run_search(tmp_dir, publications_csv=publications, keywords_csv=keywords)

        self.assertEqual(first.errored_authors, 1)
        self.assertEqual(sepmc.load_errored_authors(summary_csv), ["Bad B"])

        # --- pass 2: "Bad B" now succeeds -- retry should recover and merge it in ---
        sweden_affiliation = "Karolinska Institutet, Stockholm, Sweden."
        recovered_paper = make_paper("42", "Bad B", affiliation=sweden_affiliation)
        papers_by_author = {"Bad B": recovered_paper}
        fake_get_succeeding = make_fake_get(fail_authors=set(), papers_by_author=papers_by_author)
        self._patch_session(fake_get_succeeding)

        outcome = sepmc.retry_errored_authors(tmp_dir, keywords_csv=keywords)

        self.assertEqual(outcome.errored_authors, 0)
        self.assertEqual(sepmc.load_errored_authors(summary_csv), [])
        with papers_csv.open(newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        self.assertTrue(any(r["epmc_id"] == "42" for r in rows))
        recovered_row = next(r for r in rows if r["epmc_id"] == "42")
        self.assertEqual(recovered_row["sweden_affiliated_matching_authors"], "Bad B")

    def test_retry_errored_authors_does_nothing_when_nothing_to_retry(self) -> None:
        """No error column entries at all -> nothing to retry, nothing rewritten."""
        tmp_dir = self._make_tmp_dir()
        with (tmp_dir / sepmc.SUMMARY_OUTPUT_CSV).open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=sepmc.SUMMARY_FIELDNAMES)
            writer.writeheader()
            writer.writerow(
                {"input_author": "Good A", "query": "q", "match_count": 0, "filtered_count": 0}
            )

        outcome = sepmc.retry_errored_authors(tmp_dir)

        self.assertEqual(outcome.authors_searched, 0)
        self.assertEqual(outcome.errored_authors, 0)
        self.assertFalse((tmp_dir / sepmc.PAPERS_OUTPUT_CSV).exists())

    def test_retry_errored_authors_returns_count_still_erroring(self) -> None:
        """An author that still fails on retry leaves errored_authors non-zero."""
        tmp_dir = self._make_tmp_dir()
        keywords = self._write_keywords(tmp_dir)
        with (tmp_dir / sepmc.SUMMARY_OUTPUT_CSV).open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=sepmc.SUMMARY_FIELDNAMES)
            writer.writeheader()
            writer.writerow({"input_author": "Bad B", "query": "", "error": "boom"})

        # still fails on retry too
        self._patch_session(make_fake_get(fail_authors={"Bad B"}, papers_by_author={}))

        outcome = sepmc.retry_errored_authors(tmp_dir, keywords_csv=keywords)

        self.assertEqual(outcome.errored_authors, 1)
        self.assertEqual(sepmc.load_errored_authors(tmp_dir / sepmc.SUMMARY_OUTPUT_CSV), ["Bad B"])


class RetryTests(SepmcTestCase):
    """_get's retry policy: transient failures are retried, others raised."""

    def _responses(self, *answers: FakeResponse | Exception) -> list[str]:
        """Answer successive requests with answers in order; return the URLs requested."""
        queue = list(answers)
        requested: list[str] = []

        def fake_get(url: str, params: object = None, timeout: object = None) -> FakeResponse:
            requested.append(url)
            answer = queue.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer

        self._patch_session(fake_get)
        return requested

    def test_retries_throttling_then_succeeds(self) -> None:
        """A 503 then a 200 returns the 200, after an exponential backoff wait."""
        requested = self._responses(FakeResponse(503), FakeResponse(200, {"ok": True}))

        response = sepmc._get("https://example.org/api")

        self.assertEqual(response.json(), {"ok": True})
        self.assertEqual(len(requested), 2)
        self.assertEqual(self.retry_sleeps, [sepmc.RETRY_BACKOFF_SECONDS])

    def test_honours_retry_after_capped(self) -> None:
        """Retry-After decides the wait, but never beyond MAX_RETRY_AFTER_SECONDS."""
        self._responses(
            FakeResponse(429, headers={"Retry-After": "7"}),
            FakeResponse(429, headers={"Retry-After": "100000"}),
            FakeResponse(200),
        )

        sepmc._get("https://example.org/api")

        self.assertEqual(self.retry_sleeps, [7.0, sepmc.MAX_RETRY_AFTER_SECONDS])

    def test_retry_after_http_date(self) -> None:
        """An HTTP-date Retry-After in the past means no extra wait."""
        self._responses(
            FakeResponse(503, headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"}),
            FakeResponse(200),
        )

        sepmc._get("https://example.org/api")

        self.assertEqual(self.retry_sleeps, [0.0])

    def test_retries_transport_errors(self) -> None:
        """A dropped connection is retried like a 5xx."""
        requested = self._responses(httpx.ConnectError("reset"), FakeResponse(200))

        sepmc._get("https://example.org/api")

        self.assertEqual(len(requested), 2)

    def test_gives_up_after_max_retries(self) -> None:
        """A persistent 503 raises once the retries are used up."""
        requested = self._responses(*[FakeResponse(503)] * (sepmc.MAX_RETRIES + 1))

        with self.assertRaises(httpx.HTTPStatusError):
            sepmc._get("https://example.org/api")
        self.assertEqual(len(requested), sepmc.MAX_RETRIES + 1)
        self.assertEqual(self.retry_sleeps, [1.0, 2.0, 4.0])

    def test_does_not_retry_client_errors(self) -> None:
        """A 404 is a real answer, raised straight away."""
        requested = self._responses(FakeResponse(404))

        with self.assertRaises(httpx.HTTPStatusError):
            sepmc._get("https://example.org/api")
        self.assertEqual(len(requested), 1)
        self.assertEqual(self.retry_sleeps, [])


class RunSearchTests(SepmcTestCase):
    """Tests for a full run_search, end to end against the mocked network."""

    def test_run_search_writes_all_three_outputs(self) -> None:
        """Papers, summary and targets.txt all land in the work dir."""
        tmp_dir = self._make_tmp_dir()
        keywords = self._write_keywords(tmp_dir)
        paper = make_paper("1", "Good A")
        paper["dbCrossReferenceList"] = {
            "dbCrossReference": [
                {"type": "METABOLIGHTS", "accessionList": {"accession": [{"value": "mtbls7"}]}}
            ]
        }
        self._patch_session(
            make_fake_get(
                fail_authors=set(),
                papers_by_author={"Good A": paper},
                researchers=[researcher("Good", "A")],
            )
        )
        messages: list[str] = []

        outcome = sepmc.run_search(tmp_dir, keywords_csv=keywords, progress=messages.append)

        self.assertEqual(outcome, sepmc.SearchOutcome(1, 0, 1, 1, 1))
        self.assertEqual(
            (tmp_dir / sepmc.TARGETS_OUTPUT_TXT).read_text(),
            "/pub/databases/metabolights/studies/public/MTBLS7/\n",
        )
        self.assertTrue((tmp_dir / sepmc.PAPERS_OUTPUT_CSV).exists())
        self.assertTrue((tmp_dir / sepmc.SUMMARY_OUTPUT_CSV).exists())
        self.assertTrue(any("Good A" in m for m in messages))

    def test_run_search_reads_authors_from_publications_csv_when_given(self) -> None:
        """--publications bypasses the researcher list entirely."""
        tmp_dir = self._make_tmp_dir()
        publications = tmp_dir / "export.csv"
        publications.write_text('Authors\n"Csv A, Csv B"\n')
        fake_get = make_fake_get(set(), {}, researchers=[researcher("Feed", "X")])
        self._patch_session(fake_get)

        sepmc.run_search(
            tmp_dir, publications_csv=publications, keywords_csv=self._write_keywords(tmp_dir)
        )

        with (tmp_dir / sepmc.SUMMARY_OUTPUT_CSV).open(newline="", encoding="utf-8") as f:
            searched = [row["input_author"] for row in csv.DictReader(f)]
        self.assertEqual(searched, ["Csv A", "Csv B"])

    def test_run_search_fails_before_writing_when_publications_missing(self) -> None:
        """A missing input raises without creating any output."""
        tmp_dir = self._make_tmp_dir()

        with self.assertRaises(FileNotFoundError):
            sepmc.run_search(
                tmp_dir,
                publications_csv=tmp_dir / "missing.csv",
                keywords_csv=self._write_keywords(tmp_dir),
            )
        self.assertFalse((tmp_dir / sepmc.SUMMARY_OUTPUT_CSV).exists())

    def test_run_search_refuses_an_empty_researcher_list(self) -> None:
        """An empty feed is an error, not a clean run that searched nobody."""
        tmp_dir = self._make_tmp_dir()
        self._patch_session(make_fake_get(set(), {}, researchers=[]))

        with self.assertRaises(ValueError):
            sepmc.run_search(tmp_dir, keywords_csv=self._write_keywords(tmp_dir))
        self.assertFalse((tmp_dir / sepmc.SUMMARY_OUTPUT_CSV).exists())


class ResearcherListTests(SepmcTestCase):
    """Reading authors from the SciLifeLab researcher list."""

    def test_builds_lastname_initials_names(self) -> None:
        """Family name + initials gives the CSV's "Lastname Initials" form."""
        records = [researcher("Aaltonen", "K"), researcher("'t Hart", "LM")]
        self.assertEqual(sepmc.authors_from_researchers(records), ["Aaltonen K", "'t Hart LM"])

    def test_derives_missing_initials_from_given_names(self) -> None:
        """Initials fall back to the first letters of the given names."""
        records = [researcher("Aabakke", "", given="Anna J M")]
        self.assertEqual(sepmc.authors_from_researchers(records), ["Aabakke AJM"])

    def test_skips_unusable_and_unpublished_researchers(self) -> None:
        """No family name, no initials at all, or no publications -> skipped."""
        records = [
            researcher("", "A"),
            researcher("Nameless", ""),
            researcher("Unpublished", "U", n_publications=0),
            researcher("Kept", "K"),
            "not a record",
        ]
        self.assertEqual(sepmc.authors_from_researchers(records), ["Kept K"])

    def test_deduplicates_and_normalises_spacing(self) -> None:
        """The same person listed twice (or with stray spaces/dots) is searched once."""
        records = [researcher("Li", "X"), researcher(" Li ", "X."), researcher("Li", "XY")]
        self.assertEqual(sepmc.authors_from_researchers(records), ["Li X", "Li XY"])

    def test_fetch_researchers_rejects_unexpected_payload(self) -> None:
        """A response without a researchers list raises instead of returning []."""
        self._patch_session(lambda url, params=None, timeout=None: FakeResponse(200, {"x": 1}))
        with self.assertRaises(ValueError):
            sepmc.fetch_researchers()


# ---------------------------------------------------------------------------
# The management command's exit codes: 0 clean, 3 partial (needs
# --retry-errors), 1 the run did not complete
# ---------------------------------------------------------------------------


class MetabolightsSearchCommandTests(SepmcTestCase):
    """Exit codes of manage.py metabolights_search."""

    def _call(self, *args: str) -> str:
        """Run the command against the temp work dir and return its stdout."""
        stdout = io.StringIO()
        call_command(
            "metabolights_search",
            "--work-dir",
            str(self.tmp_dir),
            "--keywords",
            str(self.keywords),
            *args,
            stdout=stdout,
        )
        return stdout.getvalue()

    def setUp(self) -> None:
        """Give each test a work dir with a keyword list in it."""
        super().setUp()
        self.tmp_dir = self._make_tmp_dir()
        self.keywords = self._write_keywords(self.tmp_dir)

    def test_exits_3_when_an_author_errors(self) -> None:
        """A full run with one failing author exits 3, not 0."""
        good_paper = make_paper("1", "Good A")
        fake_get = make_fake_get(
            fail_authors={"Bad B"},
            papers_by_author={"Good A": good_paper},
            researchers=[researcher("Good", "A"), researcher("Bad", "B")],
        )
        self._patch_session(fake_get)

        with self.assertRaises(CommandError) as raised:
            self._call()
        self.assertEqual(raised.exception.returncode, 3)
        self.assertIn("--retry-errors", str(raised.exception))

    def test_succeeds_when_everything_succeeds(self) -> None:
        """A full run with no failing authors completes without raising."""
        good_paper = make_paper("1", "Good A")
        fake_get = make_fake_get(
            fail_authors=set(),
            papers_by_author={"Good A": good_paper},
            researchers=[researcher("Good", "A")],
        )
        self._patch_session(fake_get)

        output = self._call()

        self.assertIn("1 unique papers", output)

    def test_publications_option_reads_a_csv_export(self) -> None:
        """--publications searches the CSV's authors instead of the researcher list."""
        publications = self.tmp_dir / "export.csv"
        publications.write_text('Authors\n"Good A"\n')
        good_paper = make_paper("1", "Good A")
        self._patch_session(make_fake_get(set(), {"Good A": good_paper}, researchers=[]))

        output = self._call("--publications", str(publications))

        self.assertIn("1 unique papers", output)

    def test_exits_1_when_publications_missing(self) -> None:
        """A missing --publications file is a failed run -> exit 1."""
        with self.assertRaises(CommandError) as raised:
            self._call("--publications", str(self.tmp_dir / "missing.csv"))
        self.assertEqual(raised.exception.returncode, 1)

    def test_exits_1_when_researcher_list_unreachable(self) -> None:
        """Failing to download the researcher list is a failed run -> exit 1."""

        def fake_get(url: str, params: object = None, timeout: object = None) -> FakeResponse:
            raise httpx.ConnectError("simulated outage")

        self._patch_session(fake_get)
        with self.assertRaises(CommandError) as raised:
            self._call()
        self.assertEqual(raised.exception.returncode, 1)
        self.assertFalse((self.tmp_dir / sepmc.SUMMARY_OUTPUT_CSV).exists())

    def test_retry_errors_exits_3_while_authors_still_fail(self) -> None:
        """--retry-errors keeps exiting 3 until every author has recovered."""
        self._patch_session(make_fake_get({"Bad B"}, {}, researchers=[researcher("Bad", "B")]))
        with self.assertRaises(CommandError):
            self._call()

        with self.assertRaises(CommandError) as raised:
            self._call("--retry-errors")
        self.assertEqual(raised.exception.returncode, 3)

        self._patch_session(make_fake_get(fail_authors=set(), papers_by_author={}))
        self._call("--retry-errors")  # recovered: no exception

    def test_quietens_httpx_request_logging_during_the_run(self) -> None:
        """Per-request INFO logs are hidden by default and the level is restored after."""
        self._patch_session(make_fake_get(set(), {}, researchers=[researcher("Good", "A")]))
        httpx_logger = logging.getLogger("httpx")
        before = httpx_logger.level

        with self.assertNoLogs("httpx", level="INFO"):
            self._call()
        self.assertEqual(httpx_logger.level, before)

        with self.assertLogs("httpx", level="INFO"):
            self._call("--verbosity", "3")

    def test_work_dir_defaults_to_setting(self) -> None:
        """Without --work-dir, <DATASETS_ROOT>/metabolights_search is used."""
        self._patch_session(make_fake_get(set(), {}, researchers=[researcher("Good", "A")]))

        with override_settings(DATASETS_ROOT=str(self.tmp_dir)):
            call_command(
                "metabolights_search", "--keywords", str(self.keywords), stdout=io.StringIO()
            )

        self.assertTrue((self.tmp_dir / "metabolights_search" / sepmc.SUMMARY_OUTPUT_CSV).exists())

    def test_unwritable_work_dir_fails_before_any_request(self) -> None:
        """A read-only work dir is caught up front, not after an hour of searching."""
        requested: list[str] = []

        def fake_get(url: str, params: object = None, timeout: object = None) -> FakeResponse:
            requested.append(url)
            return FakeResponse(200, {"researchers": []})

        self._patch_session(fake_get)
        with (
            mock.patch("os.access", return_value=False),
            self.assertRaises(CommandError) as raised,
        ):
            self._call()

        self.assertIn("--work-dir", str(raised.exception))
        self.assertEqual(raised.exception.returncode, 1)
        self.assertEqual(requested, [])
