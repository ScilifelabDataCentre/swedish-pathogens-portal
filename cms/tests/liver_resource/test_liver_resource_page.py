"""Tests for LiverResourceDashboardPage."""

from datetime import date
from unittest.mock import patch

from django.test import RequestFactory
from wagtail.test.utils import WagtailPageTestCase

from cms.pages.dashboard import DashboardPage
from cms.pages.dashboard_index import DashboardIndexPage
from cms.pages.liver_resource import (
    LiverResourceDashboardPage,
    split_liver_content_for_plot,
)
from cms.snippets.dashboard_data import DashboardData
from cms.tests.liver_resource.liver_helpers import (
    create_published_liver_resource_page,
    liver_route_url,
)
from cms.tests.utils import create_test_image
from dashboard_visualisation.liver_resource.thresholds import ADJ_P_CHOICES, LOGFC_FOLD_CHOICES
from dashboard_visualisation.liver_resource.examples import list_example_slugs, list_examples
from dashboard_visualisation.liver_resource.reference_data import (
    clear_reference_data_cache,
    get_data_root,
)


class LiverResourcePageTestCase(WagtailPageTestCase):
    """Base test case with dashboard index for liver page tests."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Create site with home page and dashboard index."""
        cls.page = create_published_liver_resource_page()
        cls.index = cls.page.get_parent().specific
        cls.home = cls.index.get_parent().specific
        cls.image = cls.page.image

    def setUp(self) -> None:
        """Clear cached reference data between tests."""
        clear_reference_data_cache()


class TestLiverResourceDashboardPageModel(LiverResourcePageTestCase):
    """Tests for LiverResourceDashboardPage model constraints."""

    def test_parent_page_type_restriction(self) -> None:
        """Test that only DashboardIndexPage can be a parent."""
        self.assertEqual(
            LiverResourceDashboardPage.parent_page_types,
            ["cms.DashboardIndexPage"],
        )

    def test_subpage_type_restriction(self) -> None:
        """Test that liver dashboard pages cannot have child pages."""
        self.assertEqual(LiverResourceDashboardPage.subpage_types, [])

    def test_max_count_is_one(self) -> None:
        """Test that only one liver dashboard page may exist in the tree."""
        self.assertEqual(LiverResourceDashboardPage.max_count, 1)

    def test_uses_custom_template(self) -> None:
        """Test that the liver page uses its dedicated template."""
        self.assertEqual(
            LiverResourceDashboardPage.template,
            "cms/pages/liver_resource.html",
        )

    def test_dashboard_index_allows_liver_child(self) -> None:
        """Test that DashboardIndexPage accepts liver dashboard children."""
        self.assertIn(
            "cms.LiverResourceDashboardPage",
            DashboardIndexPage.subpage_types,
        )


