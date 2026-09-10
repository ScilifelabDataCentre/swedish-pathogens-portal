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

    def test_unknown_datatype_returns_an_error_context(self) -> None:
        """Return an empty, error-flagged context for an unsupported datatype."""
        request = self.factory.get("/data/")

        context = build_portal_data_context(request, datatype="not-a-real-type")

        self.assertEqual(context["error"], "Unknown data type: not-a-real-type")
        self.assertEqual(context["datatype_label"], "not-a-real-type")
        self.assertEqual(context["items"], [])
        self.assertEqual(context["total"], 0)
        self.assertEqual(context["facets"], [])
        self.assertFalse(context["has_facets"])
        self.assertIsNone(context["page_obj"])

    def test_missing_datatype_falls_back_to_raw_value_in_error(self) -> None:
        """Report the original datatype value in the error when it's empty/None."""
        request = self.factory.get("/data/")

        context = build_portal_data_context(request, datatype=None)

        self.assertEqual(context["datatype_label"], "Unknown")
        self.assertEqual(context["error"], "Unknown data type: None")

    def test_invalid_size_falls_back_to_default(self) -> None:
        """Fall back to the default page size when size isn't a supported option."""
        write_investigation_file(self.datasets_root / "MTBLS1001", title="Example study")

        with override_settings(DATASETS_ROOT=self.datasets_root):
            request = self.factory.get("/data/", {"size": "999"})
            context = build_portal_data_context(request, datatype="metabolomics")

        self.assertEqual(context["size"], 25)

    def test_size_query_param_can_select_a_supported_option(self) -> None:
        """Honor a size query param when it's one of the supported options."""
        write_investigation_file(self.datasets_root / "MTBLS1001", title="Example study")

        with override_settings(DATASETS_ROOT=self.datasets_root):
            request = self.factory.get("/data/", {"size": "50"})
            context = build_portal_data_context(request, datatype="metabolomics")

        self.assertEqual(context["size"], 50)

    def test_pagination_query_excludes_page_but_keeps_other_params(self) -> None:
        """Pagination links keep search/filter params but drop the page number."""
        for i in range(30):
            write_investigation_file(
                self.datasets_root / f"MTBLS{2000 + i}",
                title=f"Plasma study {i}",
            )

        with override_settings(DATASETS_ROOT=self.datasets_root):
            request = self.factory.get("/data/", {"q": "plasma", "page": "2"})
            context = build_portal_data_context(request, datatype="metabolomics")

        self.assertEqual(context["total"], 30)
        self.assertEqual(context["page_obj"].number, 2)
        self.assertEqual(len(context["page_obj"].object_list), 5)
        self.assertEqual(context["pagination_query"], "q=plasma")
