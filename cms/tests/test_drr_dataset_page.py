"""Tests for DrrDatasetPage and the DrrDatasetData snippet (FREYA-2555, FREYA-2559)."""

import tempfile
from datetime import date
from pathlib import Path

from django.core.cache import cache
from django.core.management import call_command
from django.test import RequestFactory, override_settings
from wagtail.models import Page, Site
from wagtail.test.utils import WagtailPageTestCase

from cms.pages.dashboard_index import DashboardIndexPage
from cms.pages.drr_dataset import DrrDatasetPage
from cms.pages.home import HomePage
from cms.snippets.drr_dataset_data import DrrDatasetData
from cms.tests.test_drr_precompute import FEATURE_CSV, METADATA_TSV
from cms.tests.utils import create_test_image

# A representative, fully-populated summary payload mirroring spec section 7 plus
# the FREYA-2557 reconciliation block. Counts use comma-grouped values so the
# ``intcomma`` render path is asserted unambiguously (Plotly div ids never carry
# commas), and the reconciliation ids are distinctive tokens.
FULL_SUMMARY = {
    "n_compounds": 821,
    "n_plates": 22,
    "n_wells": 7500,
    "n_profiles": 8298,
    "n_features": 1468,
    "pert_type_counts": {"trt": 6800, "negcon": 900, "poscon": 598},
    "compartments": ["nuclei", "cells", "cytoplasm"],
    "channels": ["CONC", "HOECHST", "MITO", "PHAandWGA", "SYTO"],
    "compound_reconciliation": {
        "n_compound_ids": 816,
        "n_control_ids": 5,
        "n_annotated": 651,
        "n_recovered": 34,
        "n_unannotated": 165,
        "unmatched_cbkids": ["CBK000900", "CBK000901"],
    },
    "source": {
        "filename": "datasetForPLS-DA.csv",
        "sha256": "0f1e2d3c4b5a6978",
        "generated_at": "2026-07-11T10:00:00+00:00",
    },
}


class DrrDatasetPageTestCase(WagtailPageTestCase):
    """Base test case that builds the page tree for DRR dataset tests."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Create a site with a home page and the Dashboards index page."""
        root = Page.get_first_root_node()
        for child in root.get_children():
            child.delete()
        root = Page.get_first_root_node()

        cls.home = HomePage(title="Home", slug="home")
        root.add_child(instance=cls.home)
        Site.objects.update_or_create(
            is_default_site=True,
            defaults={"hostname": "testserver", "root_page": cls.home},
        )

        cls.index = DashboardIndexPage(title="Dashboards", slug="dashboards")
        cls.home.add_child(instance=cls.index)
        cls.index.save_revision().publish()


class TestDrrDatasetPageModel(DrrDatasetPageTestCase):
    """Tests for the DrrDatasetPage model fields and placement rules."""

    def test_only_creatable_under_dashboard_index(self) -> None:
        """DrrDatasetPage is allowed under the Dashboards index, not the home page."""
        self.assertCanCreateAt(DashboardIndexPage, DrrDatasetPage)
        self.assertCanNotCreateAt(HomePage, DrrDatasetPage)

    def test_dashboard_index_allows_drr_dataset_page(self) -> None:
        """The Dashboards index registers DrrDatasetPage as an allowed child."""
        self.assertIn("cms.DrrDatasetPage", DashboardIndexPage.subpage_types)

    def test_subpage_types_empty(self) -> None:
        """DrrDatasetPage is a leaf page and cannot have children."""
        self.assertEqual(DrrDatasetPage.subpage_types, [])

    def test_organism_defaults_to_sars_cov_2(self) -> None:
        """The organism field defaults to SARS-CoV-2 for the first dataset."""
        field = DrrDatasetPage._meta.get_field("organism")
        self.assertEqual(field.default, "SARS-CoV-2")


class TestDrrDatasetData(DrrDatasetPageTestCase):
    """Tests for the DrrDatasetData snippet lookup contract."""

    def test_get_data_returns_none_when_absent(self) -> None:
        """get_data returns None when no row matches the slug."""
        self.assertIsNone(DrrDatasetData.get_data("missing-slug"))

    def test_get_data_round_trip(self) -> None:
        """get_data returns the row whose dataset_slug matches."""
        row = DrrDatasetData.objects.create(dataset_slug="sars-cov2-vero-e6")
        self.assertEqual(DrrDatasetData.get_data("sars-cov2-vero-e6").pk, row.pk)


