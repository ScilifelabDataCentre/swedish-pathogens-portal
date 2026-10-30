"""Download MetaboLights studies from the EBI FTP server.

Library behind ``manage.py metabolights_fetch`` (formerly the standalone
``portal_data/scripts/fetch_metabolights.sh``). The shell script drove
``lftp mirror``; this uses the standard library's ftplib instead, so the
command runs anywhere the app does (the production image has no lftp) and
can be unit-tested with a fake server.

It keeps the semantics the script relied on:

* By default only each study's investigation file (i_Investigation.txt) is
  fetched -- not its subdirectories, such as METADATA_REVISIONS, which can
  hold older copies of the file. ``all_files=True`` mirrors the whole study
  directory recursively instead.
* Like ``lftp mirror`` (and unlike a plain ``get``), a local file is
  re-downloaded whenever its size or modification time differs from the
  remote one, so an updated investigation file is actually caught, and an
  unchanged one is skipped. Downloaded files get the remote modification
  time so the next run can compare.
* Like ``mirror -c``, an interrupted transfer resumes from the partial file
  (kept as ``<name>.part`` until complete, so a half-written file is never
  mistaken for a finished one).
* Local files with no remote counterpart are left alone (no ``--delete``).

Each study gets its own FTP connection, and a failure is recorded and the
run moves on to the next study, so one missing or flaky study cannot sink
the rest; the caller decides what a non-empty ``failed`` means.
"""

from __future__ import annotations

import ftplib
import os
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

FTP_HOST = "ftp.ebi.ac.uk"
FTP_TIMEOUT_SECONDS = 60
INVESTIGATION_FILE = "i_Investigation.txt"
PARTIAL_SUFFIX = ".part"

Progress = Callable[[str], None]
FtpFactory = Callable[[], ftplib.FTP]


def _no_progress(_message: str) -> None:
    """Discard progress messages (the default when no reporter is given)."""


def connect(host: str = FTP_HOST, timeout: float = FTP_TIMEOUT_SECONDS) -> ftplib.FTP:
    """Open an anonymous, passive-mode, binary FTP connection to the EBI server."""
    # Plain FTP is what EBI offers for this public, anonymous, read-only data
    # (the shell script used it too); nothing secret crosses the connection.
    ftp = ftplib.FTP(host, timeout=timeout)  # noqa: S321
    ftp.login()
    ftp.set_pasv(True)
    ftp.voidcmd("TYPE I")  # SIZE is only reliable in binary mode
    return ftp


@dataclass(frozen=True)
class RemoteFile:
    """A file on the FTP server, relative to the study directory being fetched."""

    relative_path: PurePosixPath
    size: int | None = None
    mtime: float | None = None


@dataclass
class FetchSummary:
    """What a fetch run did, for the caller to report on."""

    studies: int = 0
    downloaded: list[Path] = field(default_factory=list)
    unchanged: list[Path] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)


def read_targets(path: Path) -> list[str]:
    """Read study remote paths from a targets file, one per line.

    Blank lines and lines starting with "#" are skipped, as the shell script
    did. Duplicates are dropped, keeping the first occurrence.
    """
    targets: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and line not in targets:
            targets.append(line)
    return targets


def study_dir_name(remote_path: str) -> str:
    """Return the local folder name for a study's remote path (its last segment)."""
    name = PurePosixPath(remote_path.rstrip("/")).name
    _check_safe_name(name, remote_path)
    return name


def _check_safe_name(name: str, context: str) -> None:
    """Reject a remote name that could escape the local destination directory."""
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        msg = f"Refusing unsafe remote name {name!r} (from {context!r})"
        raise ValueError(msg)


