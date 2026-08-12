"""Traversal-safe file downloads for page-model routes.

Shared by Wagtail page routes that stream a file out of a directory the
application controls — for example a per-dataset artefact directory under
``MEDIA_ROOT``. It centralises the path-traversal guard, the MIME-type
fallback and the file-handle lifetime so each route stays a one-liner.

The logic follows ``portal_data/views.py::serve_download_file``, which keeps its
own datatype/accession validation and is expected to delegate its file-serving
half here in a later refactor.
"""

from __future__ import annotations

import mimetypes
from contextlib import ExitStack
from pathlib import Path
from urllib.parse import unquote

import structlog
from django.http import FileResponse, Http404

LOGGER = structlog.get_logger(__name__)


def serve_file_from_directory(base_dir: Path, relpath: str) -> FileResponse:
    """Stream a single file from ``base_dir`` as an attachment.

    Resolves ``relpath`` inside ``base_dir`` and refuses anything that leaves
    it, whether through ``..`` segments, an absolute path, or a symlink pointing
    out of the directory.

    Args:
        base_dir: The only directory files may be served from.
        relpath: Path of the requested file relative to ``base_dir``; may be
            percent-encoded.

    Returns:
        FileResponse: An attachment response streaming the file, which releases
            the underlying handle when the response is closed.

    Raises:
        Http404: If the path escapes ``base_dir``, or no readable file is there.
    """
    requested = Path(unquote(relpath))

    if requested.is_absolute():
        LOGGER.warning("downloads.absolute_path_rejected", relpath=relpath)
        raise Http404("Invalid file path")

    try:
        candidate = (base_dir / requested).resolve(strict=False)
        base_resolved = base_dir.resolve(strict=False)
    except OSError as err:
        LOGGER.exception("downloads.path_resolution_failed", base_dir=str(base_dir))
        raise Http404("Invalid file path") from err

    if not candidate.is_relative_to(base_resolved):
        LOGGER.warning(
            "downloads.traversal_rejected",
            base_dir=str(base_resolved),
            candidate=str(candidate),
        )
        raise Http404("Invalid file path")

    if not candidate.is_file():
        LOGGER.warning("downloads.file_not_found", candidate=str(candidate))
        raise Http404("File not found")

    content_type, _ = mimetypes.guess_type(str(candidate))

    stack = ExitStack()
    try:
        handle = stack.enter_context(candidate.open("rb"))
    except OSError as err:
        stack.close()
        LOGGER.exception("downloads.open_failed", candidate=str(candidate))
        raise Http404("File not accessible") from err

    response = FileResponse(
        handle,
        as_attachment=True,
        filename=candidate.name,
        content_type=content_type or "application/octet-stream",
    )

    original_close = response.close

    def cleanup_close(*args: object, **kwargs: object) -> None:
        """Close the response, then release the file handle."""
        try:
            original_close(*args, **kwargs)
        finally:
            stack.close()

    response.close = cleanup_close
    return response