class TestDrrDatasetPageContext(DrrDatasetPageTestCase):
    """Tests that DrrDatasetPage sources figures and summary from DrrDatasetData."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Add a DRR dataset page under the Dashboards index."""
        super().setUpTestData()
        cls.image = create_test_image(title="DRR Image", file_name="drr.jpg")
        cls.page = DrrDatasetPage(
            title="SARS-CoV-2 Vero E6 Cell Painting",
            slug="sars-cov2-vero-e6",
            description="Primary Cell Painting antiviral screen.",
            image=cls.image,
            data_status="active",
            cell_line="Vero E6",
        )
        cls.index.add_child(instance=cls.page)
        cls.page.save_revision().publish()

    def test_context_pulls_figures_and_summary_from_drr_dataset_data(self) -> None:
        """get_context exposes DrrDatasetData figures and the summary payload."""
        DrrDatasetData.objects.create(
            dataset_slug="sars-cov2-vero-e6",
            data={"pca": {"data": [], "layout": {}}},
            summary={"n_compounds": 42},
        )

        request = RequestFactory().get(self.page.url)
        context = self.page.get_context(request)

        self.assertIn("pca", context["figures"])
        self.assertEqual(context["summary"], {"n_compounds": 42})

    def test_context_handles_missing_drr_dataset_data(self) -> None:
        """get_context degrades gracefully when no DrrDatasetData row exists."""
        request = RequestFactory().get(self.page.url)
        context = self.page.get_context(request)

        self.assertEqual(context["figures"], {})
        self.assertEqual(context["summary"], {})

    def test_page_serves_via_template(self) -> None:
        """A published DrrDatasetPage renders (HTTP 200) via the inherited dashboard template."""
        response = self.client.get(self.page.url)
        self.assertEqual(response.status_code, 200)


