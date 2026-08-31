"""Tests for DashboardPage and DashboardIndexPage."""

from datetime import date
from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory
from wagtail.models import Page, Site
from wagtail.test.utils import WagtailPageTestCase

from cms.pages.dashboard import DATA_STATUS_CHOICES, DashboardEbiPathogen, DashboardPage
from cms.pages.dashboard_index import DashboardIndexPage
from cms.pages.drr_dataset import DrrDatasetPage
from cms.pages.home import HomePage
from cms.pages.slu_dashboard import SLUDashboardPage
from cms.snippets.dashboard_data import DashboardData
from cms.tests.utils import create_test_image


class DashboardPageTestCase(WagtailPageTestCase):
    """Base test case that creates the page tree for dashboard tests."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Create site with home page and dashboard index page."""
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


class TestDashboardPageModel(DashboardPageTestCase):
    """Tests for the DashboardPage model fields and constraints."""

    def test_parent_page_type_restriction(self) -> None:
        """Test that only DashboardIndexPage can be a parent."""
        self.assertEqual(DashboardPage.parent_page_types, ["cms.DashboardIndexPage"])

    def test_subpage_type_restriction(self) -> None:
        """Test that DashboardPage cannot have child pages."""
        self.assertEqual(DashboardPage.subpage_types, [])

    def test_data_status_has_correct_choices(self) -> None:
        """Test that data_status field has active and historic choices."""
        field = DashboardPage._meta.get_field("data_status")
        self.assertEqual(field.choices, DATA_STATUS_CHOICES)

    def test_data_status_has_no_default(self) -> None:
        """Test that data_status has no default (editor must select)."""
        field = DashboardPage._meta.get_field("data_status")
        self.assertFalse(field.has_default())

    def test_content_includes_collapsible_block(self) -> None:
        """Dashboard StreamField includes collapsible sections for long prose."""
        child_blocks = DashboardPage._meta.get_field("content").stream_block.child_blocks
        self.assertEqual(
            set(child_blocks.keys()),
            {
                "text",
                "alert",
                "collapsible",
                "data_table",
                "last_updated",
                "plotly_figure",
                "static_figure",
            },
        )


class TestDashboardPageEbiFields(DashboardPageTestCase):
    """Tests for optional EBI catalogue fields on DashboardPage."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Create a dashboard page for EBI field tests."""
        super().setUpTestData()
        cls.image = create_test_image(title="EBI Image", file_name="ebi.jpg")

    def _add_dashboard(self, **kwargs: object) -> DashboardPage:
        """Create and publish a DashboardPage under the index."""
        page = DashboardPage(
            title="Serology",
            slug="serology-statistics",
            description="Serology test dashboard",
            image=self.image,
            data_status="active",
            **kwargs,
        )
        self.index.add_child(instance=page)
        page.save_revision().publish()
        return page

    def test_ebi_data_type_is_optional_free_text(self) -> None:
        """ebi_data_type is blank by default and has no choices."""
        field = DashboardPage._meta.get_field("ebi_data_type")
        self.assertTrue(field.blank)
        self.assertFalse(field.choices)
        self.assertEqual(field.get_default(), "")

    def test_ebi_data_source_is_optional_free_text(self) -> None:
        """ebi_data_source is blank by default and has no choices."""
        field = DashboardPage._meta.get_field("ebi_data_source")
        self.assertTrue(field.blank)
        self.assertFalse(field.choices)
        self.assertEqual(field.get_default(), "")

    def test_does_not_add_ebi_name_id_or_country(self) -> None:
        """Catalogue name uses Title; id and country are not page fields."""
        field_names = {field.name for field in DashboardPage._meta.get_fields()}
        self.assertNotIn("ebi_name", field_names)
        self.assertNotIn("ebi_id", field_names)
        self.assertNotIn("country", field_names)

    def test_page_saves_with_empty_ebi_fields(self) -> None:
        """Existing dashboards remain valid when EBI fields are left blank."""
        page = self._add_dashboard()
        self.assertEqual(page.ebi_data_type, "")
        self.assertEqual(page.ebi_data_source, "")
        self.assertEqual(page.ebi_type_of_pathogens.count(), 0)

    def test_page_saves_editor_supplied_ebi_values(self) -> None:
        """Editors can store free-text data type, source, and multiple pathogens."""
        page = self._add_dashboard(
            ebi_data_type="Serology",
            ebi_data_source="Autoimmunity and Serology profiling facility",
        )
        DashboardEbiPathogen.objects.create(page=page, ebi_type_of_pathogen="SARS-CoV-2")
        DashboardEbiPathogen.objects.create(page=page, ebi_type_of_pathogen="Influenza")

        page.refresh_from_db()
        self.assertEqual(page.ebi_data_type, "Serology")
        self.assertEqual(
            page.ebi_data_source,
            "Autoimmunity and Serology profiling facility",
        )
        self.assertEqual(
            list(page.ebi_type_of_pathogens.values_list("ebi_type_of_pathogen", flat=True)),
            ["SARS-CoV-2", "Influenza"],
        )

    def test_ebi_panel_is_before_content(self) -> None:
        """EBI panel heading is present and content stays last for subclass slicing."""
        headings = [getattr(panel, "heading", None) for panel in DashboardPage.content_panels]
        self.assertIn("EBI / European Pathogens Portal", headings)
        self.assertEqual(DashboardPage.content_panels[-1].field_name, "content")
        ebi_index = headings.index("EBI / European Pathogens Portal")
        content_index = len(DashboardPage.content_panels) - 1
        self.assertLess(ebi_index, content_index)

    def test_ebi_panel_has_no_help_ribbons(self) -> None:
        """Admin labels are explicit; panel and pathogen inline have no help banners."""
        ebi_panel = next(
            panel
            for panel in DashboardPage.content_panels
            if getattr(panel, "heading", None) == "EBI / European Pathogens Portal"
        )
        self.assertFalse(getattr(ebi_panel, "help_text", None))
        self.assertEqual(
            DashboardPage._meta.get_field("ebi_data_type").verbose_name,
            "EBI data type",
        )
        self.assertEqual(
            DashboardPage._meta.get_field("ebi_data_source").verbose_name,
            "EBI data source",
        )
        pathogen_inline = next(
            child
            for child in ebi_panel.children
            if getattr(child, "relation_name", None) == "ebi_type_of_pathogens"
        )
        self.assertFalse(getattr(pathogen_inline, "help_text", None))

    def test_subclasses_keep_ebi_panel_after_content_splice(self) -> None:
        """SLU and DRR panel splicing still includes the EBI panel."""
        slu_headings = [
            getattr(panel, "heading", None) for panel in SLUDashboardPage.content_panels
        ]
        drr_headings = [getattr(panel, "heading", None) for panel in DrrDatasetPage.content_panels]
        self.assertIn("EBI / European Pathogens Portal", slu_headings)
        self.assertIn("EBI / European Pathogens Portal", drr_headings)
        self.assertEqual(DrrDatasetPage.content_panels[-1].field_name, "content")


