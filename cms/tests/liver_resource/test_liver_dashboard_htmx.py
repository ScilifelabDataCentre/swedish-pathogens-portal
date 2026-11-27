"""HTMX header deltas for liver dashboard partials.

Plot/validation behaviour without ``HX-Request`` is covered in
``test_liver_views``.
"""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase

from cms.tests.liver_resource.liver_helpers import (
    create_liver_dashboard_data,
    create_published_liver_resource_page,
    liver_route_url,
)
from dashboard_visualisation.liver_resource.examples import EXAMPLE_SLUG
from dashboard_visualisation.liver_resource.reference_data import get_data_root
from dashboard_visualisation.liver_resource.session import SESSION_KEY


class TestLiverDashboardHtmxFlow(TestCase):
    """Verify HX-Request uploads/example loads still return plot partials."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Publish a liver page so RoutablePageMixin sub-routes resolve."""
        cls.page = create_published_liver_resource_page()
        create_liver_dashboard_data(upload_name="obese-Control.txt")

    def setUp(self) -> None:
        """Prepare client and HTMX headers."""
        self.client = Client()
        self.htmx_headers = {"HTTP_HX_REQUEST": "true"}

    def test_htmx_upload_returns_plot_partial(self) -> None:
        """HX upload returns the plot partial for #liver-tln-panel."""
        example_path = get_data_root() / "examples" / "HCC-Control.txt"
        upload = SimpleUploadedFile(
            name="HCC-Control.txt",
            content=example_path.read_bytes(),
            content_type="text/plain",
        )
        response = self.client.post(
            liver_route_url(self.page, "upload_de"),
            {"de_files": upload, "adj_p": "0.05", "logfc_fold": "1.5"},
            **self.htmx_headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "liver-tln-result")
        self.assertContains(response, "plotly-graph-div")
        self.assertIsNotNone(self.client.session.get(SESSION_KEY))

    def test_htmx_example_load_honours_threshold_query(self) -> None:
        """HX example load with threshold query returns plot and updates session."""
        url = liver_route_url(self.page, "load_example", example_slug=EXAMPLE_SLUG)
        response = self.client.get(
            f"{url}?adj_p=0.01&logfc_fold=2",
            **self.htmx_headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "liver-tln-result")
        self.assertContains(response, "adj.P&lt;0.01")
        self.assertEqual(self.client.session[SESSION_KEY]["cutoff"], "0.01_2")
