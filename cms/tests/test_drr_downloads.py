"""Tests for the DRR bulk feature-download routes (FREYA-2580, spec section 8).

Covers the two bulk artefact routes on ``DrrDatasetPage`` and the traversal
guards in the shared ``serve_file_from_directory`` helper. The per-compound
slice lives in ``test_drr_compound_download.py``.
"""

import tempfile
from pathlib import Path

import polars as pl
from django.http import Http404
from django.test import RequestFactory, SimpleTestCase

from cms.pages.drr_dataset import DrrDatasetPage
from cms.services.file_downloads import serve_file_from_directory
from cms.tests.test_drr_dataset_page import DrrDatasetPageTestCase
from cms.tests.utils import create_test_image, use_temp_media_root

# A deliberately narrow stand-in for the feature table: two compounds and one
# bracketed control placeholder, mirroring the real ``cbkid`` shapes documented
# in ``dashboard_visualisation/drr/compounds.py``. The routes are
# column-agnostic, so pinning the real ~1,468-column set would only make these
# tests brittle when the feather input adds ``pert_iname`` (draft R9).
FEATURE_ROWS = {
    "cbkid": ["CBK1", "CBK1", "CBK2", "[stau]"],
    "Metadata_Barcode": ["P1", "P1", "P2", "P2"],
    "Metadata_Well": ["A01", "A02", "B01", "B02"],
    "AreaShape_Area_nuclei": [1.0, 1.2, 0.9, 1.5],
}


class DrrDownloadRouteTestCase(DrrDatasetPageTestCase):
    """A published DRR dataset page plus an isolated ``MEDIA_ROOT`` per test.

    The fixture slug and title carry no screen identity on purpose, so the
    relabel in FREYA-2587 does not have to touch these tests.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Publish a DRR dataset page to hang the download routes off."""
        super().setUpTestData()
        cls.image = create_test_image(title="DRR Downloads", file_name="drr-downloads.jpg")
        cls.page = DrrDatasetPage(
            title="DRR Downloads",
            slug="drr-downloads",
            description="Feature downloads for the dataset.",
            image=cls.image,
            data_status="active",
        )
        cls.index.add_child(instance=cls.page)
        cls.page.save_revision().publish()

    def setUp(self) -> None:
        """Redirect ``MEDIA_ROOT`` to a temp dir and create the artefact directory."""
        super().setUp()
        self.media_root = use_temp_media_root(self)
        self.artefacts = self.media_root / "drr" / self.page.slug
        self.artefacts.mkdir(parents=True)

    def write_artefacts(self, **extra_columns: list) -> pl.DataFrame:
        """Write the ``features.csv`` / ``features.parquet`` pair the routes serve.

        Args:
            **extra_columns: Additional columns to widen the fixture with.

        Returns:
            pl.DataFrame: The frame that was written.
        """
        frame = pl.DataFrame({**FEATURE_ROWS, **extra_columns})
        frame.write_csv(self.artefacts / "features.csv")
        frame.write_parquet(self.artefacts / "features.parquet")
        return frame

    def download(self, relative_url: str) -> object:
        """GET a sub-path of the DRR page.

        Args:
            relative_url: Path relative to the page URL, e.g. ``download/features.csv``.

        Returns:
            The test client response.
        """
        return self.client.get(self.page.url + relative_url)


