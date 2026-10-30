# ruff: noqa: S321 -- an in-memory fake FTP server; no connection is made.
"""Tests for portal_data.metabolights.ftp and the metabolights_fetch command.

The FTP server is an in-memory fake (FakeFtp) implementing just the ftplib
calls the module makes, so these run offline and deterministically.
"""

from __future__ import annotations

import ftplib
import io
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from portal_data.metabolights import ftp

STUDY = "/pub/databases/metabolights/studies/public/MTBLS1"
T_OLD = datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC).timestamp()
T_NEW = datetime(2025, 6, 7, 8, 9, 10, tzinfo=UTC).timestamp()


def _stamp(epoch: float) -> str:
    """Format epoch seconds as an FTP MDTM/MLSD timestamp."""
    return datetime.fromtimestamp(epoch, tz=UTC).strftime("%Y%m%d%H%M%S")


class FakeFtp:
    """In-memory stand-in for ftplib.FTP.

    files maps absolute remote paths to (content, mtime); directories are
    implied by the paths. With mlsd_supported=False, MLSD answers 500 so
    the LIST fallback is exercised.
    """

    def __init__(
        self, files: dict[str, tuple[bytes, float]], *, mlsd_supported: bool = True
    ) -> None:
        """Store the fake file tree."""
        self.files = files
        self.mlsd_supported = mlsd_supported
        self.retrieved: list[tuple[str, int | None]] = []
        self.closed = False

    def _children(self, directory: str) -> dict[str, str]:
        """Return {name: "file"|"dir"} for the direct children of directory."""
        prefix = directory.rstrip("/") + "/"
        children: dict[str, str] = {}
        for path in self.files:
            if path.startswith(prefix):
                head, _, rest = path[len(prefix) :].partition("/")
                children[head] = "dir" if rest else "file"
        return children

    def size(self, path: str) -> int:
        """Return a file's size, or raise 550 like a real server."""
        if path not in self.files:
            raise ftplib.error_perm(f"550 {path}: No such file")
        return len(self.files[path][0])

    def sendcmd(self, cmd: str) -> str:
        """Answer MDTM."""
        verb, _, path = cmd.partition(" ")
        if verb != "MDTM" or path not in self.files:
            raise ftplib.error_perm("550 not available")
        return f"213 {_stamp(self.files[path][1])}"

    def mlsd(self, path: str, facts: list[str] | None = None) -> list[tuple[str, dict[str, str]]]:
        """Answer MLSD from the fake tree."""
        if not self.mlsd_supported:
            raise ftplib.error_perm("500 Unknown command")
        children = self._children(path)
        if not children:
            raise ftplib.error_perm(f"550 {path}: No such directory")
        entries: list[tuple[str, dict[str, str]]] = [(".", {"type": "cdir"})]
        for name, kind in children.items():
            full = f"{path.rstrip('/')}/{name}"
            if kind == "dir":
                entries.append((name, {"type": "dir"}))
            else:
                content, mtime = self.files[full]
                entries.append(
                    (name, {"type": "file", "size": str(len(content)), "modify": _stamp(mtime)})
                )
        return entries

    def retrlines(self, cmd: str, callback: Callable[[str], None]) -> None:
        """Answer LIST with Unix-style lines."""
        path = cmd.partition(" ")[2]
        for name, kind in self._children(path).items():
            if kind == "dir":
                callback(f"drwxr-xr-x    2 ftp      ftp          4096 Jan 01  2024 {name}")
            else:
                size = len(self.files[f"{path.rstrip('/')}/{name}"][0])
                callback(f"-rw-r--r--    1 ftp      ftp      {size:>8} Jan 01  2024 {name}")

    def retrbinary(
        self, cmd: str, callback: Callable[[bytes], None], rest: int | None = None
    ) -> None:
        """Answer RETR, honouring a REST offset."""
        path = cmd.partition(" ")[2]
        self.retrieved.append((path, rest))
        callback(self.files[path][0][rest or 0 :])

    def quit(self) -> None:
        """Close the fake connection."""
        self.closed = True


class FtpTestCase(SimpleTestCase):
    """Shared helpers: a temp destination directory."""

    def setUp(self) -> None:
        """Create a temporary destination root."""
        self.dest = Path(self.enterContext(tempfile.TemporaryDirectory()))


class ReadTargetsTests(FtpTestCase):
    """targets.txt parsing."""

    def test_skips_blank_comment_and_duplicate_lines(self) -> None:
        """Only real, first-seen study paths are returned."""
        path = self.dest / "targets.txt"
        path.write_text(f"# header\n\n{STUDY}/\n  \n{STUDY}/\n/other/MTBLS2/\n")
        self.assertEqual(ftp.read_targets(path), [f"{STUDY}/", "/other/MTBLS2/"])

    def test_study_dir_name_rejects_path_escape(self) -> None:
        """A target that resolves to '..' is refused rather than written outside dest."""
        self.assertEqual(ftp.study_dir_name(f"{STUDY}/"), "MTBLS1")
        with self.assertRaises(ValueError):
            ftp.study_dir_name("/pub/..")


