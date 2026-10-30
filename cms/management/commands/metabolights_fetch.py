"""Management command: download MetaboLights studies from the EBI FTP server.

Fetches each study listed in targets.txt (as written by
``metabolights_search``), or the accessions given on the command line, into
its own ``<dest>/<accession>/`` folder -- by default under
``settings.DATASETS_ROOT``, which is where the Portal Data page reads studies
from. Only i_Investigation.txt is fetched unless --all is given. Re-running is
cheap: unchanged files are skipped and updated ones re-downloaded. See
``portal_data.metabolights.ftp`` for details.

Exits 1 if any study failed to download (after trying all of them).
"""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from portal_data.metabolights import europepmc, ftp

ACCESSION_PATTERN = re.compile(r"^MTBLS\d+$")


class Command(BaseCommand):
    """Download MetaboLights studies from the EBI FTP server."""

    help = (
        "Download MetaboLights studies (i_Investigation.txt, or everything with --all) "
        "listed in targets.txt or given as accessions."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        """Register command-line arguments."""
        parser.add_argument(
            "accessions",
            nargs="*",
            help="Study accessions to fetch (e.g. MTBLS1234). If omitted, --targets is read.",
        )
        parser.add_argument(
            "--targets",
            type=Path,
            default=None,
            help=(
                "File with one study FTP path per line, as written by metabolights_search "
                f"(default: settings.METABOLIGHTS_WORK_DIR/{europepmc.TARGETS_OUTPUT_TXT})."
            ),
        )
        parser.add_argument(
            "--dest",
            type=Path,
            default=None,
            help="Directory to save studies into (default: settings.DATASETS_ROOT).",
        )
        parser.add_argument(
            "-a",
            "--all",
            dest="all_files",
            action="store_true",
            help="Mirror every file in each study's directory, not just i_Investigation.txt.",
        )

    def handle(self, *args: object, **options: object) -> None:
        """Fetch the requested studies and report what changed."""
        dest: Path = options["dest"] or Path(settings.DATASETS_ROOT)
        remote_dirs = self._remote_dirs(options["accessions"], options["targets"])
        mode = "all files per study" if options["all_files"] else ftp.INVESTIGATION_FILE + " only"

        self.stdout.write(f"Destination: {dest}")
        self.stdout.write(f"Mode:        {mode}")
        self.stdout.write(f"Studies:     {len(remote_dirs)}")
        self.stdout.write("")

        summary = ftp.fetch_studies(
            remote_dirs,
            dest,
            all_files=options["all_files"],
            progress=self.stdout.write,
        )

        self.stdout.write("")
        self.stdout.write(
            f"{summary.studies} studies: {len(summary.downloaded)} file(s) downloaded, "
            f"{len(summary.unchanged)} unchanged, {len(summary.failed)} study(ies) failed."
        )
        if summary.failed:
            failures = "\n".join(f"  {path}: {reason}" for path, reason in summary.failed.items())
            raise CommandError(f"Some studies could not be fetched:\n{failures}")
        self.stdout.write(self.style.SUCCESS("Done."))

    @staticmethod
    def _remote_dirs(accessions: list[str], targets: Path | None) -> list[str]:
        """Resolve the studies to fetch from accessions, or else the targets file."""
        if accessions:
            normalized = [accession.strip().upper() for accession in accessions]
            invalid = [a for a in normalized if not ACCESSION_PATTERN.match(a)]
            if invalid:
                raise CommandError(f"Not MetaboLights accessions: {', '.join(invalid)}")
            return [europepmc.study_ftp_path(a) for a in dict.fromkeys(normalized)]

        targets = targets or Path(settings.METABOLIGHTS_WORK_DIR) / europepmc.TARGETS_OUTPUT_TXT
        try:
            return ftp.read_targets(targets)
        except OSError as error:
            raise CommandError(
                f"Could not read targets file {targets}: {error}. "
                "Run `manage.py metabolights_search` first, or pass accessions."
            ) from error