class TestDashboardPageContext(DashboardPageTestCase):
    """Tests for DashboardPage.get_context method."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Create a dashboard page for context tests."""
        super().setUpTestData()
        cls.image = create_test_image(title="Dash Image", file_name="dash.jpg")
        cls.page = DashboardPage(
            title="Serology",
            slug="serology-statistics",
            description="Serology test dashboard",
            image=cls.image,
            data_status="active",
        )
        cls.index.add_child(instance=cls.page)
        cls.page.save_revision().publish()
        cls.historic = DashboardPage(
            title="Old serology",
            slug="old-serology",
            description="Historic serology dashboard",
            image=cls.image,
            data_status="historic",
        )
        cls.index.add_child(instance=cls.historic)
        cls.historic.save_revision().publish()

    def test_get_context_includes_figures_from_dashboard_data(self) -> None:
        """Test that get_context provides figures from DashboardData."""
        csv_file = SimpleUploadedFile("data.csv", b"a,b\n1,2\n", "text/csv")
        data_row = DashboardData.objects.create(
            dashboard_slug="serology-statistics",
            source_file=csv_file,
        )
        data_row.data = {"chart_1": {"data": [], "layout": {}}}
        data_row.save(update_fields=["data"])

        request = self.client.get(self.page.url).wsgi_request
        context = self.page.get_context(request)

        self.assertIn("figures", context)
        self.assertIn("chart_1", context["figures"])
        self.assertEqual(context["source_file_hash"], data_row.source_file_hash)

    def test_get_context_handles_missing_dashboard_data(self) -> None:
        """Test that get_context works when no DashboardData exists."""
        request = self.client.get(self.page.url).wsgi_request
        context = self.page.get_context(request)

        self.assertEqual(context["figures"], {})
        self.assertIsNone(context["dashboard_data"])
        self.assertEqual(context["source_file_hash"], "")

    def test_historic_dashboard_context_matches_active_shape(self) -> None:
        """Historic status does not change get_context keys used by TOC caching."""
        request = self.client.get(self.historic.url).wsgi_request
        context = self.historic.get_context(request)

        self.assertEqual(self.historic.data_status, "historic")
        self.assertEqual(context["figures"], {})
        self.assertEqual(context["source_file_hash"], "")

    def test_get_context_includes_dashboard_data_object(self) -> None:
        """Test that the full DashboardData object is in context."""
        csv_file = SimpleUploadedFile("data2.csv", b"x,y\n3,4\n", "text/csv")
        data_row = DashboardData.objects.create(
            dashboard_slug="serology-statistics",
            source_file=csv_file,
        )
        data_row.data = {"fig_a": {"data": [1], "layout": {}}}
        data_row.save(update_fields=["data"])

        request = self.client.get(self.page.url).wsgi_request
        context = self.page.get_context(request)

        self.assertEqual(context["dashboard_data"].pk, data_row.pk)

    def test_get_context_includes_data_updated_at(self) -> None:
        """Test that get_context exposes the public data freshness date."""
        from datetime import date

        source_file = SimpleUploadedFile("data3.csv", b"x,y\n3,4\n", "text/csv")
        data_row = DashboardData.objects.create(
            dashboard_slug="serology-statistics",
            source_file=source_file,
            data={},
        )
        data_row.data_updated_at = date(2024, 3, 1)
        data_row.save(update_fields=["data_updated_at"])

        request = self.client.get(self.page.url).wsgi_request
        context = self.page.get_context(request)

        self.assertEqual(context["data_updated_at"], date(2024, 3, 1))