class FetchStudiesTests(FtpTestCase):
    """End-to-end fetch behaviour against the fake server."""

    def _fetch(self, server: FakeFtp, **kwargs: object) -> ftp.FetchSummary:
        """Fetch the single test study from server into self.dest."""
        return ftp.fetch_studies([f"{STUDY}/"], self.dest, ftp_factory=lambda: server, **kwargs)

    def test_default_mode_fetches_only_the_investigation_file(self) -> None:
        """Subdirectories and other files are left on the server by default."""
        server = FakeFtp(
            {
                f"{STUDY}/i_Investigation.txt": (b"investigation", T_OLD),
                f"{STUDY}/s_study.txt": (b"sample", T_OLD),
                f"{STUDY}/METADATA_REVISIONS/i_Investigation.txt": (b"old", T_OLD),
            }
        )

        summary = self._fetch(server)

        local = self.dest / "MTBLS1" / "i_Investigation.txt"
        self.assertEqual(summary.downloaded, [local])
        self.assertEqual(local.read_bytes(), b"investigation")
        self.assertEqual(int(local.stat().st_mtime), int(T_OLD))
        self.assertEqual(sorted(p.name for p in (self.dest / "MTBLS1").iterdir()), [local.name])
        self.assertTrue(server.closed)

    def test_rerun_skips_unchanged_and_refetches_updated_file(self) -> None:
        """Same size+mtime is skipped; a changed remote file is downloaded again."""
        files = {f"{STUDY}/i_Investigation.txt": (b"v1", T_OLD)}
        self._fetch(FakeFtp(files))

        unchanged = self._fetch(FakeFtp(files))
        self.assertEqual(unchanged.downloaded, [])
        self.assertEqual(len(unchanged.unchanged), 1)

        # Same size, newer timestamp: the case a plain `get` used to miss.
        files[f"{STUDY}/i_Investigation.txt"] = (b"v2", T_NEW)
        updated = self._fetch(FakeFtp(files))
        self.assertEqual(len(updated.downloaded), 1)
        self.assertEqual((self.dest / "MTBLS1" / "i_Investigation.txt").read_bytes(), b"v2")

    def test_all_mode_mirrors_recursively(self) -> None:
        """--all fetches every file, keeping the directory structure."""
        server = FakeFtp(
            {
                f"{STUDY}/i_Investigation.txt": (b"i", T_OLD),
                f"{STUDY}/s_study.txt": (b"s", T_OLD),
                f"{STUDY}/FILES/raw/data.mzML": (b"raw", T_NEW),
            }
        )

        summary = self._fetch(server, all_files=True)

        self.assertEqual(len(summary.downloaded), 3)
        raw = self.dest / "MTBLS1" / "FILES" / "raw" / "data.mzML"
        self.assertEqual(raw.read_bytes(), b"raw")
        self.assertEqual(int(raw.stat().st_mtime), int(T_NEW))

    def test_all_mode_falls_back_to_list_without_mlsd(self) -> None:
        """Servers without MLSD are walked via LIST, with mtimes from MDTM."""
        server = FakeFtp(
            {
                f"{STUDY}/i_Investigation.txt": (b"i", T_OLD),
                f"{STUDY}/FILES/data.mzML": (b"raw", T_NEW),
            },
            mlsd_supported=False,
        )

        summary = self._fetch(server, all_files=True)

        self.assertEqual(len(summary.downloaded), 2)
        raw = self.dest / "MTBLS1" / "FILES" / "data.mzML"
        self.assertEqual(int(raw.stat().st_mtime), int(T_NEW))

    def test_resumes_from_partial_file(self) -> None:
        """An interrupted download continues from the .part file's length."""
        server = FakeFtp({f"{STUDY}/i_Investigation.txt": (b"0123456789", T_OLD)})
        partial = self.dest / "MTBLS1" / "i_Investigation.txt.part"
        partial.parent.mkdir(parents=True)
        partial.write_bytes(b"0123")

        self._fetch(server)

        self.assertEqual(server.retrieved, [(f"{STUDY}/i_Investigation.txt", 4)])
        self.assertEqual((self.dest / "MTBLS1" / "i_Investigation.txt").read_bytes(), b"0123456789")
        self.assertFalse(partial.exists())

    def test_failed_study_is_recorded_and_others_continue(self) -> None:
        """A study missing on the server doesn't stop the next one."""
        server = FakeFtp({f"{STUDY}/i_Investigation.txt": (b"i", T_OLD)})

        summary = ftp.fetch_studies(
            ["/pub/databases/metabolights/studies/public/MTBLS404/", f"{STUDY}/"],
            self.dest,
            ftp_factory=lambda: server,
        )

        self.assertEqual(
            list(summary.failed), ["/pub/databases/metabolights/studies/public/MTBLS404/"]
        )
        self.assertEqual(len(summary.downloaded), 1)

    def test_unsafe_remote_name_is_refused(self) -> None:
        """A listing entry that would escape the study folder fails that study."""
        server = FakeFtp({f"{STUDY}/i_Investigation.txt": (b"i", T_OLD)})
        server.mlsd = lambda path, facts=None: [("../evil", {"type": "file", "size": "1"})]

        summary = self._fetch(server, all_files=True)

        self.assertIn(f"{STUDY}/", summary.failed)
        self.assertFalse((self.dest / "evil").exists())

    def test_size_mismatch_keeps_partial_and_fails(self) -> None:
        """A short transfer is not promoted to the final file name."""
        server = FakeFtp({f"{STUDY}/i_Investigation.txt": (b"full", T_OLD)})
        server.retrbinary = lambda cmd, callback, rest=None: callback(b"fu")

        summary = self._fetch(server)

        self.assertIn(f"{STUDY}/", summary.failed)
        self.assertFalse((self.dest / "MTBLS1" / "i_Investigation.txt").exists())
        self.assertTrue((self.dest / "MTBLS1" / "i_Investigation.txt.part").exists())


