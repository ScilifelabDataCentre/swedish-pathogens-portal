"""Go-live regression coverage for HepaGeNIE Dash1 (Commit 9).

Consolidates Option B thresholds, Plot Difference/Total, hover titles,
and DashboardData example load into one regression suite.
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
    """End-to-end regression for Dash1 go-live behaviours."""

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
        """Rename: CMS model label is HepaGeNIE, not DINA/ITA."""
        self.assertEqual(
            LiverResourceDashboardPage._meta.verbose_name,
            "HepaGeNIE Dashboard",
        )

    def test_page_chrome_exposes_option_b_plot_and_hepagene_assets(self) -> None:
        """Page shows Option B + Plot controls, HepaGeNIE a11y label, downloads."""
        response = self.client.get(self.page.url)
        self.assertEqual(response.status_code, 200)

        self.assertContains(response, "HepaGeNIE (Gene Network Inference and Exploration)")
        self.assertContains(response, 'aria-label="HepaGeNIE tree-leaf network"')
        self.assertNotContains(response, "DINA")
        self.assertNotContains(response, "DEcutoff")

        self.assertContains(response, "Adj P.val")
        self.assertContains(response, "LogFC fold")
        self.assertContains(response, "Difference DE genes")
        self.assertContains(response, "Total DE genes")
        for value in ADJ_P_CHOICES:
            self.assertContains(response, f'value="{value}"')
        for value in LOGFC_FOLD_CHOICES:
            self.assertContains(response, f'value="{value}"')

        self.assertContains(response, EXAMPLE_LABEL)
        self.assertContains(response, liver_route_url(self.page, "load_example", EXAMPLE_SLUG))
        self.assertNotContains(response, 'id="liver-reference-figure"')
        self.assertNotContains(response, 'id="liver-reference-figure-dialog"')
        self.assertNotContains(response, 'id="liver-reference-figure-open"')
        self.assertNotContains(response, 'id="liver-download-supplementary"')
        self.assertContains(response, "Download DE template")

    def test_hover_titles_present_on_base_tln(self) -> None:
        """Jackie hover titles appear for titled modules; blanks stay number-only."""
        figure_json = build_base_figure_json()
        leaf_trace = next(trace for trace in figure_json["data"] if trace.get("customdata"))
        hover_by_module = dict(
            zip(leaf_trace["customdata"], leaf_trace["hovertext"], strict=True)
        )
        self.assertIn("Myeliod cells", hover_by_module["3"])
        self.assertIn("Amino acid catabolism and urea cycle", hover_by_module["4"])
        self.assertIn("Cell cycle (I) - DNA replication", hover_by_module["12"])
        self.assertTrue(hover_by_module["1"].startswith("<b>Module 1</b><br>Genes:"))

    def test_dashboard_data_example_load_export_and_asset_downloads(self) -> None:
        """Example from DashboardData → session exports (CSV downloads)."""
        example_url = liver_route_url(self.page, "load_example", EXAMPLE_SLUG)
        load = self.client.get(example_url)
        self.assertEqual(load.status_code, 200)
        self.assertContains(load, "liver-tln-result")
        self.assertContains(load, "obese-Control.txt")
        self.assertContains(load, "DE threshold:")
        self.assertIsNotNone(self.client.session.get(SESSION_KEY))

        modules = self.client.get(liver_route_url(self.page, "export_module_scores"))
        self.assertEqual(modules.status_code, 200)
        self.assertIn("text/csv", modules["Content-Type"])
        self.assertIn("Module", modules.content.decode())

        genes = self.client.get(liver_route_url(self.page, "export_genes"))
        self.assertEqual(genes.status_code, 200)
        self.assertIn("text/csv", genes["Content-Type"])

    def test_recompute_option_b_and_total_plot_metric(self) -> None:
        """Recompute honours stricter thresholds and Total plot mode."""
        self.client.get(liver_route_url(self.page, "load_example", EXAMPLE_SLUG))
        recompute_url = liver_route_url(self.page, "recompute")

        response = self.client.get(
            recompute_url,
            {"adj_p": "0.01", "logfc_fold": "2", "plot_metric": "total"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["stats"]["adj_p"], 0.01)
        self.assertEqual(payload["stats"]["logfc_fold"], 2.0)
        self.assertEqual(payload["stats"]["plot_metric"], "total")
        for value in payload["ratios"].values():
            if value is not None:
                self.assertGreaterEqual(value, 0.0)
        session = self.client.session[SESSION_KEY]
        self.assertEqual(session["cutoff"], "0.01_2")
        self.assertEqual(session["plot_metric"], "total")
