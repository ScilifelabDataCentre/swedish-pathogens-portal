"""Tests for DashboardData CSV validation and viz service integration."""

from datetime import date
from io import BytesIO
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from cms.snippets.dashboard_data import DashboardData, get_dashboard_data_save_feedback
from cms.tests.utils import validate_csv
from dashboard_visualisation import generate_figures
from dashboard_visualisation.registry import VIZ_MODULES
from dashboard_visualisation.utils.uploads import calculate_file_hash

SAMPLE_DASHBOARD_SLUG = "sample-dashboard"
SAMPLE_VIZ_MODULE = "cms.tests.sample_viz"
MINIMAL_SAMPLE_CSV = b"""date,value
2024-01-01,10
2024-01-08,5
"""


class TestCsvValidation(TestCase):
    """Tests for the CSV validation service."""

    def test_valid_csv_passes(self) -> None:
        """Test that a well-formed CSV with header and data passes."""
        content = b"date,value\n2024-01-01,100\n2024-01-02,200\n"
        file = BytesIO(content)
        result = validate_csv(file)

        self.assertTrue(result.is_valid)
        self.assertEqual(result.row_count, 2)
        self.assertEqual(result.columns, ["date", "value"])

    def test_empty_file_fails(self) -> None:
        """Test that an empty file fails validation."""
        file = BytesIO(b"")
        result = validate_csv(file)

        self.assertFalse(result.is_valid)
        self.assertIn("empty", result.errors[0].lower())

    def test_whitespace_only_file_fails(self) -> None:
        """Test that a file with only whitespace fails validation."""
        file = BytesIO(b"   \n  \n  ")
        result = validate_csv(file)

        self.assertFalse(result.is_valid)

    def test_header_only_fails(self) -> None:
        """Test that a CSV with only a header row fails."""
        file = BytesIO(b"date,value\n")
        result = validate_csv(file)

        self.assertFalse(result.is_valid)
        self.assertIn("header", result.errors[0].lower())

    def test_non_utf8_file_fails(self) -> None:
        """Test that a non-UTF-8 file fails validation."""
        file = BytesIO(b"\xff\xfe\x00\x01")
        result = validate_csv(file)

        self.assertFalse(result.is_valid)
        self.assertIn("UTF-8", result.errors[0])

    def test_file_seek_reset_after_validation(self) -> None:
        """Test that file position is reset after validation."""
        content = b"col1,col2\na,b\n"
        file = BytesIO(content)
        validate_csv(file)

        self.assertEqual(file.tell(), 0)

    def test_semicolon_delimited_csv_passes(self) -> None:
        """Test that semicolon-separated exports (e.g. Numbers EU locale) pass."""
        content = b"date;count;class\n2024-01-01;10;positive\n2024-01-02;5;negative\n"
        result = validate_csv(BytesIO(content))

        self.assertTrue(result.is_valid)
        self.assertEqual(result.columns, ["date", "count", "class"])
        self.assertEqual(result.row_count, 2)


class TestGenerateFigures(TestCase):
    """Tests for the viz service registry."""

    def setUp(self) -> None:
        """Register a minimal test viz module for dispatch tests."""
        self._viz_modules_patch = patch.dict(
            VIZ_MODULES,
            {SAMPLE_DASHBOARD_SLUG: SAMPLE_VIZ_MODULE},
        )
        self._viz_modules_patch.start()

    def tearDown(self) -> None:
        """Restore the viz module registry."""
        self._viz_modules_patch.stop()

    def test_unregistered_slug_returns_empty_dict(self) -> None:
        """Test that an unregistered dashboard slug returns empty dict."""
        result = generate_figures("nonexistent-dashboard", "/fake/path.csv")
        self.assertEqual(result, {})

    def test_returns_dict_type(self) -> None:
        """Test that generate_figures always returns a dict."""
        result = generate_figures("unknown-slug", "/any/path.csv")
        self.assertIsInstance(result, dict)

    def test_registered_viz_accepts_bytesio_without_path(self) -> None:
        """Test that registered viz services read from in-memory file objects."""
        source = BytesIO(MINIMAL_SAMPLE_CSV)
        result = generate_figures(SAMPLE_DASHBOARD_SLUG, source)

        self.assertEqual(set(result.keys()), {"sample_chart"})

    def test_registered_viz_accepts_semicolon_delimited_csv(self) -> None:
        """Test that registered viz accepts semicolon-separated CSV exports."""
        source = BytesIO(b"date;value\n2024-01-01;10\n2024-01-08;5\n")
        result = generate_figures(SAMPLE_DASHBOARD_SLUG, source)

        self.assertIn("sample_chart", result)

    def test_registered_viz_rewinds_file_after_prior_read(self) -> None:
        """Test that generate_figures works when the file was read earlier (e.g. hashing)."""
        source = BytesIO(MINIMAL_SAMPLE_CSV)
        source.read()
        result = generate_figures(SAMPLE_DASHBOARD_SLUG, source)

        self.assertIn("sample_chart", result)

    def test_registered_viz_reads_committed_field_file(self) -> None:
        """Test that figure generation reads committed Django storage files as text."""
        row = DashboardData.objects.create(
            dashboard_slug="field-file-dashboard",
            dashboard_title="Field file dashboard",
            source_file=SimpleUploadedFile(
                "data.csv",
                MINIMAL_SAMPLE_CSV,
                "text/csv",
            ),
        )
        result = generate_figures(SAMPLE_DASHBOARD_SLUG, row.source_file)

        self.assertIn("sample_chart", result)