class TestDrrBulkDownloads(DrrDownloadRouteTestCase):
    r"""The bulk feature-table routes (spec section 8).

    Wagtail serves page URLs through ``^((?:[\w\-]+/)*)$``, so the format is a
    path segment rather than a file extension. The saved filename still comes
    from Content-Disposition.
    """

    def test_features_csv_served_as_attachment(self) -> None:
        """The CSV route streams the artefact, named features.csv."""
        frame = self.write_artefacts()

        response = self.download("download/features/csv/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="features.csv"')
        body = b"".join(response.streaming_content).decode()
        response.close()
        self.assertEqual(body, frame.write_csv())
        self.assertIn("cbkid", body.splitlines()[0])

    def test_features_parquet_served_as_attachment(self) -> None:
        """The Parquet route streams real Parquet bytes, named features.parquet."""
        self.write_artefacts()

        response = self.download("download/features/parquet/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="features.parquet"')
        self.assertEqual(response["Content-Type"], "application/octet-stream")
        body = b"".join(response.streaming_content)
        response.close()
        self.assertTrue(body.startswith(b"PAR1"))

    def test_missing_csv_artefact_returns_404(self) -> None:
        """A page whose precompute has not run yet 404s rather than erroring."""
        self.assertEqual(self.download("download/features/csv/").status_code, 404)

    def test_missing_parquet_artefact_returns_404(self) -> None:
        """The Parquet route 404s when the artefact is absent."""
        self.assertEqual(self.download("download/features/parquet/").status_code, 404)

    def test_slashless_url_redirects_to_the_route(self) -> None:
        """A request without the trailing slash is redirected, not lost."""
        self.write_artefacts()

        response = self.download("download/features/csv")

        self.assertEqual(response.status_code, 301)
        self.assertTrue(response["Location"].endswith("download/features/csv/"))

    def test_no_arbitrary_artefact_can_be_named(self) -> None:
        """The surface is fixed-format: a stray archive in the directory is unreachable."""
        self.write_artefacts()
        (self.artefacts / "plate.ome.zarr.zip").write_bytes(b"not servable")

        self.assertEqual(self.download("download/features/zip/").status_code, 404)
        self.assertEqual(self.download("download/plate.ome.zarr.zip").status_code, 404)


class TestDrrDownloadUrlsContext(DrrDownloadRouteTestCase):
    """``download_urls`` in ``get_context`` (inverts the transitional contract)."""

    def context(self) -> dict:
        """Return the page context for a plain GET.

        Returns:
            dict: The rendered template context.
        """
        return self.page.get_context(RequestFactory().get(self.page.url))

    def test_download_urls_expose_every_available_download(self) -> None:
        """Both bulk artefacts and the compound base are advertised as absolute URLs."""
        self.write_artefacts()

        download_urls = self.context()["download_urls"]

        self.assertEqual(sorted(download_urls), ["compound_base", "csv", "parquet"])
        self.assertTrue(download_urls["csv"].startswith(self.page.url))
        self.assertIn("download/features/csv/", download_urls["csv"])
        self.assertIn("download/features/parquet/", download_urls["parquet"])
        self.assertIn("download/compound/", download_urls["compound_base"])

    def test_raw_images_is_not_advertised(self) -> None:
        """The 302 link-out belongs to FREYA-2581 and must not appear here."""
        self.write_artefacts()

        self.assertNotIn("raw_images", self.context()["download_urls"])

    def test_download_urls_absent_without_artefacts(self) -> None:
        """With nothing precomputed the section stays hidden instead of dead-linking."""
        self.assertNotIn("download_urls", self.context())

    def test_only_the_present_artefact_is_advertised(self) -> None:
        """A half-precomputed directory advertises only what it can serve.

        With no Parquet table there is nothing for the per-compound slice to
        filter, so the compound base is withheld too.
        """
        (self.artefacts / "features.csv").write_text("cbkid\nCBK1\n", encoding="utf-8")

        self.assertEqual(sorted(self.context()["download_urls"]), ["csv"])

    def test_downloads_section_renders_bulk_links(self) -> None:
        """The template's downloads section goes live, minus the raw-image button."""
        self.write_artefacts()

        response = self.client.get(self.page.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="drr-downloads-heading"')
        self.assertContains(response, "Download features (CSV)")
        self.assertContains(response, "Download features (Parquet)")
        self.assertNotContains(response, "Download raw images")

    def test_downloads_section_hidden_without_artefacts(self) -> None:
        """No artefacts, no downloads section."""
        response = self.client.get(self.page.url)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="drr-downloads-heading"')
        self.assertNotContains(response, "Download features (CSV)")


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
