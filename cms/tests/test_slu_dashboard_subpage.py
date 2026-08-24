"""Tests for the SLUDashboardSubPage model."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.http import QueryDict
from wagtail.models import Page, Site
from wagtail.test.utils import WagtailPageTestCase

from cms.pages.dashboard_index import DashboardIndexPage
from cms.pages.home import HomePage
from cms.pages.slu_dashboard import SLUDashboardPage
from cms.pages.slu_dashboard_subpage import SLUDashboardSubPage
from cms.tests.utils import create_test_image
from dashboard_visualisation.tests.fixtures.slu_ww_sample_data import get_sample_data


class TestSLUDashboardSubPage(WagtailPageTestCase):
    """Tests for the SLUDashboardSubPage model."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Create a site setup with a home page and a dashboard index page."""

        root = Page.get_first_root_node()
        for child in root.get_children():
            child.delete()
        root = Page.get_first_root_node()
        cls.home = HomePage(title="Home", slug="home")
        root.add_child(instance=cls.home)

        Site.objects.update_or_create(
            is_default_site=True, defaults={"hostname": "testserver", "root_page": cls.home}
        )

        cls.index = DashboardIndexPage(title="Dashboards", slug="dashboards")
        cls.home.add_child(instance=cls.index)
        cls.index.save_revision().publish()

        cls.image = create_test_image(title="Test image", file_name="test_image.jpg")
        cls.slu_page = SLUDashboardPage(
            title="SLU wastewater",
            slug="slu-wastewater",
            description="SLU wastewater description",
            image=cls.image,
            data_status="active",
            notice="Important notice",
            notice_type="warning",
        )
        cls.index.add_child(instance=cls.slu_page)
        cls.slu_page.save_revision().publish()

        cls.page = SLUDashboardSubPage(
            title="Influenza A virus", slug="influenza-a-virus", navigation_order=1
        )
        cls.slu_page.add_child(instance=cls.page)
        cls.page.save_revision().publish()

    def test_parent_page_type_restriction(self):
        """Test that only DashboardIndexPage can be a parent of SLUDashboardSubPage."""
        self.assertEqual(SLUDashboardSubPage.parent_page_types, ["cms.SLUDashboardPage"])

    def test_parent_returns_dashboard_page(self):
        """Test that parent returns the parent SLUDashboardPage."""
        self.assertEqual(self.page.parent, self.slu_page)

    def test_notice_type_returns_parent_notice_type(self):
        """Test that notice_type returns the notice type from the parent page."""
        self.assertEqual(self.page.notice_type, "warning")

    def test_notice_returns_parent_notice(self):
        """Test that notice returns the notice from the parent page."""
        self.assertEqual(self.page.notice, "Important notice")

    def test_inherit_notice_false(self):
        """Test that inherit_notice set to False works correctly."""
        self.page.inherit_notice = False
        self.page.save_revision().publish()
        self.assertEqual(self.page.notice, "")

    def test_dashboard_data_returns_parent_dashboard_data(self):
        """Test that dashboard_data returns the dashboard data from the parent page."""
        dashboard_data = SimpleNamespace(data={"raw_data": {"some": "data"}})

        with patch.object(
            type(self.slu_page), "dashboard_data", new_callable=lambda: dashboard_data
        ):
            self.assertIs(self.page.dashboard_data, dashboard_data)

    def test_dashboard_data_updated_at_returns_parent_value(self):
        """Test that dashboard_data_updated_at returns the value from the parent page."""
        with patch.object(
            type(self.slu_page),
            "dashboard_data_updated_at",
            new_callable=lambda: "2026-08-13T08:00:00",
        ):
            self.assertEqual(self.page.dashboard_data_updated_at, "2026-08-13T08:00:00")

    def test_get_data_status_display_returns_parent_value(self):
        """Test that get_data_status_display returns the value from the parent page."""
        with patch.object(
            type(self.slu_page),
            "get_data_status_display",
            new_callable=lambda: "Active",
        ):
            self.assertEqual(self.page.get_data_status_display, "Active")

    def test_navigation_tabs_returns_parent_navigation_tabs(self):
        """Test that navigation_tabs returns the navigation tabs from the parent page."""
        navigation_tabs = [
            {"title": "Overview", "url": self.slu_page.url},
            {"title": "Influenza A virus", "url": self.page.url},
        ]

        with patch.object(
            type(self.slu_page),
            "navigation_tabs",
            new_callable=lambda: navigation_tabs,
        ):
            self.assertEqual(self.page.navigation_tabs, navigation_tabs)

    def test_get_context_contains_dashboard_data(self):
        """Test that get_context contains the dashboard data."""
        dashboard_data = SimpleNamespace(
            data={"raw_data": {"some": "data"}}, source_file_hash="abc123"
        )

        with patch.object(
            type(self.slu_page),
            "dashboard_data",
            new_callable=lambda: dashboard_data,
        ):
            context = self.page.get_context(self.client.request())

        self.assertIs(context["dashboard_data"], dashboard_data)

    def test_get_context_contains_figures(self):
        """Test that get_context contains figures from dashboard data."""
        dashboard_data = SimpleNamespace(
            data={"raw_data": {"some": "data"}, "figure": {"x": [1, 2, 3]}}
        )

        with patch.object(
            type(self.slu_page),
            "dashboard_data",
            new_callable=lambda: dashboard_data,
        ):
            context = self.page.get_context(self.client.request())

        self.assertEqual(
            context["figures"], {"raw_data": {"some": "data"}, "figure": {"x": [1, 2, 3]}}
        )

    def test_get_context_contains_parent_information(self):
        """Test that get_context contains the expected parent page information."""
        context = self.page.get_context(self.client.request())

        self.assertEqual(context["page_title"], self.slu_page.title)
        self.assertEqual(context["page_heading"], self.index.title)

    @patch("cms.pages.slu_dashboard_subpage.get_single_site_plot")
    @patch("cms.pages.slu_dashboard.SLUDashboardPage.dashboard_data")
    def test_htmx_request_returns_single_site_plot(
        self, mock_dashboard_data: MagicMock, mock_get_plot: MagicMock
    ):
        """Test that an HTMX request returns the single-site plot HTML."""
        sample_data = get_sample_data()
        q = QueryDict("plot-toggle=single&sites=Göteborg&methods=pmmov_normalised&timeseries=1")
        mock_dashboard_data.data = {"raw_data": sample_data}
        mock_get_plot.return_value = "<div>single-site plot</div>"

        response = self.client.get(self.page.url, q, HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), "<div>single-site plot</div>")

        mock_get_plot.assert_called_once_with(
            data=sample_data, virus=self.page.title, as_html=True, **dict(q.lists())
        )

    @patch("cms.pages.slu_dashboard_subpage.get_all_sites_plot")
    @patch("cms.pages.slu_dashboard.SLUDashboardPage.dashboard_data")
    def test_htmx_request_with_all_plot_toggle_returns_all_sites_plot(
        self, mock_dashboard_data: MagicMock, mock_get_plot: MagicMock
    ):
        """Test that an HTMX request with all toggle returns the all-sites plot HTML."""
        sample_data = get_sample_data()
        q = QueryDict("plot-toggle=all&sites=Göteborg&methods=pmmov_normalised&timeseries=1")
        mock_dashboard_data.data = {"raw_data": sample_data}
        mock_get_plot.return_value = "<div>all-sites plot</div>"

        response = self.client.get(self.page.url, q, HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), "<div>all-sites plot</div>")

        mock_get_plot.assert_called_once_with(
            data=sample_data, virus=self.page.title, as_html=True, **dict(q.lists())
        )

    def test_htmx_request_without_raw_data_returns_error(self):
        """Test that an HTMX request without raw data returns an error message."""

        response = self.client.get(self.page.url, HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "'Raw data' not found")

    def test_htmx_request_with_invalid_virus_returns_error(self):
        """Test that an HTMX request with an invalid virus title returns an error."""
        self.page.title = "Invalid virus"
        self.page.save_revision().publish()

        response = self.client.get(self.page.url, HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "'Invalid virus' not found")

    def test_non_htmx_request_uses_default_serve(self):
        """Test that a non-HTMX request uses the default Wagtail serve behaviour."""
        response = self.client.get(self.page.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "cms/pages/slu_wastewater/slu_dashboard.html")
