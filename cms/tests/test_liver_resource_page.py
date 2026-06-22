"""Tests for LiverResourceDashboardPage."""

from django.test import RequestFactory
from wagtail.models import Page, Site
from wagtail.test.utils import WagtailPageTestCase

from cms.pages.dashboard import DashboardPage
from cms.pages.dashboard_index import DashboardIndexPage
from cms.pages.home import HomePage
from cms.pages.liver_resource import LiverResourceDashboardPage
from dashboard_visualisation.liver_resource.computation import VALID_CUTOFFS
from dashboard_visualisation.liver_resource.examples import list_example_slugs, list_examples
from dashboard_visualisation.liver_resource.reference_data import clear_reference_data_cache
from cms.tests.utils import create_test_image


class LiverResourcePageTestCase(WagtailPageTestCase):
    """Base test case with dashboard index for liver page tests."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Create site with home page and dashboard index."""
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

        cls.image = create_test_image(title="Liver Image", file_name="liver.jpg")
        cls.page = LiverResourceDashboardPage(
            title="Liver Resource",
            slug="liver-resource",
            description="DINA Liver Resource dashboard",
            image=cls.image,
            data_status="active",
            content=[("text", "<p>Upload a limma-style DE file to colour the TLN.</p>")],
        )
        cls.index.add_child(instance=cls.page)
        cls.page.save_revision().publish()

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

    def test_get_context_includes_cutoff_choices(self) -> None:
        """Test that get_context exposes all valid DEcutoff modes."""
        request = self.client.get(self.page.url).wsgi_request
        context = self.page.get_context(request)

        self.assertEqual(context["cutoff_choices"], VALID_CUTOFFS)

    def test_get_context_includes_base_plot_html(self) -> None:
        """Test that get_context exposes server-rendered base Plotly HTML."""
        request = self.client.get(self.page.url).wsgi_request
        context = self.page.get_context(request)

        self.assertIn("plotly-graph-div", context["base_plot_html"])
        self.assertEqual(context["plot_height"], 700)
        self.assertEqual(context["leaf_trace_index"], 2)

    def test_get_context_includes_examples(self) -> None:
        """Test that get_context exposes bundled example dataset metadata."""
        request = self.client.get(self.page.url).wsgi_request
        context = self.page.get_context(request)

        self.assertEqual(context["examples"], list_examples())
        slugs = [example["slug"] for example in context["examples"]]
        self.assertEqual(slugs, list_example_slugs())

    def test_get_context_includes_session_flags(self) -> None:
        """Test that get_context exposes session state for export controls."""
        request = self.client.get(self.page.url).wsgi_request
        context = self.page.get_context(request)

        self.assertFalse(context["has_session"])
        self.assertEqual(context["current_cutoff"], "standard")
        self.assertEqual(context["default_cutoff"], "standard")

    def test_get_context_includes_parent_heading(self) -> None:
        """Test that liver pages inherit the dashboard index heading."""
        request = self.client.get(self.page.url).wsgi_request
        context = self.page.get_context(request)

        self.assertEqual(context["page_heading"], "Dashboards")

    def test_get_context_includes_liver_endpoint_urls(self) -> None:
        """Test that get_context exposes client-side liver endpoint URLs."""
        request = self.client.get(self.page.url).wsgi_request
        context = self.page.get_context(request)

        self.assertIn("/cms/liver/upload/", context["liver_upload_url"])
        self.assertIn("/cms/liver/recompute/", context["liver_recompute_url"])
        self.assertIn("{module_id}", context["liver_module_detail_url_pattern"])

    def test_page_includes_htmx_and_plotly_wiring(self) -> None:
        """Test that the page template includes htmx upload wiring and liver JS."""
        response = self.client.get(self.page.url)
        self.assertContains(response, 'hx-post="/cms/liver/upload/"')
        self.assertContains(response, 'hx-target="#liver-tln-panel"')
        self.assertContains(response, 'hx-target-error="#liver-validation-errors"')
        self.assertContains(response, 'id="liver-dashboard"')
        self.assertContains(response, "liver_resource.js")

    def test_page_renders_successfully(self) -> None:
        """Test that the liver dashboard page returns HTTP 200."""
        response = self.client.get(self.page.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Liver Resource")
        self.assertContains(response, "liver-tln-plot")
        self.assertContains(response, "plotly-graph-div")
        self.assertContains(response, "tln-container")
        self.assertContains(response, "liver-upload-form")
        self.assertContains(response, "module-detail")
        self.assertContains(response, "Neutral base network")


class TestLiverResourceDashboardIndexListing(LiverResourcePageTestCase):
    """Tests for liver dashboard visibility on the index page."""

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
