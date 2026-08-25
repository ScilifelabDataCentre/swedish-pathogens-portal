"""Tests for DashboardData model."""

from unittest.mock import patch

from django.contrib.auth.models import Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse
from django.views.generic import View
from wagtail.admin.models import Admin
from wagtail.snippets.views.snippets import EditView, HistoryView, RevisionsCompareView, UsageView

from cms.snippets.dashboard_data import (
    DashboardData,
    DashboardDataEditView,
    DashboardDataHistoryView,
    DashboardDataRevisionsCompareView,
    DashboardDataUsageView,
    DashboardDataViewSet,
    _is_internal_user,
    _user_can_access_dashboard_data,
)


class TestDashboardDataModel(TestCase):
    """Tests for the DashboardData model fields and constraints."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Create a DashboardData instance for testing."""
        cls.source_file = SimpleUploadedFile(
            name="test_data.csv",
            content=b"date,value\n2024-01-01,100\n2024-01-02,200\n",
            content_type="text/csv",
        )
        cls.dashboard_data = DashboardData.objects.create(
            dashboard_title="Serology statistics",
            dashboard_slug="serology-statistics",
            source_file=cls.source_file,
            uploaded_by="testuser",
        )
        cls.dashboard_data.data = {"serology_chart": {"data": [], "layout": {}}}
        cls.dashboard_data.save(update_fields=["data"])

    def test_str_representation_includes_title(self) -> None:
        """Test that string representation includes the dashboard title."""
        result = str(self.dashboard_data)
        self.assertIn("Serology statistics", result)

    def test_ordering_is_by_slug(self) -> None:
        """Test that default ordering is by dashboard_slug."""
        self.assertEqual(DashboardData._meta.ordering, ["dashboard_slug"])

    def test_dashboard_slug_is_unique(self) -> None:
        """Test that only one row is allowed per dashboard_slug."""
        duplicate_file = SimpleUploadedFile("dup.csv", b"a,b\n1,2\n", "text/csv")
        with self.assertRaises(IntegrityError):
            DashboardData.objects.create(
                dashboard_slug="serology-statistics",
                source_file=duplicate_file,
                uploaded_by="testuser",
            )

    def test_source_file_upload_path(self) -> None:
        """Test that the source file is stored under dashboard_data/."""
        self.assertIn("dashboard_data/", self.dashboard_data.source_file.name)

    def test_data_field_stores_json(self) -> None:
        """Test that the data JSONField stores and retrieves correctly."""
        self.assertEqual(
            self.dashboard_data.data,
            {"serology_chart": {"data": [], "layout": {}}},
        )

    def test_data_updated_at_optional(self) -> None:
        """Test that data_updated_at can be set and saved independently."""
        from datetime import date

        self.dashboard_data.data_updated_at = date(2024, 6, 15)
        self.dashboard_data.save(update_fields=["data_updated_at"])
        self.dashboard_data.refresh_from_db()
        self.assertEqual(self.dashboard_data.data_updated_at, date(2024, 6, 15))


class TestDashboardDataGetData(TestCase):
    """Tests for the DashboardData.get_data class method."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Create a DashboardData row for lookup tests."""
        cls.source_file = SimpleUploadedFile(
            name="current.csv",
            content=b"date,value\n2024-01-01,100\n",
            content_type="text/csv",
        )
        cls.row = DashboardData.objects.create(
            dashboard_slug="serology-statistics",
            source_file=cls.source_file,
            data={"chart": {}},
            uploaded_by="testuser",
        )

    def test_returns_row_for_slug(self) -> None:
        """Test that get_data returns the row for a dashboard slug."""
        result = DashboardData.get_data("serology-statistics")
        self.assertEqual(result, self.row)

    def test_returns_none_for_missing_slug(self) -> None:
        """Test that get_data returns None when no data exists for slug."""
        result = DashboardData.get_data("nonexistent-dashboard")
        self.assertIsNone(result)