class TestDashboardIndexPageModel(DashboardPageTestCase):
    """Tests for the DashboardIndexPage model."""

    def test_max_count_is_one(self) -> None:
        """Test that only one DashboardIndexPage can exist."""
        self.assertEqual(DashboardIndexPage.max_count, 1)

    def test_parent_page_type_restriction(self) -> None:
        """Test that only HomePage can be a parent."""
        self.assertEqual(DashboardIndexPage.parent_page_types, ["cms.HomePage"])

    def test_subpage_types_allows_dashboard_page_types(self) -> None:
        """Test that standard, DRR, liver, and SLU dashboard pages are allowed children."""
        self.assertEqual(
            DashboardIndexPage.subpage_types,
            [
                "cms.DashboardPage",
                "cms.DrrDatasetPage",
                "cms.LiverResourceDashboardPage",
                "cms.SLUDashboardPage",
            ],
        )

    @patch("cms.pages.dashboard_index.validate_filters")
    def test_get_context_adds_filter_metadata(self, mock_validate_filters: MagicMock):
        """Test that get_context adds the correct filter metadata to the context."""
        mock_validate_filters.return_value = {}

        factory = RequestFactory()
        request = factory.get("/")

        with (
            patch("cms.pages.DashboardTopic.objects.filter") as mock_topic_filter,
            patch("cms.pages.DashboardPage.objects.child_of") as mock_child_of,
        ):
            # Mock topics queryset chain
            mock_topic_filter.return_value.values_list.return_value.distinct.return_value = [
                "COVID-19",
                "Infectious Diseases",
            ]

            # Mock article queryset chain
            dashboard1 = MagicMock()
            dashboard1.dashboard_data_updated_at = date(2024, 1, 1)
            dashboard1.title = "B"

            dashboard2 = MagicMock()
            dashboard2.dashboard_data_updated_at = date(2024, 2, 1)
            dashboard2.title = "A"

            mock_queryset = [dashboard1, dashboard2]
            (
                mock_child_of.return_value.live.return_value.public.return_value.specific.return_value.prefetch_related.return_value.distinct.return_value.filter.return_value
            ) = mock_queryset

            context = self.index.get_context(request)

        self.assertEqual(context["all_topics"], ["COVID-19", "Infectious Diseases"])
        self.assertEqual(
            context["all_status_types"],
            ["Active", "Historic"],
        )
        self.assertEqual(context["dashboards_list"], [dashboard2, dashboard1])

        mock_validate_filters.assert_called_once_with(
            request.GET,
            valid_topics=["COVID-19", "Infectious Diseases"],
            valid_types=["Active", "Historic"],
        )

    @patch("cms.pages.dashboard_index.validate_filters")
    def test_get_context_applies_search_filter(self, mock_validate_filters: MagicMock):
        """Test that get_context applies the search filter correctly."""
        mock_validate_filters.return_value = {
            "search": "influenza",
        }

        factory = RequestFactory()
        request = factory.get("/?search=influenza")

        with (
            patch("cms.pages.DashboardTopic.objects.filter") as mock_topic_filter,
            patch("cms.pages.DashboardPage.objects.child_of") as mock_child_of,
        ):
            mock_topic_filter.return_value.values_list.return_value.distinct.return_value = []

            dashboard = MagicMock()
            dashboard.dashboard_data_updated_at = None
            dashboard.title = "Influenza Dashboard"

            queryset_chain = mock_child_of.return_value.live.return_value.public.return_value.specific.return_value.prefetch_related.return_value.distinct.return_value  # noqa: E501

            queryset_chain.filter.return_value = [dashboard]

            context = self.index.get_context(request)

        args, kwargs = queryset_chain.filter.call_args

        self.assertEqual(context["dashboards_list"], [dashboard])
        queryset_chain.filter.assert_called_once()
        self.assertEqual(len(args), 1)
        self.assertIn("influenza", str(args[0]))
