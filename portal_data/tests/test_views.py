"""Tests for portal_data view functions."""

from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.http import Http404, HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from portal_data.views import serve_download_file, serve_study_files

TEMPLATE = "cms/pages/portal_data/study_files.html"


class ServeStudyFilesTests(SimpleTestCase):
    """Tests for listing files available for a study accession."""

    def setUp(self) -> None:
        """Create a temporary dataset root and a stand-in Wagtail page."""
        self.factory = RequestFactory()
        self.tmpdir_context = tempfile.TemporaryDirectory()
        self.datasets_root = Path(self.tmpdir_context.name)
        self.page = SimpleNamespace(datatype="metabolomics", url="/data/metabolomics/")

    def tearDown(self) -> None:
        """Remove the temporary dataset root."""
        self.tmpdir_context.cleanup()

    @patch("portal_data.views.render")
    def test_renders_the_file_listing_for_a_valid_study(self, mock_render: MagicMock) -> None:
        """Build the file-listing context and render it for a valid accession."""
        study_dir = self.datasets_root / "MTBLS1001"
        study_dir.mkdir()
        (study_dir / "results.csv").write_text("a,b\n1,2\n", encoding="utf-8")

        request = self.factory.get("/data/metabolomics/MTBLS1001/files/")
        mock_render.return_value = "rendered response"

        with override_settings(DATASETS_ROOT=self.datasets_root):
            response = serve_study_files(request, self.page, "MTBLS1001", TEMPLATE)

        self.assertEqual(response, "rendered response")
        mock_render.assert_called_once()
        rendered_request, rendered_template, context = mock_render.call_args[0]
        self.assertIs(rendered_request, request)
        self.assertEqual(rendered_template, TEMPLATE)
        self.assertEqual(context["accession"], "MTBLS1001")
        self.assertEqual(context["page"], self.page)
        self.assertEqual(context["portal_data_index_url"], self.page.url)
        self.assertEqual([f["relpath"] for f in context["files"]], ["results.csv"])

    def test_unknown_datatype_raises_404(self) -> None:
        """Reject a page whose datatype isn't a supported config."""
        unknown_page = SimpleNamespace(datatype="not-a-real-type", url="/data/")
        request = self.factory.get("/data/not-a-real-type/MTBLS1001/files/")

        with (
            override_settings(DATASETS_ROOT=self.datasets_root),
            self.assertRaises(Http404),
        ):
            serve_study_files(request, unknown_page, "MTBLS1001", TEMPLATE)

    def test_invalid_accession_raises_404(self) -> None:
        """Reject an accession that doesn't match the MTBLS pattern."""
        request = self.factory.get("/data/metabolomics/not-valid/files/")

        with (
            override_settings(DATASETS_ROOT=self.datasets_root),
            self.assertRaises(Http404),
        ):
            serve_study_files(request, self.page, "not-valid", TEMPLATE)

    def test_missing_datasets_root_raises_404(self) -> None:
        """Raise 404 when DATASETS_ROOT itself doesn't exist."""
        request = self.factory.get("/data/metabolomics/MTBLS1001/files/")
        missing_root = self.datasets_root / "does-not-exist"

        with override_settings(DATASETS_ROOT=missing_root), self.assertRaises(Http404):
            serve_study_files(request, self.page, "MTBLS1001", TEMPLATE)

    def test_missing_study_directory_raises_404(self) -> None:
        """Raise 404 when the accession has no matching directory on disk."""
        request = self.factory.get("/data/metabolomics/MTBLS1001/files/")

        with (
            override_settings(DATASETS_ROOT=self.datasets_root),
            self.assertRaises(Http404),
        ):
            serve_study_files(request, self.page, "MTBLS1001", TEMPLATE)

    @patch("portal_data.views.list_study_files")
    def test_unexpected_listing_error_raises_404(self, mock_list_study_files: MagicMock) -> None:
        """Convert an unexpected error while listing files into a 404."""
        study_dir = self.datasets_root / "MTBLS1001"
        study_dir.mkdir()
        mock_list_study_files.side_effect = OSError("boom")
        request = self.factory.get("/data/metabolomics/MTBLS1001/files/")

        with (
            override_settings(DATASETS_ROOT=self.datasets_root),
            self.assertRaises(Http404),
        ):
            serve_study_files(request, self.page, "MTBLS1001", TEMPLATE)


