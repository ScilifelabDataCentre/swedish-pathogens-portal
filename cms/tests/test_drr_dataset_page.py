"""Tests for DrrDatasetPage and the DrrDatasetData snippet (FREYA-2555)."""

from django.test import RequestFactory
from wagtail.models import Page, Site
from wagtail.test.utils import WagtailPageTestCase

from cms.pages.dashboard_index import DashboardIndexPage
from cms.pages.drr_dataset import DrrDatasetPage
from cms.pages.home import HomePage
from cms.snippets.drr_dataset_data import DrrDatasetData
from cms.tests.utils import create_test_image


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
