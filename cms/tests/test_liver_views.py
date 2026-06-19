"""Tests for liver resource upload view."""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from cms.services.liver_resource.reference_data import get_data_root
from cms.services.liver_resource.session import SESSION_KEY


class TestLiverUploadView(TestCase):
    """Verify POST /cms/liver/upload/ behaviour."""

    def setUp(self) -> None:
        """Prepare client and example DE file path."""
        self.client = Client()
        self.url = reverse("cms:liver_upload")
        self.example_path = get_data_root() / "examples" / "HCC-Control.txt"

    def test_upload_valid_file_returns_plot(self) -> None:
        """Test a valid DE file returns the TLN plot partial."""
        upload = SimpleUploadedFile(
            name="HCC-Control.txt",
            content=self.example_path.read_bytes(),
            content_type="text/plain",
        )
        response = self.client.post(self.url, {"de_file": upload, "cutoff": "standard"})

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
        response = self.client.post(self.url, {})
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
        response = self.client.post(self.url, {"de_file": upload})

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Could not use this DE file", status_code=400)
        self.assertIsNone(self.client.session.get(SESSION_KEY))

    def test_get_method_not_allowed(self) -> None:
        """Test upload endpoint rejects GET requests."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)