class TestLiverResourceDashboardPageContext(LiverResourcePageTestCase):
    """Tests for LiverResourceDashboardPage.get_context."""

    def test_get_context_includes_base_tln_figure_json(self) -> None:
        """Test that get_context exposes the neutral base TLN figure."""
        request = self.client.get(self.page.url).wsgi_request
        context = self.page.get_context(request)

        figure = context["base_tln_figure_json"]
        self.assertIn("data", figure)
        self.assertIn("layout", figure)
        self.assertGreater(len(figure["data"]), 0)

    def test_get_context_includes_threshold_choices(self) -> None:
        """Test that get_context exposes Adj P.val and LogFC choices."""
        request = self.client.get(self.page.url).wsgi_request
        context = self.page.get_context(request)

        self.assertEqual(context["adj_p_choices"], ADJ_P_CHOICES)
        self.assertEqual(context["logfc_fold_choices"], LOGFC_FOLD_CHOICES)

    def test_get_context_includes_base_plot_html(self) -> None:
        """Test that get_context exposes server-rendered base Plotly HTML."""
        request = self.client.get(self.page.url).wsgi_request
        context = self.page.get_context(request)

        self.assertIn("plotly-graph-div", context["base_plot_html"])
        self.assertEqual(context["plot_height"], 560)
        self.assertEqual(context["leaf_trace_index"], 2)

    def test_get_context_includes_examples(self) -> None:
        """Test examples come from DashboardData; empty without a source file."""
        request = self.client.get(self.page.url).wsgi_request
        context = self.page.get_context(request)

        self.assertEqual(context["examples"], [])
        self.assertEqual(context["examples"], list_examples(self.page.dashboard_data))
        self.assertEqual(list_example_slugs(), ["obese-control"])

        from cms.tests.liver_resource.liver_helpers import create_liver_dashboard_data

        create_liver_dashboard_data(upload_name="obese-Control.txt")
        self.page.__dict__.pop("dashboard_data", None)
        request = self.client.get(self.page.url).wsgi_request
        context = self.page.get_context(request)
        self.assertEqual(
            [example["slug"] for example in context["examples"]],
            list_example_slugs(),
        )

    def test_get_context_includes_session_flags(self) -> None:
        """Test that get_context exposes session state for export controls."""
        request = self.client.get(self.page.url).wsgi_request
        context = self.page.get_context(request)

        self.assertFalse(context["has_session"])
        self.assertEqual(context["current_adj_p"], 0.05)
        self.assertEqual(context["current_logfc_fold"], 1.5)
        self.assertEqual(context["current_plot_metric"], "difference")
        self.assertEqual(context["default_adj_p"], 0.05)
        self.assertEqual(context["default_logfc_fold"], 1.5)
        self.assertEqual(context["default_plot_metric"], "difference")
        self.assertEqual(
            [choice["value"] for choice in context["plot_metric_choices"]],
            ["difference", "total"],
        )

    def test_get_context_includes_parent_heading(self) -> None:
        """Test that liver pages inherit the dashboard index heading."""
        request = self.client.get(self.page.url).wsgi_request
        context = self.page.get_context(request)

        self.assertEqual(context["page_heading"], "Dashboards")

    def test_get_context_omits_unused_endpoint_url_keys(self) -> None:
        """Test get_context does not inject unused liver_*_url keys."""
        request = self.client.get(self.page.url).wsgi_request
        context = self.page.get_context(request)

        self.assertNotIn("liver_upload_url", context)
        self.assertNotIn("liver_recompute_url", context)
        self.assertNotIn("liver_reference_figure_url", context)
        self.assertNotIn("liver_supplementary_url", context)

    def test_get_context_example_label_uses_dashboard_data_filename(self) -> None:
        """Test example button uses GSE126848 label for an obese-named DashboardData file."""
        from cms.tests.liver_resource.liver_helpers import create_liver_dashboard_data
        from dashboard_visualisation.liver_resource.examples import EXAMPLE_LABEL

        create_liver_dashboard_data(upload_name="obese-Control.txt")
        self.page.__dict__.pop("dashboard_data", None)

        request = self.client.get(self.page.url).wsgi_request
        context = self.page.get_context(request)

        self.assertEqual(context["examples"][0]["label"], EXAMPLE_LABEL)
        self.assertEqual(context["examples"][0]["slug"], "obese-control")
        self.assertEqual(context["examples"][0]["filename"], "obese-Control.txt")

    def test_page_includes_htmx_and_plotly_wiring(self) -> None:
        """Test that the page template includes htmx upload wiring and liver JS."""
        response = self.client.get(self.page.url)
        upload_url = liver_route_url(self.page, "upload_de")
        recompute_url = liver_route_url(self.page, "recompute")
        self.assertContains(response, f'hx-post="{upload_url}"')
        self.assertContains(response, f'data-recompute-url="{recompute_url}"')
        self.assertContains(response, 'hx-target="#liver-tln-panel"')
        self.assertContains(response, 'hx-target-error="#liver-validation-errors"')
        self.assertContains(response, 'id="liver-dashboard"')
        self.assertContains(response, "liver_resource.js")
        self.assertNotIn("/cms/liver/", upload_url)
        self.assertNotIn("/cms/liver/", recompute_url)

    def test_page_colour_legend_uses_up_down_regulated_labels(self) -> None:
        """Test colour legend spells out up/down regulated (not bare Up/Down)."""
        response = self.client.get(self.page.url)
        self.assertContains(response, 'id="liver-colour-legend"')
        self.assertContains(response, "Up regulated")
        self.assertContains(response, "Down regulated")
        self.assertContains(response, "Neutral / no data")
        self.assertNotContains(response, "> Up</span>")
        self.assertNotContains(response, "> Down</span>")

    def test_split_liver_content_moves_footer_text_below_plot(self) -> None:
        """Test reference TLN + workbook + citation text blocks render below the plot."""
        self.page.content = [
            ("text", "<p>Intro copy for HepaGeNIE.</p>"),
            ("alert", {"alert_type": "info", "message": "<p>Upload help.</p>"}),
            (
                "text",
                "<p>Download the <a href=\"/documents/1/tln.jpg\">HepaGeNIE reference TLN map</a>.</p>",
            ),
            (
                "text",
                "<p>Download the <a href=\"/documents/2/supp.xlsx\">supplementary workbook</a>.</p>",
            ),
            (
                "text",
                "<h3>How to cite the example dataset</h3><p>Suppli et al. (2019).</p>",
            ),
        ]
        self.page.save_revision().publish()
        self.page.refresh_from_db()

        above, below = split_liver_content_for_plot(self.page.content)
        self.assertEqual([block.block_type for block in above], ["text", "alert"])
        self.assertEqual(len(below), 3)
        self.assertIn("reference tln map", str(below[0].value).casefold())
        self.assertIn("supplementary workbook", str(below[1].value).casefold())
        self.assertIn("How to cite the example dataset", str(below[2].value))

        response = self.client.get(self.page.url)
        html = response.content.decode()
        plot_pos = html.index('id="tln-container"')
        ref_pos = html.index("reference TLN map")
        supp_pos = html.index("supplementary workbook")
        cite_pos = html.index("How to cite the example dataset")
        self.assertGreater(ref_pos, plot_pos)
        self.assertGreater(supp_pos, ref_pos)
        self.assertGreater(cite_pos, supp_pos)

    def test_page_renders_successfully(self) -> None:
        """Test that the liver dashboard page returns HTTP 200."""
        example_path = get_data_root() / "examples" / "HCC-Control.txt"
        from django.core.files.uploadedfile import SimpleUploadedFile

        upload = SimpleUploadedFile(
            name="HCC-Control.txt",
            content=example_path.read_bytes(),
            content_type="text/plain",
        )
        row = DashboardData.objects.create(
            dashboard_title="HepaGeNIE",
            dashboard_slug="liver-resource",
            source_file=upload,
            data_updated_at=date(2026, 4, 20),
        )
        # create() regenerates figures and sets data_updated_at to today; pin the display date.
        DashboardData.objects.filter(pk=row.pk).update(data_updated_at=date(2026, 4, 20))
        self.page.__dict__.pop("dashboard_data", None)

        response = self.client.get(self.page.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Liver Resource")
        self.assertContains(response, "Data last updated")
        self.assertContains(response, "April 20, 2026")
        self.assertContains(response, "liver-tln-plot")
        self.assertContains(response, "plotly-graph-div")
        self.assertContains(response, "tln-container")
        self.assertContains(response, "liver-upload-form")
        self.assertNotContains(response, "module-detail")
        self.assertContains(response, "Neutral base network")
        self.assertContains(response, "HCC Control")


class TestLiverResourceDashboardDataIntegration(LiverResourcePageTestCase):
    """Tests for liver page integration with DashboardData figures."""

    def test_get_context_uses_dashboard_data_base_tln(self) -> None:
        """Test page load reads base_tln from DashboardData when row exists."""
        example_path = get_data_root() / "examples" / "HCC-Control.txt"
        from django.core.files.uploadedfile import SimpleUploadedFile

        upload = SimpleUploadedFile(
            name="HCC-Control.txt",
            content=example_path.read_bytes(),
            content_type="text/plain",
        )
        DashboardData.objects.create(
            dashboard_title="HepaGeNIE",
            dashboard_slug="liver-resource",
            source_file=upload,
            data_updated_at=date(2026, 4, 20),
        )

        with patch(
            "dashboard_visualisation.liver_resource.dashboard_figures.build_base_figure_json"
        ) as mock_build:
            request = self.client.get(self.page.url).wsgi_request
            context = self.page.get_context(request)
            mock_build.assert_not_called()

        self.assertIn("data", context["base_tln_figure_json"])

    def test_dashboard_data_updated_at_prefers_snippet_date(self) -> None:
        """Test index card date uses DashboardData when snippet row exists."""
        from django.core.files.uploadedfile import SimpleUploadedFile

        example_path = get_data_root() / "examples" / "HCC-Control.txt"
        upload = SimpleUploadedFile(
            name="HCC-Control.txt",
            content=example_path.read_bytes(),
            content_type="text/plain",
        )
        row = DashboardData.objects.create(
            dashboard_title="HepaGeNIE",
            dashboard_slug="liver-resource",
            source_file=upload,
            data_updated_at=date(2026, 5, 1),
        )
        DashboardData.objects.filter(pk=row.pk).update(data_updated_at=date(2026, 5, 1))
        self.page.__dict__.pop("dashboard_data", None)

        self.assertEqual(self.page.dashboard_data_updated_at, date(2026, 5, 1))


class TestLiverResourceDashboardIndexListing(LiverResourcePageTestCase):
    """Tests for liver dashboard visibility on the index page."""

    def test_dashboard_data_updated_at_without_snippet_is_none(self) -> None:
        """Test index card date is absent until DashboardData exists."""
        self.assertIsNone(self.page.dashboard_data_updated_at)

    def test_liver_page_appears_in_dashboard_index(self) -> None:
        """Test that liver dashboards are listed alongside standard dashboards."""
        standard_image = create_test_image(title="Standard", file_name="standard.jpg")
        standard = DashboardPage(
            title="Serology",
            slug="serology",
            description="Standard dashboard",
            image=standard_image,
            data_status="active",
            content=[("text", "<p>Standard dashboard intro.</p>")],
        )
        self.index.add_child(instance=standard)
        standard.save_revision().publish()

        request = RequestFactory().get(self.index.url)
        context = self.index.get_context(request)

        titles = [page.title for page in context["dashboards_list"]]
        self.assertIn("Liver Resource", titles)
        self.assertIn("Serology", titles)