class DashboardDataAccessTests(TestCase):
    """Tests for access control on DashboardData based on user groups."""

    def setUp(self) -> None:
        """Create users and groups for access control tests."""
        source_file = SimpleUploadedFile(
            name="current.csv",
            content=b"date,value\n2024-01-01,100\n",
            content_type="text/csv",
        )

        dashboard_data_permission = Permission.objects.get(
            content_type=ContentType.objects.get_for_model(DashboardData),
            codename="change_dashboarddata",
        )
        admin_permission = Permission.objects.get(
            content_type=ContentType.objects.get_for_model(Admin),
            codename="access_admin",
        )
        self.editors = Group.objects.get(name="Editors")
        self.editors.permissions.add(dashboard_data_permission, admin_permission)
        self.researchers = Group.objects.create(name="researchers")
        self.researchers.permissions.add(dashboard_data_permission, admin_permission)
        self.other_researchers = Group.objects.create(name="other-researchers")

        self.researcher = User.objects.create_user(username="researcher", password="password")  # noqa: S106
        self.researcher.groups.add(self.researchers)

        self.editor = User.objects.create_user(username="editor", password="password")  # noqa: S106
        self.editor.groups.add(self.editors)

        self.superuser = User.objects.create_superuser(username="admin", password="password")  # noqa: S106

        self.own_data = DashboardData.objects.create(
            dashboard_title="Own dashboard",
            dashboard_slug="own-dashboard",
            research_group=self.researchers,
            source_file=source_file,
            data={"chart": {}},
        )

        self.other_data = DashboardData.objects.create(
            dashboard_title="Other dashboard",
            dashboard_slug="other-dashboard",
            research_group=self.other_researchers,
            source_file=source_file,
            data={"chart": {}},
        )

        self.unassigned_data = DashboardData.objects.create(
            dashboard_title="Unassigned dashboard",
            dashboard_slug="unassigned-dashboard",
            research_group=None,
            source_file=source_file,
            data={"chart": {}},
        )

    # ------------------------------------------------------------------
    # _is_internal_user
    # ------------------------------------------------------------------

    def test_superuser_is_internal_user(self) -> None:
        """Test that returns True for super user."""
        self.assertTrue(_is_internal_user(self.superuser))

    def test_editor_is_internal_user(self) -> None:
        """Test that returns True for editor."""
        self.assertTrue(_is_internal_user(self.editor))

    def test_researcher_is_not_internal_user(self) -> None:
        """Test that returns False for other user."""
        self.assertFalse(_is_internal_user(self.researcher))

    def test_none_is_not_internal_user(self) -> None:
        """Test that returns False for passed None."""
        self.assertFalse(_is_internal_user(None))

    # ------------------------------------------------------------------
    # _user_can_access_dashboard_data
    # ------------------------------------------------------------------

    def test_superuser_can_access_dashboard_data(self) -> None:
        """Test that superusers can access other dashboard data."""
        self.assertTrue(_user_can_access_dashboard_data(self.superuser, self.other_data))

    def test_editor_can_access_other_dashboard_data(self) -> None:
        """Test that editors cannot access other dashboard data."""
        self.assertTrue(_user_can_access_dashboard_data(self.editor, self.other_data))

    def test_researcher_can_access_own_dashboard_data(self) -> None:
        """Test that researchers can access their own dashboard data."""
        self.assertTrue(_user_can_access_dashboard_data(self.researcher, self.own_data))

    def test_researcher_cannot_access_other_dashboard_data(self) -> None:
        """Test that researchers cannot access other dashboard data."""
        self.assertFalse(_user_can_access_dashboard_data(self.researcher, self.other_data))

    def test_none_user_cannot_access_dashboard_data(self) -> None:
        """Test that None user cannot access any dashboard data."""
        self.assertFalse(_user_can_access_dashboard_data(None, self.own_data))

    # ------------------------------------------------------------------
    # DashboardDataForm
    # ------------------------------------------------------------------

    def test_research_group_field_visible_to_superuser(self) -> None:
        """Test research_group field appears in the admin form for superuser."""

        self.client.force_login(self.superuser)
        response = self.client.get(
            reverse("wagtailsnippets_cms_dashboarddata:edit", args=[self.own_data.pk])
        )

        self.assertContains(response, 'name="research_group"')

    def test_research_group_field_visible_to_editor(self) -> None:
        """Test research_group field appears in the admin form for editors."""

        self.client.force_login(self.editor)
        response = self.client.get(
            reverse("wagtailsnippets_cms_dashboarddata:edit", args=[self.own_data.pk])
        )

        self.assertContains(response, 'name="research_group"')

    def test_research_group_field_not_visible_to_researcher(self) -> None:
        """Test research_group field doesn't appear in the admin form for researchers."""

        self.client.force_login(self.researcher)
        response = self.client.get(
            reverse("wagtailsnippets_cms_dashboarddata:edit", args=[self.own_data.pk])
        )

        self.assertNotContains(response, 'name="research_group"')

    # ------------------------------------------------------------------
    # DashboardDataViewSet.get_queryset
    # ------------------------------------------------------------------

    def test_researcher_only_sees_dashboard_data_for_their_group(self) -> None:
        """Test that researcher only see dashboard data assigned to their group."""
        request = self.client.get("/").wsgi_request
        request.user = self.researcher

        queryset = DashboardDataViewSet().get_queryset(request)

        self.assertIn(self.own_data, queryset)
        self.assertNotIn(self.other_data, queryset)
        self.assertNotIn(self.unassigned_data, queryset)

    def test_editor_sees_all_dashboard_data(self) -> None:
        """Test that internal editors can see all dashboard data."""
        request = self.client.get("/").wsgi_request
        request.user = self.editor

        queryset = DashboardDataViewSet().get_queryset(request)

        self.assertIn(self.own_data, queryset)
        self.assertIn(self.other_data, queryset)
        self.assertIn(self.unassigned_data, queryset)

    def test_superuser_sees_all_dashboard_data(self) -> None:
        """Test that superusers can see all dashboard data."""
        request = self.client.get("/").wsgi_request
        request.user = self.superuser

        queryset = DashboardDataViewSet().get_queryset(request)

        self.assertIn(self.own_data, queryset)
        self.assertIn(self.other_data, queryset)
        self.assertIn(self.unassigned_data, queryset)

    # ------------------------------------------------------------------
    # DashboardDataEditView
    # ------------------------------------------------------------------

    def test_researcher_can_access_only_own_dashboard_data(self) -> None:
        """Test researchers can access edit page only for assigned dashboard data."""
        view = self._get_view(self.researcher, DashboardDataEditView)

        with patch.object(EditView, "get_object", return_value=self.own_data):
            self.assertEqual(view.get_object(), self.own_data)

        with (
            patch.object(EditView, "get_object", return_value=self.other_data),
            self.assertRaises(PermissionDenied),
        ):
            view.get_object()

        with (
            patch.object(EditView, "get_object", return_value=self.unassigned_data),
            self.assertRaises(PermissionDenied),
        ):
            view.get_object()

    def test_editor_can_access_other_research_group(self) -> None:
        """Test editors can access edit page of any dashboard data."""
        view = self._get_view(self.editor, DashboardDataEditView)

        with patch.object(EditView, "get_object", return_value=self.own_data):
            self.assertEqual(view.get_object(), self.own_data)
        with patch.object(EditView, "get_object", return_value=self.other_data):
            self.assertEqual(view.get_object(), self.other_data)
        with patch.object(EditView, "get_object", return_value=self.unassigned_data):
            self.assertEqual(view.get_object(), self.unassigned_data)

    def test_superuser_can_access_other_research_group(self) -> None:
        """Test superusers can access edit page of any dashboard data."""
        view = self._get_view(self.superuser, DashboardDataEditView)

        with patch.object(EditView, "get_object", return_value=self.own_data):
            self.assertEqual(view.get_object(), self.own_data)
        with patch.object(EditView, "get_object", return_value=self.other_data):
            self.assertEqual(view.get_object(), self.other_data)
        with patch.object(EditView, "get_object", return_value=self.unassigned_data):
            self.assertEqual(view.get_object(), self.unassigned_data)

    # ------------------------------------------------------------------
    # DashboardDataHistoryView
    # ------------------------------------------------------------------

    def test_researcher_can_access_only_own_dashboard_data_history(self) -> None:
        """Test researchers can access history page only for assigned dashboard data."""
        view = self._get_view(self.researcher, DashboardDataHistoryView)

        with patch.object(HistoryView, "get_object", return_value=self.own_data):
            self.assertEqual(view.get_object(), self.own_data)

        with (
            patch.object(HistoryView, "get_object", return_value=self.other_data),
            self.assertRaises(PermissionDenied),
        ):
            view.get_object()

        with (
            patch.object(HistoryView, "get_object", return_value=self.unassigned_data),
            self.assertRaises(PermissionDenied),
        ):
            view.get_object()

    def test_editor_can_access_other_research_group_history(self) -> None:
        """Test editors can access history page of any dashboard data."""
        view = self._get_view(self.editor, DashboardDataHistoryView)

        with patch.object(HistoryView, "get_object", return_value=self.own_data):
            self.assertEqual(view.get_object(), self.own_data)
        with patch.object(HistoryView, "get_object", return_value=self.other_data):
            self.assertEqual(view.get_object(), self.other_data)
        with patch.object(HistoryView, "get_object", return_value=self.unassigned_data):
            self.assertEqual(view.get_object(), self.unassigned_data)

    def test_superuser_can_access_other_research_group_history(self) -> None:
        """Test superusers can access history page of any dashboard data."""
        view = self._get_view(self.superuser, DashboardDataHistoryView)

        with patch.object(HistoryView, "get_object", return_value=self.own_data):
            self.assertEqual(view.get_object(), self.own_data)
        with patch.object(HistoryView, "get_object", return_value=self.other_data):
            self.assertEqual(view.get_object(), self.other_data)
        with patch.object(HistoryView, "get_object", return_value=self.unassigned_data):
            self.assertEqual(view.get_object(), self.unassigned_data)

    # ------------------------------------------------------------------
    # DashboardDataRevisionsCompareView
    # ------------------------------------------------------------------

    def test_researcher_can_access_only_own_dashboard_data_revisions(self) -> None:
        """Test researchers can access revision page only for assigned dashboard data."""
        view = self._get_view(self.researcher, DashboardDataRevisionsCompareView)

        with patch.object(RevisionsCompareView, "get_object", return_value=self.own_data):
            self.assertEqual(view.get_object(), self.own_data)

        with (
            patch.object(RevisionsCompareView, "get_object", return_value=self.other_data),
            self.assertRaises(PermissionDenied),
        ):
            view.get_object()

        with (
            patch.object(RevisionsCompareView, "get_object", return_value=self.unassigned_data),
            self.assertRaises(PermissionDenied),
        ):
            view.get_object()

    def test_editor_can_access_other_research_group_revisions(self) -> None:
        """Test editors can access revision page of any dashboard data."""
        view = self._get_view(self.editor, DashboardDataRevisionsCompareView)

        with patch.object(RevisionsCompareView, "get_object", return_value=self.own_data):
            self.assertEqual(view.get_object(), self.own_data)
        with patch.object(RevisionsCompareView, "get_object", return_value=self.other_data):
            self.assertEqual(view.get_object(), self.other_data)
        with patch.object(RevisionsCompareView, "get_object", return_value=self.unassigned_data):
            self.assertEqual(view.get_object(), self.unassigned_data)

    def test_superuser_can_access_other_research_group_revisions(self) -> None:
        """Test superusers can access revision page of any dashboard data."""
        view = self._get_view(self.superuser, DashboardDataRevisionsCompareView)

        with patch.object(RevisionsCompareView, "get_object", return_value=self.own_data):
            self.assertEqual(view.get_object(), self.own_data)
        with patch.object(RevisionsCompareView, "get_object", return_value=self.other_data):
            self.assertEqual(view.get_object(), self.other_data)
        with patch.object(RevisionsCompareView, "get_object", return_value=self.unassigned_data):
            self.assertEqual(view.get_object(), self.unassigned_data)

    # ------------------------------------------------------------------
    # DashboardDataUsageView
    # ------------------------------------------------------------------

    def test_researcher_can_access_only_own_dashboard_data_usage(self) -> None:
        """Test researchers can access usage page only for assigned dashboard data."""
        view = self._get_view(self.researcher, DashboardDataUsageView)

        with patch.object(UsageView, "get_object", return_value=self.own_data):
            self.assertEqual(view.get_object(), self.own_data)

        with (
            patch.object(UsageView, "get_object", return_value=self.other_data),
            self.assertRaises(PermissionDenied),
        ):
            view.get_object()

        with (
            patch.object(UsageView, "get_object", return_value=self.unassigned_data),
            self.assertRaises(PermissionDenied),
        ):
            view.get_object()

    def test_editor_can_access_other_research_group_usage(self) -> None:
        """Test editors can access usage page of any dashboard data."""
        view = self._get_view(self.editor, DashboardDataUsageView)

        with patch.object(UsageView, "get_object", return_value=self.own_data):
            self.assertEqual(view.get_object(), self.own_data)
        with patch.object(UsageView, "get_object", return_value=self.other_data):
            self.assertEqual(view.get_object(), self.other_data)
        with patch.object(UsageView, "get_object", return_value=self.unassigned_data):
            self.assertEqual(view.get_object(), self.unassigned_data)

    def test_superuser_can_access_other_research_group_usage(self) -> None:
        """Test superusers can access usage page of any dashboard data."""
        view = self._get_view(self.superuser, DashboardDataUsageView)

        with patch.object(UsageView, "get_object", return_value=self.own_data):
            self.assertEqual(view.get_object(), self.own_data)
        with patch.object(UsageView, "get_object", return_value=self.other_data):
            self.assertEqual(view.get_object(), self.other_data)
        with patch.object(UsageView, "get_object", return_value=self.unassigned_data):
            self.assertEqual(view.get_object(), self.unassigned_data)

    # ------------------------------------------------------------------
    # Helper method
    # ------------------------------------------------------------------

    def _get_view(self, user: User, view_class: type[View]) -> View:
        """Return view with given user."""
        request = self.client.get("/").wsgi_request
        request.user = user

        view = view_class()
        view.request = request

        return view
