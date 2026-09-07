"""Tests for the SLUDashboardPage model."""

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


class TestSLUDashboardPage(WagtailPageTestCase):
    """Tests for the SLUDashboardPage model."""

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
        cls.page = SLUDashboardPage(
            title="SLU wastewater",
            slug="slu-wastewater",
            description="SLU wastewater description",
            image=cls.image,
            data_status="active",
        )
        cls.index.add_child(instance=cls.page)
        cls.page.save_revision().publish()

    def test_max_count_set_on_model(self):
        """Test that only one instance of SLUDashboardPage can be created."""
        self.assertEqual(SLUDashboardPage.max_count, 1)

    def test_parent_page_type_restriction(self):
        """Test that only DashboardIndexPage can be a parent of SLUDashboardPage."""
        self.assertEqual(SLUDashboardPage.parent_page_types, ["cms.DashboardIndexPage"])

    def test_subpage_type_restriction(self):
        """Test that only SLUDashboardSubPage can be added as a child."""
        self.assertEqual(SLUDashboardPage.subpage_types, ["cms.SLUDashboardSubPage"])

    def test_inherits_ebi_catalogue_panel(self):
        """SLU keeps the EBI panel after replacing the parent content field."""
        headings = [getattr(panel, "heading", None) for panel in SLUDashboardPage.content_panels]
        self.assertIn("EBI / European Pathogens Portal", headings)
        self.assertEqual(self.page.ebi_data_type, "")
        self.assertEqual(self.page.ebi_data_source, "")

    def test_navigation_tabs_without_children(self):
        """Test that navigation_tabs contains only the overview link without children."""
        self.assertEqual(self.page.navigation_tabs, [{"title": "Overview", "url": self.page.url}])

    def test_navigation_tabs_with_children(self):
        """Test that navigation_tabs contains live children sorted by order and title."""

        child_b = SLUDashboardSubPage(title="B child", slug="b-child", navigation_order=2)
        child_a = SLUDashboardSubPage(title="A child", slug="a-child", navigation_order=1)
        child_c = SLUDashboardSubPage(title="C child", slug="c-child", navigation_order=1)
        child_d = SLUDashboardSubPage(
            title="D child", slug="d-child", navigation_order=3, include_in_navigation=False
        )

        self.page.add_child(instance=child_b)
        self.page.add_child(instance=child_a)
        self.page.add_child(instance=child_c)
        self.page.add_child(instance=child_d)

        child_a.save_revision().publish()
        child_b.save_revision().publish()
        child_c.save_revision().publish()
        child_d.save_revision().publish()

        self.assertEqual(
            self.page.navigation_tabs,
            [
                {"title": "Overview", "url": self.page.url},
                {"title": "A child", "url": child_a.url},
                {"title": "C child", "url": child_c.url},
                {"title": "B child", "url": child_b.url},
            ],
        )

    @patch("cms.pages.dashboard.DashboardPage.dashboard_data")
    @patch("cms.pages.slu_dashboard.get_quant_overview_plot")
    def test_htmx_request_returns_plot_html(
        self, mock_get_plot: MagicMock, mock_dashboard_data: MagicMock
    ):
        """Test that an HTMX request returns the generated plot HTML."""
        sample_data = get_sample_data()
        q = QueryDict(
            "years=2023&years=2024"
            "&months=1"
            "&sites=Göteborg&sites=Kalmar"
            "&methods=pmmov_normalised"
            "&timeseries=1"
        )
        mock_dashboard_data.data = {"raw_data": sample_data}
        mock_get_plot.return_value = "<div>plot</div>"

        response = self.client.get(self.page.url, q, HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), "<div>plot</div>")
        mock_get_plot.assert_called_once_with(data=sample_data, as_html=True, **dict(q.lists()))

    def test_htmx_request_without_raw_data_returns_error(self):
        """Test that an HTMX request without raw data returns an error message."""

        response = self.client.get(self.page.url, HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "'Raw data' not found")

    def test_non_htmx_request_uses_default_serve(self):
        """Test that a non-HTMX request uses the default Wagtail serve behaviour."""
        response = self.client.get(self.page.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "cms/pages/slu_wastewater/slu_dashboard.html")
