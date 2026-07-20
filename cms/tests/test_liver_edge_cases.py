"""Edge-case and integration tests for the liver resource dashboard."""

from __future__ import annotations

import json
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponse
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse

from dashboard_visualisation.liver_resource.analysis import analyse_de_data
from dashboard_visualisation.liver_resource.computation import parse_de_file
from dashboard_visualisation.liver_resource.session import SESSION_KEY
from dashboard_visualisation.liver_resource.validators import validate_de_upload


def build_de_file_bytes(
    *,
    gene_count: int = 150,
    log_fc: float = 0.0,
    adj_pval: float = 1.0,
    t_stat: float = 0.0,
    header: str = "logFC\tadj.P.Val\tt\tP.Value",
) -> bytes:
    """Build a minimal valid tab-separated DE file for tests."""
    rows = [header]
    for index in range(gene_count):
        gene_id = f"ENSG{900_000_000_000 + index:011d}"
        rows.append(f"{gene_id}\t{log_fc}\t{adj_pval}\t{t_stat}\t{adj_pval}")
    return "\n".join(rows).encode()


class TestLiverValidationEdgeCases(SimpleTestCase):
    """Validator edge cases not covered elsewhere."""

    def test_empty_file_is_rejected(self) -> None:
        """Test completely empty uploads are rejected."""
        result = validate_de_upload(BytesIO(b""))
        self.assertFalse(result.is_valid)
        self.assertTrue(any("empty" in error.lower() for error in result.errors))

    def test_header_only_file_is_rejected(self) -> None:
        """Test a header row without gene data is rejected."""
        content = b"logFC\tadj.P.Val\n"
        result = validate_de_upload(BytesIO(content))
        self.assertFalse(result.is_valid)
        self.assertTrue(any("100" in error for error in result.errors))

    def test_non_numeric_logfc_is_rejected(self) -> None:
        """Test non-numeric logFC values are rejected."""
        header = "logFC\tadj.P.Val\n"
        rows = "\n".join(
            f"ENSG{900_000_000_000 + index:011d}\tnot_a_number\t0.05" for index in range(150)
        )
        result = validate_de_upload(BytesIO((header + rows).encode()))
        self.assertFalse(result.is_valid)
        self.assertTrue(any("logFC" in error for error in result.errors))

    def test_non_utf8_file_is_rejected(self) -> None:
        """Test non-UTF-8 encoded uploads are rejected."""
        result = validate_de_upload(BytesIO(b"\xff\xfe"))
        self.assertFalse(result.is_valid)
        self.assertTrue(any("UTF-8" in error for error in result.errors))


class TestLiverComputationEdgeCases(SimpleTestCase):
    """Computation behaviour for unusual but valid DE inputs."""

    def test_no_significant_genes_returns_neutral_colours(self) -> None:
        """Test a valid file with no DE signal still produces a coloured figure."""
        de_data = parse_de_file(BytesIO(build_de_file_bytes(log_fc=0.0, adj_pval=1.0)))
        analysis = analyse_de_data(de_data, filename="neutral.txt", cutoff="standard")

        self.assertEqual(analysis.up_count, 0)
        self.assertEqual(analysis.down_count, 0)
        self.assertIn("data", analysis.figure_json)
        self.assertEqual(len(analysis.ratios), 105)
        self.assertTrue(all(colour == "#ffffff" for colour in analysis.colours.values()))


class TestLiverViewEdgeCases(TestCase):
    """HTTP edge cases for liver dashboard endpoints."""

    def setUp(self) -> None:
        """Prepare client and endpoint URLs for edge-case requests."""
        self.client = Client()
        self.upload_url = reverse("cms:liver_upload")
        self.recompute_url = reverse("cms:liver_recompute")
        self.htmx_headers = {"HTTP_HX_REQUEST": "true"}

    def _post_de_file(
        self,
        content: bytes,
        *,
        filename: str = "test.txt",
        cutoff: str = "standard",
    ) -> HttpResponse:
        """POST a DE upload and return the response."""
        upload = SimpleUploadedFile(
            name=filename,
            content=content,
            content_type="text/plain",
        )
        return self.client.post(
            self.upload_url,
            {"de_files": upload, "cutoff": cutoff},
            **self.htmx_headers,
        )

    def test_upload_empty_file_returns_validation_error(self) -> None:
        """Test empty upload returns a validation fragment and no session."""
        response = self._post_de_file(b"")
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Could not use this DE file", status_code=400)
        self.assertIsNone(self.client.session.get(SESSION_KEY))

    def test_upload_too_few_genes_returns_validation_error(self) -> None:
        """Test uploads below the minimum gene count are rejected."""
        content = build_de_file_bytes(gene_count=50)
        response = self._post_de_file(content, filename="short.txt")
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "100", status_code=400)
        self.assertIsNone(self.client.session.get(SESSION_KEY))

    def test_upload_no_significant_genes_still_returns_plot(self) -> None:
        """Test a valid neutral DE file still renders a TLN plot."""
        response = self._post_de_file(build_de_file_bytes(log_fc=0.0, adj_pval=1.0))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "liver-tln-result")
        self.assertContains(response, "0 up / 0 down")
        self.assertIsNotNone(self.client.session.get(SESSION_KEY))

    def test_upload_malformed_tab_content_returns_validation_error(self) -> None:
        """Test comma-separated content without required columns is rejected."""
        rows = ["gene,logFC,padj"] + [f"GENE{i},1.0,0.01" for i in range(150)]
        response = self._post_de_file("\n".join(rows).encode(), filename="csv-style.txt")
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Could not use this DE file", status_code=400)

    def test_export_genes_without_session_returns_400(self) -> None:
        """Test gene export without upload returns plain-text error."""
        url = reverse("cms:liver_export_genes")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Upload DE file(s)", response.content)

    def test_recompute_invalid_cutoff_falls_back_to_standard(self) -> None:
        """Test invalid cutoff query values fall back to the default cutoff."""
        self._post_de_file(build_de_file_bytes())
        response = self.client.get(self.recompute_url, {"cutoff": "not-a-real-cutoff"})
        self.assertEqual(response.status_code, 200)

        payload = json.loads(response.content)
        self.assertEqual(payload["stats"]["cutoff"], "standard")
        self.assertEqual(self.client.session[SESSION_KEY]["cutoff"], "standard")

    def test_recompute_after_session_cleared_returns_error(self) -> None:
        """Test recompute without session returns JSON error."""
        self._post_de_file(build_de_file_bytes())
        session = self.client.session
        del session[SESSION_KEY]
        session.save()

        response = self.client.get(self.recompute_url, {"cutoff": "top500"})
        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.content)
        self.assertIn("error", payload)