class TestDashboardDataSaveIntegration(TestCase):
    """Tests for DashboardData save hook with viz service integration."""

    def test_data_updated_at_set_on_new_upload(self) -> None:
        """Test that a new source file sets data_updated_at to today."""
        source_file = SimpleUploadedFile("test.csv", b"a,b\n1,2\n", "text/csv")
        row = DashboardData.objects.create(
            dashboard_slug="test-dashboard",
            source_file=source_file,
            uploaded_by="testuser",
        )
        self.assertEqual(row.data_updated_at, date.today())

    def test_data_updated_at_updates_when_source_file_changes(self) -> None:
        """Test that replacing the source file refreshes data_updated_at to today."""
        source_file = SimpleUploadedFile("old.csv", b"a,b\n1,2\n", "text/csv")
        row = DashboardData.objects.create(
            dashboard_slug="test-dashboard",
            source_file=source_file,
            uploaded_by="testuser",
        )
        row.data_updated_at = date(2020, 1, 1)
        row.save(update_fields=["data_updated_at"])

        row.source_file = SimpleUploadedFile("new.csv", b"a,b\n3,4\n", "text/csv")
        row.save()
        row.refresh_from_db()

        self.assertEqual(row.data_updated_at, date.today())

    def test_data_updated_at_unchanged_without_file_change(self) -> None:
        """Test that saving other fields does not change data_updated_at."""
        source_file = SimpleUploadedFile("test.csv", b"a,b\n1,2\n", "text/csv")
        row = DashboardData.objects.create(
            dashboard_slug="test-dashboard",
            source_file=source_file,
            uploaded_by="testuser",
        )
        historic_date = date(2019, 5, 10)
        row.data_updated_at = historic_date
        row.save(update_fields=["data_updated_at"])

        row.uploaded_by = "another-editor"
        row.save(update_fields=["uploaded_by"])
        row.refresh_from_db()

        self.assertEqual(row.data_updated_at, historic_date)

    def test_save_with_no_registered_service_keeps_empty_data(self) -> None:
        """Test that saving with unregistered slug keeps data as empty dict."""
        csv_file = SimpleUploadedFile("test.csv", b"a,b\n1,2\n", "text/csv")
        row = DashboardData.objects.create(
            dashboard_slug="unregistered-dashboard",
            source_file=csv_file,
            uploaded_by="testuser",
        )
        self.assertEqual(row.data, {})
        self.assertEqual(len(row.source_file_hash), 64)

    @patch("dashboard_visualisation.generate_figures", return_value={"chart": {"data": []}})
    def test_regenerates_figures_when_file_changes_with_existing_data(
        self,
        mock_generate: object,
    ) -> None:
        """Test that figure JSON is regenerated when the source file hash changes."""
        row = DashboardData.objects.create(
            dashboard_slug="test-dashboard",
            source_file=SimpleUploadedFile("old.csv", b"a,b\n1,2\n", "text/csv"),
            data={"old_chart": {"data": [1]}},
            uploaded_by="testuser",
        )
        self.assertEqual(mock_generate.call_count, 1)

        row.source_file = SimpleUploadedFile("new.csv", b"x,y\n9,9\n", "text/csv")
        row.save()
        row.refresh_from_db()

        self.assertEqual(mock_generate.call_count, 2)
        self.assertEqual(row.data, {"chart": {"data": []}})

    @patch("dashboard_visualisation.generate_figures", return_value={"chart": {}})
    def test_does_not_regenerate_figures_without_file_change(
        self,
        mock_generate: object,
    ) -> None:
        """Test that saving other fields does not call generate_figures again."""
        row = DashboardData.objects.create(
            dashboard_slug="other-dashboard",
            source_file=SimpleUploadedFile("data.csv", b"a,b\n1,2\n", "text/csv"),
            uploaded_by="testuser",
        )
        self.assertEqual(mock_generate.call_count, 1)

        row.uploaded_by = "another-editor"
        row.save()
        self.assertEqual(mock_generate.call_count, 1)

    @patch("dashboard_visualisation.generate_figures", return_value={"chart": {"data": []}})
    def test_same_file_content_does_not_regenerate(
        self,
        mock_generate: object,
    ) -> None:
        """Test that re-uploading identical bytes does not regenerate figures."""
        content = b"date,class,count\n2024-01-01,positive,1\n"
        row = DashboardData.objects.create(
            dashboard_slug="same-content-dashboard",
            source_file=SimpleUploadedFile("npc.csv", content, "text/csv"),
            uploaded_by="testuser",
        )
        self.assertEqual(mock_generate.call_count, 1)
        historic_date = date(2020, 6, 1)
        row.data_updated_at = historic_date
        row.save(update_fields=["data_updated_at"])

        row = DashboardData.objects.get(pk=row.pk)
        row.source_file = SimpleUploadedFile("npc.csv", content, "text/csv")
        row.save()
        row.refresh_from_db()

        self.assertEqual(mock_generate.call_count, 1)
        self.assertEqual(row.data_updated_at, historic_date)

    @patch("dashboard_visualisation.generate_figures", return_value={"chart": {"data": []}})
    def test_file_change_persists_even_with_update_fields(
        self,
        mock_generate: object,
    ) -> None:
        """Test that regeneration is not dropped when save uses update_fields."""
        row = DashboardData.objects.create(
            dashboard_slug="update-fields-dashboard",
            source_file=SimpleUploadedFile("old.csv", b"a,b\n1,2\n", "text/csv"),
            data={"old_chart": {"data": [1]}},
            uploaded_by="testuser",
        )
        old_hash = row.source_file_hash
        self.assertEqual(mock_generate.call_count, 1)

        row.source_file = SimpleUploadedFile("new.csv", b"x,y\n9,9\n", "text/csv")
        row.save(update_fields=["uploaded_by"])
        row.refresh_from_db()

        self.assertEqual(mock_generate.call_count, 2)
        self.assertNotEqual(row.source_file_hash, old_hash)
        self.assertEqual(row.data_updated_at, date.today())
        self.assertEqual(row.data, {"chart": {"data": []}})

    def test_hash_uses_pending_upload_before_save(self) -> None:
        """Test that hashing detects a pending admin upload before it is stored."""
        content_v1 = b"date,class,count\n2024-01-01,positive,1\n"
        row = DashboardData.objects.create(
            dashboard_slug="pending-upload-dashboard",
            source_file=SimpleUploadedFile("npc.csv", content_v1, "text/csv"),
        )
        stored_hash = row.source_file_hash

        row = DashboardData.objects.get(pk=row.pk)
        row.source_file = SimpleUploadedFile(
            "npc.csv",
            b"date,class,count\n2024-01-01,positive,99\n",
            "text/csv",
        )
        pending_hash = calculate_file_hash(row.source_file)

        self.assertNotEqual(pending_hash, stored_hash)

    @patch("dashboard_visualisation.generate_figures", return_value={"chart": {"data": []}})
    def test_duplicate_reupload_sets_feedback_flag(
        self,
        mock_generate: object,
    ) -> None:
        """Test that re-uploading identical content is flagged for admin messaging."""
        content = b"date,class,count\n2024-01-01,positive,1\n"
        row = DashboardData.objects.create(
            dashboard_slug="duplicate-flag-dashboard",
            source_file=SimpleUploadedFile("npc.csv", content, "text/csv"),
            uploaded_by="testuser",
        )
        self.assertEqual(mock_generate.call_count, 1)

        row = DashboardData.objects.get(pk=row.pk)
        row.source_file = SimpleUploadedFile("npc.csv", content, "text/csv")
        row.save()

        self.assertEqual(mock_generate.call_count, 1)
        self.assertTrue(row._duplicate_source_upload)

    def test_latest_revision_save_preserves_duplicate_feedback(self) -> None:
        """Test that Wagtail revision bookkeeping does not clear upload feedback flags."""
        npc_csv = b"date,class,count\n2024-01-01,positive,1\n"
        row = DashboardData.objects.create(
            dashboard_slug="revision-feedback-dashboard",
            source_file=SimpleUploadedFile("npc.csv", npc_csv, "text/csv"),
        )
        row._duplicate_source_upload = True
        row.save(update_fields=["latest_revision"])

        self.assertTrue(row._duplicate_source_upload)

    @patch("dashboard_visualisation.generate_figures", side_effect=ValueError("invalid csv"))
    def test_regeneration_failure_reverts_data_updated_at(
        self,
        mock_generate: object,
    ) -> None:
        """Test that a failed regeneration does not change the public date."""
        row = DashboardData.objects.create(
            dashboard_slug="regen-fail-dashboard",
            source_file=SimpleUploadedFile("old.csv", b"a,b\n1,2\n", "text/csv"),
            uploaded_by="testuser",
        )
        historic_date = date(2018, 3, 15)
        row.data_updated_at = historic_date
        row.save(update_fields=["data_updated_at"])

        row.source_file = SimpleUploadedFile("bad.csv", b"broken", "text/csv")
        row.save()
        row.refresh_from_db()

        self.assertEqual(mock_generate.call_count, 2)
        self.assertEqual(row.data_updated_at, historic_date)
        self.assertEqual(row._regeneration_error, "invalid csv")


