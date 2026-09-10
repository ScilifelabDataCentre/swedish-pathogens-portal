"""Tests for portal_data shared context builders."""

from __future__ import annotations

import tempfile
from pathlib import Path

from django.test import RequestFactory, TestCase, override_settings

from portal_data.context import build_portal_data_context


def write_investigation_file(
    study_dir: Path,
    *,
    title: str,
    release_date: str = "2024-01-01",
    platform: str = "LC-MS",
) -> None:
    """Write a minimal MetaboLights investigation file for tests."""
    study_dir.mkdir(parents=True, exist_ok=True)
    (study_dir / "i_Investigation.txt").write_text(
        "\n".join(
            [
                f"Study Title\t{title}",
                f"Study Description\tDescription for {title}",
                f"Study Public Release Date\t{release_date}",
                "Study Factor Name\tTreatment",
                "Study Design Type\tcase control design",
                f"Study Assay Technology Platform\t{platform}",
                "Study Assay Technology Type\tmass spectrometry",
            ]
        ),
        encoding="utf-8",
    )


class PortalDataContextTests(TestCase):
    """Tests for the portal data listing context."""

    def setUp(self) -> None:
        """Create a temporary dataset root for each test."""
        self.factory = RequestFactory()
        self.tmpdir_context = tempfile.TemporaryDirectory()
        self.datasets_root = Path(self.tmpdir_context.name)

    def tearDown(self) -> None:
        """Remove the temporary dataset root."""
        self.tmpdir_context.cleanup()

    def test_build_portal_data_context_uses_default_facets(self) -> None:
        """Build context with default facets when no facet query params exist."""
        write_investigation_file(
            self.datasets_root / "MTBLS1001",
            title="Example plasma study",
        )

        with override_settings(DATASETS_ROOT=self.datasets_root):
            request = self.factory.get("/data/")
            context = build_portal_data_context(
                request,
                datatype="metabolomics",
            )

        self.assertEqual(context["datatype"], "metabolomics")
        self.assertEqual(context["datatype_label"], "Metabolomics")
        self.assertEqual(context["query"], "")
        self.assertEqual(context["filters"], {})
        self.assertEqual(context["total"], 1)
        self.assertEqual(context["items"][0]["accession"], "MTBLS1001")
        facet_fields = [facet["field"] for facet in context["facets"]]
        self.assertIn("year", facet_fields)
        self.assertIn("platforms", facet_fields)

    def test_build_portal_data_context_applies_search(self) -> None:
        """Filter listing context by a free-text search query."""
        write_investigation_file(
            self.datasets_root / "MTBLS1001",
            title="Plasma metabolomics",
        )
        write_investigation_file(
            self.datasets_root / "MTBLS1002",
            title="Urine metabolomics",
        )

        with override_settings(DATASETS_ROOT=self.datasets_root):
            request = self.factory.get("/data/", {"q": "plasma"})
            context = build_portal_data_context(
                request,
                datatype="metabolomics",
            )

        self.assertEqual(context["total"], 1)
        self.assertEqual(context["items"][0]["accession"], "MTBLS1001")

    def test_build_portal_data_context_applies_facet_filter(self) -> None:
        """Filter listing context by a selected facet value."""
        write_investigation_file(
            self.datasets_root / "MTBLS1001",
            title="LCMS study",
            platform="LC-MS",
        )
        write_investigation_file(
            self.datasets_root / "MTBLS1002",
            title="NMR study",
            platform="NMR spectroscopy",
        )

        with override_settings(DATASETS_ROOT=self.datasets_root):
            request = self.factory.get(
                "/data/",
                {
                    "facet": ["platforms"],
                    "platforms": ["LC-MS"],
                },
            )
            context = build_portal_data_context(
                request,
                datatype="metabolomics",
            )

        self.assertEqual(context["filters"], {"platforms": ["LC-MS"]})
        self.assertEqual(context["total"], 1)
        self.assertEqual(context["items"][0]["accession"], "MTBLS1001")
