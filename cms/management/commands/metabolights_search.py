"""Management command: find MetaboLights studies linked to SciLifeLab authors.

Searches Europe PMC for MetaboLights-linked publications by every researcher
in the SciLifeLab publications database (or, with --publications, every
author in a publications CSV export), and writes the matching papers, a per-author
summary and a targets.txt of study FTP paths for ``metabolights_fetch``. See
``portal_data.metabolights.europepmc`` for the matching rules and output
columns.

Exit codes, for cron-style scheduling:
  0  Completed with no errors.
  3  Completed, but one or more authors' searches errored (see the error
     column in the summary CSV) -- run again with --retry-errors before
     treating the output as complete or running metabolights_fetch.
  1  The run did not complete (e.g. the researcher list could not be
     downloaded, or an input file was missing).
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

import httpx
from django.core.management.base import BaseCommand, CommandError, CommandParser

from portal_data import services
from portal_data.metabolights import europepmc

PARTIAL_RUN_EXIT_CODE = 3


class Command(BaseCommand):
    """Search Europe PMC for MetaboLights-linked publications by SciLifeLab authors."""

    help = (
        "Search Europe PMC for MetaboLights-linked publications by SciLifeLab researchers, "
        "and write the MetaboLights study targets for metabolights_fetch."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        """Register command-line arguments."""
        parser.add_argument(
            "--work-dir",
            type=Path,
            default=None,
            help=(
                "Directory receiving the output CSVs and targets.txt "
                f"(default: <DATASETS_ROOT>/{services.METABOLIGHTS_SEARCH_DIRNAME})."
            ),
        )
        parser.add_argument(
            "--publications",
            type=Path,
            default=None,
            help=(
                "Read authors from this SciLifeLab publications CSV export (with an "
                "'Authors' column) instead of downloading the researcher list from "
                f"{europepmc.RESEARCHERS_JSON_URL}."
            ),
        )
        parser.add_argument(
            "--keywords",
            type=Path,
            default=europepmc.DEFAULT_KEYWORDS_CSV,
            help="One pathogen/infectious-disease keyword per line (default: the bundled list).",
        )
        parser.add_argument(
            "--retry-errors",
            action="store_true",
            help=(
                "Instead of a full run, re-run the search only for authors that errored "
                f"in the previous run (per the error column in {europepmc.SUMMARY_OUTPUT_CSV}) "
                "and merge the results into the existing output files."
            ),
        )

    def handle(self, *args: object, **options: object) -> None:
        """Run a full search or a retry, then report and set the exit code.

        httpx logs every request at INFO, which over a full run (one request
        or more per author) would bury the progress lines, so it is quietened
        to warnings for the run unless --verbosity 3 asks for everything.
        """
        httpx_logger = logging.getLogger("httpx")
        previous_level = httpx_logger.level
        if options["verbosity"] < 3:  # noqa: PLR2004 -- Django's highest verbosity
            httpx_logger.setLevel(logging.WARNING)
        try:
            self._search(options)
        finally:
            httpx_logger.setLevel(previous_level)

    def _search(self, options: dict[str, object]) -> None:
        """Do the run that handle() describes."""
        work_dir: Path = options["work_dir"] or services.get_metabolights_work_dir()
        keywords: Path = options["keywords"]

        # The outputs are only written at the end of a run that can take an hour,
        # so check the work dir is usable before any of the searching.
        try:
            services.ensure_writable_dir(work_dir)
        except OSError as error:
            raise CommandError(
                f"Cannot write search results to {work_dir}: {error}. "
                "Pass a writable --work-dir or set DATASETS_ROOT."
            ) from error

        try:
            if options["retry_errors"]:
                outcome = europepmc.retry_errored_authors(
                    work_dir, keywords_csv=keywords, progress=self.stdout.write
                )
                if outcome.authors_searched == 0:
                    return
            else:
                outcome = europepmc.run_search(
                    work_dir,
                    publications_csv=options["publications"],
                    keywords_csv=keywords,
                    progress=self.stdout.write,
                )
        except (httpx.HTTPError, OSError, ValueError, csv.Error) as error:
            # The researcher list couldn't be downloaded, or an input was
            # missing/malformed: the run never completed. Per-author Europe PMC
            # failures don't land here -- they are recorded and reported
            # through outcome.errored_authors.
            raise CommandError(str(error)) from error

        self.stdout.write("")
        self.stdout.write(
            f"Searched {outcome.authors_searched} author(s): {outcome.unique_papers} unique "
            f"papers ({outcome.author_paper_matches} author-paper matches this run), "
            f"{outcome.targets} MetaboLights study target(s). Output in {work_dir}"
        )

        if outcome.errored_authors:
            raise CommandError(
                f"{outcome.errored_authors} author(s) errored -- run "
                "`manage.py metabolights_search --retry-errors` before relying on this output.",
                returncode=PARTIAL_RUN_EXIT_CODE,
            )
        self.stdout.write(self.style.SUCCESS("Done."))