def _parse_ftp_timestamp(value: str) -> float:
    """Parse an FTP MDTM/MLSD timestamp (YYYYMMDDHHMMSS[.sss], UTC) to epoch seconds."""
    parsed = datetime.strptime(value.strip()[:14], "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    return parsed.timestamp()


def stat_remote_file(ftp: ftplib.FTP, remote_path: str) -> tuple[int | None, float | None]:
    """Return (size, mtime) for a single remote file.

    Raises ftplib.error_perm if the file does not exist. Either value is
    None if the server does not support the command that reports it, in
    which case the up-to-date check falls back to whatever is known.
    """
    size = ftp.size(remote_path)  # also the existence check: 550 if missing
    try:
        mtime = _parse_ftp_timestamp(ftp.sendcmd(f"MDTM {remote_path}").split()[-1])
    except ftplib.error_perm, ValueError:
        mtime = None
    return size, mtime


def _list_directory(
    ftp: ftplib.FTP, remote_dir: str
) -> Iterator[tuple[str, str, int | None, float | None]]:
    """Yield (name, kind, size, mtime) for each entry in a remote directory.

    kind is "dir" or "file". Uses MLSD, which gives machine-readable facts;
    falls back to parsing a Unix-style LIST for servers without it (sizes
    only -- the modification time is then fetched per file with MDTM).
    """
    try:
        entries = list(ftp.mlsd(remote_dir, facts=["type", "size", "modify"]))
    except ftplib.error_perm:
        yield from _list_directory_fallback(ftp, remote_dir)
        return

    for name, facts in entries:
        kind = facts.get("type", "").lower()
        if kind in {"cdir", "pdir"} or name in {".", ".."}:
            continue
        size = int(facts["size"]) if facts.get("size", "").isdigit() else None
        mtime = _parse_ftp_timestamp(facts["modify"]) if facts.get("modify") else None
        yield name, ("dir" if kind == "dir" else "file"), size, mtime


def _list_directory_fallback(
    ftp: ftplib.FTP, remote_dir: str
) -> Iterator[tuple[str, str, int | None, float | None]]:
    """Parse a Unix-style LIST listing (``drwxr-xr-x 2 ftp ftp 4096 Jan 01 2020 name``)."""
    lines: list[str] = []
    ftp.retrlines(f"LIST {remote_dir}", lines.append)
    for line in lines:
        parts = line.split(maxsplit=8)
        if len(parts) < 9 or parts[8] in {".", ".."}:
            continue
        mode, size, name = parts[0], parts[4], parts[8]
        if mode.startswith("l"):  # symlink: not followed, as lftp mirror's default
            continue
        kind = "dir" if mode.startswith("d") else "file"
        yield name, kind, (int(size) if size.isdigit() else None), None


def walk_remote(ftp: ftplib.FTP, remote_dir: str) -> Iterator[RemoteFile]:
    """Yield every file under remote_dir, recursively, relative to remote_dir."""

    def _walk(relative: PurePosixPath) -> Iterator[RemoteFile]:
        current = f"{remote_dir.rstrip('/')}/{relative}" if relative.parts else remote_dir
        for name, kind, size, mtime in _list_directory(ftp, current):
            _check_safe_name(name, current)
            if kind == "dir":
                yield from _walk(relative / name)
            else:
                yield RemoteFile(relative / name, size, mtime)

    yield from _walk(PurePosixPath())


def _is_up_to_date(local: Path, remote: RemoteFile) -> bool:
    """Return True if local already matches the remote file's size and mtime."""
    if not local.is_file():
        return False
    stat = local.stat()
    if remote.size is not None and stat.st_size != remote.size:
        return False
    if remote.mtime is not None and int(stat.st_mtime) != int(remote.mtime):
        return False
    # Neither attribute known: nothing to compare, so fetch it again to be safe.
    return remote.size is not None or remote.mtime is not None


def download_file(ftp: ftplib.FTP, remote_path: str, remote: RemoteFile, local: Path) -> bool:
    """Download remote_path to local unless it is already up to date.

    Returns True if the file was downloaded, False if it was unchanged.
    Resumes from an existing ``<name>.part`` file when it is shorter than
    the remote file; otherwise starts over.
    """
    if _is_up_to_date(local, remote):
        return False

    local.parent.mkdir(parents=True, exist_ok=True)
    partial = local.with_name(local.name + PARTIAL_SUFFIX)
    offset = partial.stat().st_size if partial.is_file() else 0
    if remote.size is None or offset >= remote.size:
        offset = 0

    with partial.open("ab" if offset else "wb") as handle:
        ftp.retrbinary(f"RETR {remote_path}", handle.write, rest=offset or None)

    received = partial.stat().st_size
    if remote.size is not None and received != remote.size:
        msg = f"{remote_path}: expected {remote.size} bytes, got {received}"
        raise OSError(msg)

    partial.replace(local)
    if remote.mtime is not None:
        os.utime(local, (remote.mtime, remote.mtime))
    return True


def fetch_study(
    ftp: ftplib.FTP,
    remote_dir: str,
    local_dir: Path,
    *,
    all_files: bool = False,
) -> tuple[list[Path], list[Path]]:
    """Fetch one study into local_dir; return (downloaded, unchanged) local paths."""
    remote_dir = remote_dir.rstrip("/")
    if all_files:
        remote_files: Iterable[RemoteFile] = walk_remote(ftp, remote_dir)
    else:
        size, mtime = stat_remote_file(ftp, f"{remote_dir}/{INVESTIGATION_FILE}")
        remote_files = [RemoteFile(PurePosixPath(INVESTIGATION_FILE), size, mtime)]

    downloaded: list[Path] = []
    unchanged: list[Path] = []
    for remote in remote_files:
        remote_path = f"{remote_dir}/{remote.relative_path}"
        if remote.mtime is None and all_files:
            _, mtime = stat_remote_file(ftp, remote_path)
            remote = RemoteFile(remote.relative_path, remote.size, mtime)
        local = local_dir.joinpath(*remote.relative_path.parts)
        if download_file(ftp, remote_path, remote, local):
            downloaded.append(local)
        else:
            unchanged.append(local)
    return downloaded, unchanged


def fetch_studies(
    remote_dirs: Iterable[str],
    dest_root: Path,
    *,
    all_files: bool = False,
    ftp_factory: FtpFactory | None = None,
    progress: Progress = _no_progress,
) -> FetchSummary:
    """Fetch each study into ``dest_root/<study folder>/``.

    A study that fails (missing on the server, connection dropped, ...) is
    recorded in the summary's ``failed`` and the run carries on. ftp_factory
    opens one connection per study (default: connect to the EBI server).
    """
    ftp_factory = ftp_factory or connect
    summary = FetchSummary()
    for remote_dir in remote_dirs:
        summary.studies += 1
        try:
            local_dir = dest_root / study_dir_name(remote_dir)
            progress(f"=== {local_dir.name} ===")
            progress(f"  Remote: ftp://{FTP_HOST}{remote_dir}")
            progress(f"  Local:  {local_dir}/")
            ftp = ftp_factory()
            try:
                downloaded, unchanged = fetch_study(ftp, remote_dir, local_dir, all_files=all_files)
            finally:
                _close_quietly(ftp)
        except (*ftplib.all_errors, ValueError) as error:  # all_errors includes OSError
            summary.failed[remote_dir] = str(error) or type(error).__name__
            progress(f"  FAILED: {summary.failed[remote_dir]}")
            continue

        summary.downloaded.extend(downloaded)
        summary.unchanged.extend(unchanged)
        progress(f"  {len(downloaded)} downloaded, {len(unchanged)} unchanged")
    return summary


def _close_quietly(ftp: ftplib.FTP) -> None:
    """Say goodbye to the server, dropping the socket if it has already gone away."""
    try:
        ftp.quit()
    except ftplib.all_errors:
        ftp.close()
