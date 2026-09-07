"""Test cases for file download services."""

import tempfile
from pathlib import Path

from django.http import Http404
from django.test import SimpleTestCase

from cms.services.file_downloads import serve_file_from_directory


class TestServeFileFromDirectory(SimpleTestCase):
    """Traversal and error guards in ``cms.services.file_downloads``."""

    def setUp(self) -> None:
        """Build a served directory with a sibling file that must stay unreachable."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.base = self.root / "base"
        self.base.mkdir()
        (self.base / "features.csv").write_text("cbkid\nCBK1\n", encoding="utf-8")
        self.secret = self.root / "secret.txt"
        self.secret.write_text("never served", encoding="utf-8")

    def test_serves_a_file_inside_the_directory(self) -> None:
        """A plain relative path inside the base directory is served."""
        response = serve_file_from_directory(self.base, "features.csv")

        body = b"".join(response.streaming_content)
        response.close()
        self.assertEqual(body, b"cbkid\nCBK1\n")
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="features.csv"')

    def test_rejects_parent_traversal(self) -> None:
        """``../`` cannot escape the served directory."""
        with self.assertRaises(Http404):
            serve_file_from_directory(self.base, "../secret.txt")

    def test_rejects_percent_encoded_traversal(self) -> None:
        """An encoded separator is unquoted before the guard runs."""
        with self.assertRaises(Http404):
            serve_file_from_directory(self.base, "..%2Fsecret.txt")

    def test_rejects_absolute_path(self) -> None:
        """An absolute path is refused outright."""
        with self.assertRaises(Http404):
            serve_file_from_directory(self.base, str(self.secret))

    def test_rejects_symlink_escaping_the_directory(self) -> None:
        """A symlink pointing outside the base directory is not followed."""
        (self.base / "escape.txt").symlink_to(self.secret)

        with self.assertRaises(Http404):
            serve_file_from_directory(self.base, "escape.txt")

    def test_rejects_a_directory(self) -> None:
        """Directories are not downloadable."""
        (self.base / "figures").mkdir()

        with self.assertRaises(Http404):
            serve_file_from_directory(self.base, "figures")

    def test_missing_file_raises_404(self) -> None:
        """An absent artefact raises 404 rather than an OSError."""
        with self.assertRaises(Http404):
            serve_file_from_directory(self.base, "absent.csv")

    def test_missing_base_directory_raises_404(self) -> None:
        """A slug directory that was never precomputed raises 404."""
        with self.assertRaises(Http404):
            serve_file_from_directory(self.root / "never-precomputed", "features.csv")