class TestDashboardDataAdminMessages(TestCase):
    """Tests for Wagtail admin save feedback messages."""

    def test_edit_view_disables_autosave(self) -> None:
        """Test that dashboard uploads are not saved until Save is clicked."""
        from django.contrib.auth import get_user_model
        from django.test import RequestFactory

        from cms.snippets.dashboard_data import DashboardDataEditView

        user_model = get_user_model()
        admin = user_model.objects.create_superuser(
            username="autosave-test",
            email="autosave@test.example",
            password="testpass",  # noqa: S106
        )
        row = DashboardData.objects.create(
            dashboard_slug="autosave-dashboard",
            dashboard_title="Autosave dashboard",
            source_file=SimpleUploadedFile(
                "npc.csv",
                b"date,class,count\n2024-01-01,positive,1\n",
                "text/csv",
            ),
        )

        request = RequestFactory().get(f"/wagtail/snippets/cms/dashboarddata/edit/{row.pk}/")
        request.user = admin
        view = DashboardDataEditView()
        view.model = DashboardData
        view.setup(request, pk=row.pk)

        self.assertTrue(view.revision_enabled)
        self.assertFalse(view.autosave_enabled)

    def test_duplicate_upload_shows_warning_message(self) -> None:
        """Test that duplicate uploads produce a clear admin warning."""
        from django.contrib.messages import get_messages
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.test import RequestFactory
        from wagtail.admin import messages as admin_messages

        request = RequestFactory().get("/")
        request.session = {}
        request._messages = FallbackStorage(request)

        row = DashboardData(dashboard_slug="duplicate-message-dashboard")
        row._duplicate_source_upload = True
        message, level = get_dashboard_data_save_feedback(row)
        self.assertIsNotNone(message)
        method = getattr(admin_messages, level, admin_messages.success)
        method(request, message)

        stored = list(get_messages(request))
        self.assertEqual(len(stored), 1)
        self.assertIn("identical", str(stored[0]).lower())

    def test_duplicate_upload_form_save_sets_feedback(self) -> None:
        """Test that duplicate uploads through the admin form surface feedback flags."""
        from wagtail.admin.panels import ObjectList

        from cms.snippets.dashboard_data import DashboardData, DashboardDataForm

        content = b"date,class,count\n2024-01-01,positive,1\n"
        row = DashboardData.objects.create(
            dashboard_slug="form-feedback-dashboard",
            dashboard_title="Form feedback dashboard",
            source_file=SimpleUploadedFile("npc.csv", content, "text/csv"),
        )

        form_class = ObjectList(DashboardData.panels).bind_to_model(DashboardData).get_form_class()
        self.assertTrue(issubclass(form_class, DashboardDataForm))
        form = form_class(
            instance=row,
            data={
                "dashboard_title": row.dashboard_title,
                "dashboard_slug": row.dashboard_slug,
                "data_updated_at": "2026-05-28",
                "data": "{}",
            },
            files={"source_file": SimpleUploadedFile("npc.csv", content, "text/csv")},
        )
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertTrue(saved._duplicate_source_upload)


