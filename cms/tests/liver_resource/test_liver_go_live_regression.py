"""Thin go-live smoke for HepaGeNIE (chrome, hover, example → exports).

Detailed upload/recompute/export behaviour lives in ``test_liver_views`` and
page wiring in ``test_liver_resource_page``.
"""

from __future__ import annotations

from django.test import Client, TestCase

from cms.pages.liver_resource import LiverResourceDashboardPage
from cms.tests.liver_resource.liver_helpers import (
    create_liver_dashboard_data,
    create_published_liver_resource_page,
    liver_route_url,
)
from dashboard_visualisation.liver_resource.examples import EXAMPLE_LABEL, EXAMPLE_SLUG
from dashboard_visualisation.liver_resource.plotly_tln import build_base_figure_json
from dashboard_visualisation.liver_resource.session import SESSION_KEY
from dashboard_visualisation.liver_resource.thresholds import ADJ_P_CHOICES, LOGFC_FOLD_CHOICES


class TestLiverGoLiveRegression(TestCase):
    """End-to-end smoke for HepaGeNIE go-live behaviours."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Publish liver page and obese-named DashboardData example."""
        cls.page = create_published_liver_resource_page(
            title="HepaGeNIE (Gene Network Inference and Exploration)",
            description=(
                "Interactive Tree-and-Leaf Network for mammalian liver gene modules. "
                "Upload differential expression to colour the HepaGeNIE TLN."
            ),
        )
        create_liver_dashboard_data(upload_name="obese-Control.txt")

    def setUp(self) -> None:
        """Fresh client per test."""
        self.client = Client()

    def test_model_verbose_name_is_hepagene(self) -> None:
        """CMS model label is HepaGeNIE Dashboard."""
        self.assertEqual(
            LiverResourceDashboardPage._meta.verbose_name,
            "HepaGeNIE Dashboard",
        )

    def test_page_chrome_exposes_thresholds_plot_and_assets(self) -> None:
        """Page shows DE threshold + Plot controls, a11y label, and downloads."""
        response = self.client.get(self.page.url)
        self.assertEqual(response.status_code, 200)

        self.assertContains(response, "HepaGeNIE (Gene Network Inference and Exploration)")
        self.assertContains(response, 'aria-label="HepaGeNIE tree-leaf network"')
        self.assertContains(response, "Adj P.val")
        self.assertContains(response, "LogFC fold")
        self.assertContains(response, "Difference DE genes")
        self.assertContains(response, "Total DE genes")
        self.assertContains(response, "Up regulated")
        self.assertContains(response, "Down regulated")
        for value in ADJ_P_CHOICES:
            self.assertContains(response, f'value="{value}"')
        for value in LOGFC_FOLD_CHOICES:
            self.assertContains(response, f'value="{value}"')
        self.assertContains(response, EXAMPLE_LABEL)
        self.assertContains(response, liver_route_url(self.page, "load_example", EXAMPLE_SLUG))
        self.assertContains(response, "Download DE template")

    def test_hover_titles_present_on_base_tln(self) -> None:
        """Hover titles appear for titled modules; blanks stay number-only."""
        figure_json = build_base_figure_json()
        leaf_trace = next(trace for trace in figure_json["data"] if trace.get("customdata"))
        hover_by_module = dict(
            zip(leaf_trace["customdata"], leaf_trace["hovertext"], strict=True)
        )
        self.assertIn("Myeliod cells", hover_by_module["3"])
        self.assertTrue(hover_by_module["1"].startswith("<b>Module 1</b><br>Genes:"))

    def test_dashboard_data_example_load_then_exports(self) -> None:
        """Example from DashboardData → session → CSV exports."""
        example_url = liver_route_url(self.page, "load_example", EXAMPLE_SLUG)
        load = self.client.get(example_url)
        self.assertEqual(load.status_code, 200)
        self.assertContains(load, "liver-tln-result")
        self.assertContains(load, "obese-Control.txt")
        self.assertIsNotNone(self.client.session.get(SESSION_KEY))

        modules = self.client.get(liver_route_url(self.page, "export_module_scores"))
        self.assertEqual(modules.status_code, 200)
        self.assertIn("text/csv", modules["Content-Type"])
        self.assertIn("Module", modules.content.decode())

        genes = self.client.get(liver_route_url(self.page, "export_genes"))
        self.assertEqual(genes.status_code, 200)
        self.assertIn("text/csv", genes["Content-Type"])
