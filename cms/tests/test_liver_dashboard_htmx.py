"""Integration tests for liver dashboard htmx interactions."""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from cms.services.liver_resource.reference_data import get_data_root
from cms.services.liver_resource.session import SESSION_KEY


class TestLiverDashboardHtmxFlow(TestCase):
    """Verify end-to-end htmx flows used by the liver dashboard page."""

    def setUp(self) -> None:
        self.client = Client()
        self.upload_url = reverse("cms:liver_upload")
        self.example_path = get_data_root() / "examples" / "HCC-Control.txt"
        self.htmx_headers = {"HTTP_HX_REQUEST": "true"}

    def test_htmx_upload_returns_plot_partial(self) -> None:
        """Test htmx-style upload returns plot markup for #liver-tln-panel."""
        upload = SimpleUploadedFile(
            name="HCC-Control.txt",
            content=self.example_path.read_bytes(),
            content_type="text/plain",
        )
        response = self.client.post(
            self.upload_url,
            {"de_file": upload, "cutoff": "standard"},
            **self.htmx_headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "liver-tln-result")
        self.assertContains(response, "plotly-graph-div")
        self.assertContains(response, "liver-analysis-stats")
        self.assertIsNotNone(self.client.session.get(SESSION_KEY))

    def test_htmx_upload_validation_error_returns_alert(self) -> None:
        """Test invalid htmx upload returns validation markup for the error panel."""
        upload = SimpleUploadedFile(
            name="bad.txt",
            content=b"invalid\tcontent\n",
            content_type="text/plain",
        )
        response = self.client.post(
            self.upload_url,
            {"de_file": upload},
            **self.htmx_headers,
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Could not use this DE file", status_code=400)

    def test_htmx_example_load_returns_plot_partial(self) -> None:
        """Test example load via htmx returns plot markup."""
        url = reverse("cms:liver_load_example", kwargs={"example_slug": "hcc-control"})
        response = self.client.get(f"{url}?cutoff=top500", **self.htmx_headers)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "liver-tln-result")
        self.assertContains(response, "top500")
        self.assertEqual(self.client.session[SESSION_KEY]["cutoff"], "top500")