class TestDashboardDataFormValidation(TestCase):
    """Tests for Wagtail admin form validation on source uploads."""

    def test_rejects_numbers_file_upload(self) -> None:
        """Test that .numbers files are rejected with an export hint."""
        from wagtail.admin.panels import ObjectList

        from cms.snippets.dashboard_data import DashboardData, DashboardDataForm

        csv_content = b"date,count,class\n2024-01-01,1,positive\n"
        row = DashboardData.objects.create(
            dashboard_slug="form-test-dashboard",
            source_file=SimpleUploadedFile("data.csv", csv_content, "text/csv"),
        )
        form_class = ObjectList(DashboardData.panels).bind_to_model(DashboardData).get_form_class()
        self.assertTrue(issubclass(form_class, DashboardDataForm))
        form = form_class(
            {
                "dashboard_title": row.dashboard_title,
                "dashboard_slug": row.dashboard_slug,
                "data": "{}",
                "data_updated_at": "",
            },
            {
                "source_file": SimpleUploadedFile(
                    "NPC-statistics-data-set.numbers",
                    b"not-a-real-numbers-file",
                    "application/vnd.apple.numbers",
                ),
            },
            instance=row,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("Export", str(form.errors["source_file"]))


class TestUploadedBy(TestCase):
    """Tests for recording the editor who uploaded source data."""

    def test_apply_uploaded_by_on_create(self) -> None:
        """Test that a new row records the authenticated admin username."""
        from django.contrib.auth import get_user_model
        from django.test import RequestFactory

        from cms.snippets.dashboard_data import DashboardData, apply_uploaded_by

        user_model = get_user_model()
        admin = user_model.objects.create_superuser(
            username="upload-editor",
            email="upload@test.example",
            password="testpass",  # noqa: S106
        )
        request = RequestFactory().post("/", {})
        request.user = admin

        row = DashboardData(dashboard_slug="upload-by-test")
        apply_uploaded_by(row, request)
        self.assertEqual(row.uploaded_by, "upload-editor")

    def test_apply_uploaded_by_on_reupload_only(self) -> None:
        """Test that uploaded_by updates when a new source file is posted."""
        from django.contrib.auth import get_user_model
        from django.test import RequestFactory

        from cms.snippets.dashboard_data import DashboardData, apply_uploaded_by

        user_model = get_user_model()
        admin = user_model.objects.create_superuser(
            username="reupload-editor",
            email="reupload@test.example",
            password="testpass",  # noqa: S106
        )
        csv_content = b"date,count,class\n2024-01-01,1,positive\n"
        row = DashboardData.objects.create(
            dashboard_slug="reupload-by-test",
            dashboard_title="Reupload test",
            uploaded_by="original-editor",
            source_file=SimpleUploadedFile("data.csv", csv_content, "text/csv"),
        )

        new_csv = b"date,count,class\n2024-01-02,2,negative\n"
        request = RequestFactory().post(
            "/",
            {"source_file": SimpleUploadedFile("new.csv", new_csv, "text/csv")},
        )
        request.user = admin
        apply_uploaded_by(row, request)
        self.assertEqual(row.uploaded_by, "reupload-editor")

    def test_apply_uploaded_by_skips_metadata_only_edit(self) -> None:
        """Test that uploaded_by is unchanged when no new file is uploaded."""
        from django.contrib.auth import get_user_model
        from django.test import RequestFactory

        from cms.snippets.dashboard_data import DashboardData, apply_uploaded_by

        user_model = get_user_model()
        admin = user_model.objects.create_superuser(
            username="metadata-editor",
            email="metadata@test.example",
            password="testpass",  # noqa: S106
        )
        csv_content = b"date,count,class\n2024-01-01,1,positive\n"
        row = DashboardData.objects.create(
            dashboard_slug="metadata-by-test",
            dashboard_title="Metadata test",
            uploaded_by="original-editor",
            source_file=SimpleUploadedFile("data.csv", csv_content, "text/csv"),
        )

        request = RequestFactory().post("/", {})
        request.user = admin
        apply_uploaded_by(row, request)
        self.assertEqual(row.uploaded_by, "original-editor")