class MetabolightsFetchCommandTests(FtpTestCase):
    """manage.py metabolights_fetch argument handling and exit status."""

    def setUp(self) -> None:
        """Point the command at a fake server."""
        super().setUp()
        self.server = FakeFtp(
            {
                f"{STUDY}/i_Investigation.txt": (b"one", T_OLD),
                "/pub/databases/metabolights/studies/public/MTBLS2/i_Investigation.txt": (
                    b"two",
                    T_OLD,
                ),
            }
        )
        self.enterContext(mock.patch.object(ftp, "connect", lambda: self.server))

    def _call(self, *args: str) -> str:
        """Run the command into self.dest and return stdout."""
        stdout = io.StringIO()
        call_command("metabolights_fetch", "--dest", str(self.dest), *args, stdout=stdout)
        return stdout.getvalue()

    def test_fetches_accessions_given_on_the_command_line(self) -> None:
        """Positional accessions are normalised and fetched."""
        self._call("mtbls1", "MTBLS2")
        self.assertEqual((self.dest / "MTBLS1" / "i_Investigation.txt").read_bytes(), b"one")
        self.assertEqual((self.dest / "MTBLS2" / "i_Investigation.txt").read_bytes(), b"two")

    def test_rejects_non_accessions(self) -> None:
        """Anything that isn't MTBLS<digits> is refused before connecting."""
        with self.assertRaises(CommandError):
            self._call("../etc")

    def test_reads_targets_from_work_dir_by_default(self) -> None:
        """Without accessions, <METABOLIGHTS_WORK_DIR>/targets.txt is used."""
        work_dir = self.dest / "work"
        work_dir.mkdir()
        (work_dir / "targets.txt").write_text(f"{STUDY}/\n")

        with override_settings(METABOLIGHTS_WORK_DIR=work_dir):
            self._call()

        self.assertTrue((self.dest / "MTBLS1" / "i_Investigation.txt").exists())

    def test_missing_targets_file_is_a_command_error(self) -> None:
        """A missing targets file points the user at metabolights_search."""
        with self.assertRaises(CommandError) as raised:
            self._call("--targets", str(self.dest / "nope.txt"))
        self.assertIn("metabolights_search", str(raised.exception))

    def test_failed_study_makes_the_command_fail(self) -> None:
        """Any failed study gives a non-zero exit after trying the rest."""
        with self.assertRaises(CommandError) as raised:
            self._call("MTBLS1", "MTBLS404")
        self.assertIn("MTBLS404", str(raised.exception))
        self.assertTrue((self.dest / "MTBLS1" / "i_Investigation.txt").exists())

    def test_read_only_dest_fails_once_before_connecting(self) -> None:
        """An unwritable destination is one clear error, not one per study."""
        connect = mock.Mock(side_effect=AssertionError("should not connect"))
        with (
            mock.patch.object(ftp, "connect", connect),
            mock.patch("os.access", return_value=False),
            self.assertRaises(CommandError) as raised,
        ):
            self._call("MTBLS1", "MTBLS2")
        self.assertIn("not writable", str(raised.exception))
        connect.assert_not_called()

    def test_summary_pluralises(self) -> None:
        """The closing summary reads naturally for one study and one file."""
        output = self._call("MTBLS1")
        self.assertIn("1 study: 1 file downloaded, 0 unchanged, 0 failed.", output)

    def test_dest_defaults_to_datasets_root(self) -> None:
        """Without --dest, studies land in settings.DATASETS_ROOT."""
        with override_settings(DATASETS_ROOT=str(self.dest)):
            call_command("metabolights_fetch", "MTBLS1", stdout=io.StringIO())
        self.assertTrue((self.dest / "MTBLS1" / "i_Investigation.txt").exists())