class TestDrrDatasetPageRender(DrrDatasetPageTestCase):
    """Rendered-HTML tests for the DRR dataset template (spec section 9 / 10)."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Add a published DRR dataset page carrying a single PCA figure block."""
        super().setUpTestData()
        cls.image = create_test_image(title="DRR Render", file_name="drr-render.jpg")
        cls.page = DrrDatasetPage(
            title="SARS-CoV-2 Vero E6 Cell Painting",
            slug="sars-cov2-vero-e6",
            description="Primary Cell Painting antiviral screen.",
            image=cls.image,
            data_status="active",
            cell_line="Vero E6",
            screen_type="Primary Cell Painting",
            upstream_accession="S-BIAD2580",
            content=[
                ("plotly_figure", {"figure_id": "pca", "alt_text": "PCA plot", "height": 500}),
            ],
        )
        cls.index.add_child(instance=cls.page)
        cls.page.save_revision().publish()

    def setUp(self) -> None:
        """Clear the per-figure HTML cache so figure assertions are hermetic."""
        super().setUp()
        cache.clear()

    def test_populated_page_renders_metadata_summary_and_figure(self) -> None:
        """A populated DrrDatasetData renders metadata, the summary panel, and the figure."""
        DrrDatasetData.objects.create(
            dataset_slug="sars-cov2-vero-e6",
            data={"pca": {"data": [], "layout": {}}},
            summary=FULL_SUMMARY,
            source_file_hash="deadbeefcafe0000",
            data_updated_at=date(2026, 7, 10),
        )

        response = self.client.get(self.page.url)
        self.assertEqual(response.status_code, 200)

        # Header and dataset metadata.
        self.assertContains(response, "SARS-CoV-2")
        self.assertContains(response, "Vero E6")
        self.assertContains(response, "Primary Cell Painting")
        self.assertContains(response, "S-BIAD2580")
        self.assertContains(response, "Data last updated")
        self.assertContains(response, "July 10, 2026")

        # Summary counts (intcomma-formatted; commas never appear in Plotly div ids).
        self.assertContains(response, "Summary statistics")
        self.assertContains(response, "8,298")  # n_profiles
        self.assertContains(response, "1,468")  # n_features
        self.assertContains(response, "7,500")  # n_wells

        # Perturbation types plus compartments / channels.
        self.assertContains(response, "Perturbation types")
        self.assertContains(response, "6,800")  # trt count
        self.assertContains(response, "nuclei, cells, cytoplasm")
        self.assertContains(response, "CONC, HOECHST, MITO, PHAandWGA, SYTO")

        # Compound-metadata reconciliation block (FREYA-2557).
        self.assertContains(response, "Compound metadata reconciliation")
        self.assertContains(response, "651")  # n_annotated
        self.assertContains(response, "165")  # n_unannotated
        self.assertContains(response, "Unannotated compound IDs (2)")
        self.assertContains(response, "CBK000900, CBK000901")

        # Source provenance.
        self.assertContains(response, "datasetForPLS-DA.csv")
        self.assertContains(response, "0f1e2d3c4b5a6978")

        # Figure rendered server-side through the inherited PlotlyFigureBlock path.
        self.assertContains(response, 'class="plotly-figure"')
        self.assertContains(response, 'aria-label="PCA plot"')

    def test_figure_falls_back_when_figure_json_missing(self) -> None:
        """With no precomputed figure JSON the block shows its unavailable-data fallback."""
        response = self.client.get(self.page.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Chart data is not available for this figure.")
        self.assertNotContains(response, 'class="plotly-figure"')

    def test_summary_panel_hidden_without_data(self) -> None:
        """The summary panel is omitted entirely when no DrrDatasetData exists."""
        response = self.client.get(self.page.url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Summary statistics")


class TestDrrDatasetDownloadsInert(DrrDatasetPageTestCase):
    """Option A contract: the downloads section stays inert until FREYA-2537 / 2539."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Add a published DRR dataset page for the downloads-inert checks."""
        super().setUpTestData()
        cls.image = create_test_image(title="DRR Inert", file_name="drr-inert.jpg")
        cls.page = DrrDatasetPage(
            title="DRR Downloads Inert",
            slug="drr-downloads-inert",
            description="Downloads stay hidden until the routes land.",
            image=cls.image,
            data_status="active",
        )
        cls.index.add_child(instance=cls.page)
        cls.page.save_revision().publish()

    def test_download_urls_absent_from_context(self) -> None:
        """get_context does not expose download_urls until the routes are wired."""
        request = RequestFactory().get(self.page.url)
        context = self.page.get_context(request)
        self.assertNotIn("download_urls", context)

    def test_downloads_section_not_rendered_even_with_data(self) -> None:
        """The downloads markup stays hidden even when a data row is present."""
        DrrDatasetData.objects.create(
            dataset_slug="drr-downloads-inert",
            summary={"n_compounds": 1},
            data={},
        )
        response = self.client.get(self.page.url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="drr-downloads-heading"')
        self.assertNotContains(response, "Download features (CSV)")
        self.assertNotContains(response, "Download raw images")


class TestDrrDatasetSliceAcceptance(DrrDatasetPageTestCase):
    """End-to-end: precompute artefacts drive a live DRR page render (spec section 10)."""

    def setUp(self) -> None:
        """Clear the per-figure HTML cache before the end-to-end render."""
        super().setUp()
        cache.clear()

    def test_precompute_output_renders_on_the_page(self) -> None:
        """drr_precompute output reaches the page: summary, reconciliation, and figure."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        input_path = base / "features.csv"
        input_path.write_text(FEATURE_CSV, encoding="utf-8")
        metadata_path = base / "metadata.tsv"
        metadata_path.write_text(METADATA_TSV, encoding="utf-8")
        media = base / "media"

        slug = "drr-acceptance-slice"
        with override_settings(MEDIA_ROOT=str(media)):
            call_command(
                "drr_precompute",
                slug=slug,
                input=str(input_path),
                metadata=str(metadata_path),
                title="Acceptance DRR",
            )

            image = create_test_image(title="DRR Acceptance", file_name="drr-acc.jpg")
            page = DrrDatasetPage(
                title="Acceptance DRR",
                slug=slug,
                description="End-to-end acceptance slice.",
                image=image,
                data_status="active",
                cell_line="Vero E6",
                content=[
                    ("plotly_figure", {"figure_id": "pca", "alt_text": "PCA plot", "height": 500}),
                ],
            )
            self.index.add_child(instance=page)
            page.save_revision().publish()

            response = self.client.get(page.url)

        self.assertEqual(response.status_code, 200)

        # The precompute upserted a data row the page reads by slug.
        row = DrrDatasetData.get_data(slug)
        self.assertIsNotNone(row)
        self.assertEqual(row.summary["n_compounds"], 3)
        self.assertEqual(row.summary["n_plates"], 2)
        self.assertIn("pca", row.data)

        # The precomputed summary, reconciliation, and figure all reach the page.
        self.assertContains(response, "Summary statistics")
        self.assertContains(response, "Compound metadata reconciliation")
        self.assertContains(response, "CBK3")  # the fixture's unmatched compound id
        self.assertContains(response, "Unannotated compound IDs (1)")
        self.assertContains(response, 'class="plotly-figure"')
