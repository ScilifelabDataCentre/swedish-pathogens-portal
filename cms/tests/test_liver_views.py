"""Tests for liver resource HTMX views."""

import csv
import io
import json
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from cms.services.liver_resource.reference_data import get_data_root
from cms.services.liver_resource.session import SESSION_KEY


class TestLiverViews(TestCase):
    """Verify liver dashboard HTMX endpoints."""

    def setUp(self) -> None:
        """Prepare client and example DE file path."""
        self.client = Client()
        self.upload_url = reverse("cms:liver_upload")
        self.recompute_url = reverse("cms:liver_recompute")
        self.example_path = get_data_root() / "examples" / "HCC-Control.txt"

    def _upload_example_file(self) -> None:
        upload = SimpleUploadedFile(
            name="HCC-Control.txt",
            content=self.example_path.read_bytes(),
            content_type="text/plain",
        )
        response = self.client.post(
            self.upload_url,
            {"de_file": upload, "cutoff": "standard"},
        )
        self.assertEqual(response.status_code, 200)

    def test_upload_valid_file_returns_plot(self) -> None:
        """Test a valid DE file returns the TLN plot partial."""
        self._upload_example_file()
        response = self.client.post(
            self.upload_url,
            {
                "de_file": SimpleUploadedFile(
                    name="HCC-Control.txt",
                    content=self.example_path.read_bytes(),
                    content_type="text/plain",
                ),
                "cutoff": "standard",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "liver-tln-result")
        self.assertContains(response, "plotly-graph-div")
        self.assertContains(response, "HCC-Control.txt")

        session = self.client.session.get(SESSION_KEY)
        self.assertIsNotNone(session)
        self.assertEqual(session["filename"], "HCC-Control.txt")
        self.assertEqual(session["cutoff"], "standard")
        self.assertGreater(len(session["genes"]), 10_000)

    def test_upload_missing_file_returns_error(self) -> None:
        """Test missing file field returns validation errors."""
        response = self.client.post(self.upload_url, {})
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Choose a DE file to upload.", status_code=400)
        self.assertIsNone(self.client.session.get(SESSION_KEY))

    def test_upload_invalid_file_returns_error(self) -> None:
        """Test invalid DE content returns field-level errors."""
        upload = SimpleUploadedFile(
            name="bad.txt",
            content=b"not\ta\tvalid\tfile\n",
            content_type="text/plain",
        )
        response = self.client.post(self.upload_url, {"de_file": upload})

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Could not use this DE file", status_code=400)
        self.assertIsNone(self.client.session.get(SESSION_KEY))

    def test_upload_rejects_get(self) -> None:
        """Test upload endpoint rejects GET requests."""
        response = self.client.get(self.upload_url)
        self.assertEqual(response.status_code, 405)

    def test_load_example_returns_plot(self) -> None:
        """Test bundled example endpoint stores session and returns plot."""
        url = reverse("cms:liver_load_example", kwargs={"example_slug": "hcc-control"})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "liver-tln-result")
        self.assertContains(response, "HCC-Control.txt")
        self.assertEqual(self.client.session[SESSION_KEY]["filename"], "HCC-Control.txt")

    def test_load_unknown_example_returns_error(self) -> None:
        """Test unknown example slug returns validation error."""
        url = reverse("cms:liver_load_example", kwargs={"example_slug": "missing-example"})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Unknown example dataset", status_code=400)

    def test_recompute_requires_session(self) -> None:
        """Test recompute without upload returns JSON error."""
        response = self.client.get(self.recompute_url, {"cutoff": "top500"})
        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.content)
        self.assertIn("error", payload)

    def test_recompute_returns_colours_array(self) -> None:
        """Test recompute returns updated colours for all modules."""
        self._upload_example_file()
        response = self.client.get(self.recompute_url, {"cutoff": "top500"})
        self.assertEqual(response.status_code, 200)

        payload = json.loads(response.content)
        self.assertEqual(len(payload["colours_array"]), 105)
        self.assertEqual(payload["stats"]["cutoff"], "top500")
        self.assertEqual(self.client.session[SESSION_KEY]["cutoff"], "top500")

    def test_module_detail_requires_session(self) -> None:
        """Test module detail without upload returns helpful message."""
        url = reverse("cms:liver_module_detail", kwargs={"module_id": 1})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Upload a DE file", status_code=400)

    def test_module_detail_returns_gene_table(self) -> None:
        """Test module detail returns summary and gene rows after upload."""
        self._upload_example_file()
        url = reverse("cms:liver_module_detail", kwargs={"module_id": 1})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Module 1")
        self.assertContains(response, "ENSG")

    def test_download_template_returns_file(self) -> None:
        """Test template download returns the bundled DE template."""
        url = reverse("cms:liver_download_template")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertIn("DE_upload_template.txt", response["Content-Disposition"])
        self.assertIn(b"logFC", response.content)
        self.assertIn(b"adj.P.Val", response.content)

    def test_export_module_scores_requires_session(self) -> None:
        """Test module scores export without session returns 400."""
        url = reverse("cms:liver_export_modules")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 400)

    def test_export_module_scores_matches_reference(self) -> None:
        """Test module scores download matches R fixture after upload."""
        self._upload_example_file()
        url = reverse("cms:liver_export_modules")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("HCC-Control_module_scores.csv", response["Content-Disposition"])

        rows = list(csv.DictReader(io.StringIO(response.content.decode())))
        fixture_path = (
            Path(__file__).resolve().parent
            / "fixtures"
            / "liver"
            / "expected"
            / "HCC-Control_module_scores.csv"
        )
        reference_rows = list(csv.DictReader(fixture_path.open(encoding="utf-8", newline="")))
        self.assertEqual(len(rows), 105)
        self.assertAlmostEqual(
            float(rows[0]["DERatio"]),
            float(reference_rows[0]["DERatio"]),
            places=6,
        )

    def test_export_genes_returns_csv(self) -> None:
        """Test gene classification export returns a CSV attachment."""
        self._upload_example_file()
        url = reverse("cms:liver_export_genes")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertIn("HCC-Control_genes.csv", response["Content-Disposition"])
        rows = list(csv.DictReader(io.StringIO(response.content.decode())))
        self.assertGreater(len(rows), 10_000)