class ServeDownloadFileTests(SimpleTestCase):
    """Traversal and error guards in ``serve_download_file``."""

    def setUp(self) -> None:
        """Build a study directory with a sibling file that must stay unreachable."""
        self.factory = RequestFactory()
        self.tmpdir_context = tempfile.TemporaryDirectory()
        self.datasets_root = Path(self.tmpdir_context.name)
        self.study_dir = self.datasets_root / "MTBLS1001"
        self.study_dir.mkdir()
        (self.study_dir / "results.csv").write_text("a,b\n1,2\n", encoding="utf-8")
        self.secret = self.datasets_root / "secret.txt"
        self.secret.write_text("never served", encoding="utf-8")

    def tearDown(self) -> None:
        """Remove the temporary dataset root."""
        self.tmpdir_context.cleanup()

    def _download(self, relpath: str) -> HttpResponse:
        """Call serve_download_file with DATASETS_ROOT overridden to the fixture root."""
        request = self.factory.get(f"/data/metabolomics/MTBLS1001/files/{relpath}/")
        with override_settings(DATASETS_ROOT=self.datasets_root):
            return serve_download_file(request, "metabolomics", "MTBLS1001", relpath)

    def test_streams_a_file_inside_the_study_directory(self) -> None:
        """A plain relative path inside the study directory is served."""
        response = self._download("results.csv")

        body = b"".join(response.streaming_content)
        response.close()
        self.assertEqual(body, b"a,b\n1,2\n")
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="results.csv"')

    def test_unknown_datatype_raises_404(self) -> None:
        """Reject a datatype that isn't a supported config."""
        request = self.factory.get("/data/not-a-real-type/MTBLS1001/files/results.csv/")

        with (
            override_settings(DATASETS_ROOT=self.datasets_root),
            self.assertRaises(Http404),
        ):
            serve_download_file(request, "not-a-real-type", "MTBLS1001", "results.csv")

    def test_invalid_accession_raises_404(self) -> None:
        """Reject an accession that doesn't match the MTBLS pattern."""
        request = self.factory.get("/data/metabolomics/not-valid/files/results.csv/")

        with (
            override_settings(DATASETS_ROOT=self.datasets_root),
            self.assertRaises(Http404),
        ):
            serve_download_file(request, "metabolomics", "not-valid", "results.csv")

    def test_rejects_absolute_relpath(self) -> None:
        """An absolute path is refused outright."""
        with self.assertRaises(Http404):
            self._download(str(self.secret))

    def test_rejects_parent_traversal(self) -> None:
        """``../`` cannot escape the study directory."""
        with self.assertRaises(Http404):
            self._download("../secret.txt")

    def test_rejects_percent_encoded_traversal(self) -> None:
        """An encoded separator is unquoted before the guard runs."""
        with self.assertRaises(Http404):
            self._download("..%2Fsecret.txt")

    def test_rejects_symlink_escaping_the_study_directory(self) -> None:
        """A symlink pointing outside the study directory is not followed."""
        (self.study_dir / "escape.txt").symlink_to(self.secret)

        with self.assertRaises(Http404):
            self._download("escape.txt")

    def test_rejects_a_directory(self) -> None:
        """Directories are not downloadable."""
        (self.study_dir / "subdir").mkdir()

        with self.assertRaises(Http404):
            self._download("subdir")

    def test_missing_file_raises_404(self) -> None:
        """An absent file raises 404 rather than an OSError."""
        with self.assertRaises(Http404):
            self._download("absent.csv")

    def test_missing_datasets_root_raises_404(self) -> None:
        """Raise 404 when DATASETS_ROOT itself doesn't exist."""
        request = self.factory.get("/data/metabolomics/MTBLS1001/files/results.csv/")
        missing_root = self.datasets_root / "does-not-exist"

        with override_settings(DATASETS_ROOT=missing_root), self.assertRaises(Http404):
            serve_download_file(request, "metabolomics", "MTBLS1001", "results.csv")

    def test_missing_study_directory_raises_404(self) -> None:
        """Raise 404 when the accession has no matching directory on disk."""
        request = self.factory.get("/data/metabolomics/MTBLS9999/files/results.csv/")

        with (
            override_settings(DATASETS_ROOT=self.datasets_root),
            self.assertRaises(Http404),
        ):
            serve_download_file(request, "metabolomics", "MTBLS9999", "results.csv")
