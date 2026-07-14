"""Dashboard data upload snippet."""

from __future__ import annotations

import structlog
from django.contrib.contenttypes.fields import GenericRelation
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.db import models
from django.shortcuts import redirect
from django.utils import timezone
from wagtail.admin import messages as admin_messages
from wagtail.admin.forms import WagtailAdminModelForm
from wagtail.admin.panels import FieldPanel, MultiFieldPanel
from wagtail.models import RevisionMixin
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import CreateView, EditView, SnippetViewSet

from dashboard_visualisation.registry import validate_source_columns
from dashboard_visualisation.liver_resource.dashboard_figures import LIVER_DASHBOARD_SLUG
from dashboard_visualisation.utils.uploads import (
    calculate_file_hash,
    rewind_source_file,
    validate_csv,
)

LOGGER = structlog.get_logger(__name__)

_SKIP_FILE_HOOK_ATTR = "_dashboard_data_skip_file_hook"
_UNSUPPORTED_SOURCE_EXTENSIONS = {".numbers", ".xlsx", ".xls", ".ods"}
_LIVER_SOURCE_EXTENSIONS = {".txt", ".tsv", ".csv"}


def _is_new_source_file_upload(source_file: object) -> bool:
    """Return True when the admin form attached a new upload for this save."""
    if not source_file:
        return False
    if isinstance(source_file, UploadedFile):
        return True
    if hasattr(source_file, "_committed"):
        return not source_file._committed
    return False


class DashboardDataForm(WagtailAdminModelForm):
    """Validate dashboard source uploads before save."""

    def clean_source_file(self) -> object:
        """Reject non-CSV uploads and validate readable source CSV."""
        source_file = self.cleaned_data.get("source_file")
        if not source_file:
            return source_file

        name = getattr(source_file, "name", "") or ""
        extension = name[name.rfind(".") :].lower() if "." in name else ""
        if extension in _UNSUPPORTED_SOURCE_EXTENSIONS:
            raise ValidationError(
                f'"{name}" cannot be used directly. Export the spreadsheet as CSV '
                "(File → Export To → CSV in Numbers/Excel) and upload the .csv file."
            )

        if not _is_new_source_file_upload(source_file):
            return source_file

        dashboard_slug = self.cleaned_data.get("dashboard_slug") or getattr(
            self.instance, "dashboard_slug", ""
        )

        if dashboard_slug == LIVER_DASHBOARD_SLUG:
            if extension and extension not in _LIVER_SOURCE_EXTENSIONS:
                raise ValidationError(
                    f'"{name}" is not supported for the liver dashboard. '
                    "Upload a tab- or comma-separated limma DE file (.txt, .tsv, or .csv)."
                )
            from dashboard_visualisation.liver_resource.validators import validate_de_upload

            size_bytes = getattr(source_file, "size", None)
            result = validate_de_upload(source_file, size_bytes=size_bytes)
            if not result.is_valid:
                raise ValidationError(result.errors[0])
            return source_file

        result = validate_csv(source_file)
        if not result.is_valid:
            raise ValidationError(result.errors[0])

        if column_error := validate_source_columns(dashboard_slug, result.columns):
            raise ValidationError(column_error)

        return source_file

    def save(self, commit: bool = True) -> DashboardData:
        """Mark pending uploads before Django commits the file to storage."""
        if self.files.get("source_file"):
            self.instance._pending_source_upload = True
        return super().save(commit=commit)


class DashboardData(RevisionMixin, models.Model):
    """Stores uploaded data and pre-computed Plotly figures for a dashboard.

    One row per dashboard (``dashboard_slug`` is unique). Wagtail revisions
    (via ``RevisionMixin``) provide history and rollback instead of duplicate rows.

    Attributes:
        dashboard_title: Human-readable title for admin display.
        dashboard_slug: Unique identifier matching the dashboard page slug.
        source_file: The uploaded source data file (CSV, Excel, etc.), stored
            for visitor download and re-generation of figures when viz scripts change.
        source_file_hash: SHA-256 of ``source_file``; used to detect file changes.
        data: Pre-computed Plotly figure JSON keyed by figure_id.
        data_updated_at: Public-facing date for when the underlying data was last updated.
            Set automatically to today when ``source_file`` changes; editors can override.
        uploaded_by: Username of the editor who uploaded.
    """

    dashboard_title = models.CharField(
        max_length=255,
        default="",
        help_text="Human-readable dashboard name for admin display.",
    )
    dashboard_slug = models.SlugField(
        max_length=255,
        unique=True,
        help_text="Must match the dashboard page slug. One data upload per dashboard.",
    )
    source_file = models.FileField(upload_to="dashboard_data/")
    source_file_hash = models.CharField(max_length=64, blank=True, editable=False)
    data = models.JSONField(default=dict, blank=True)
    data_updated_at = models.DateField(
        null=True,
        blank=True,
        help_text=(
            "Date shown on the public dashboard as when the underlying data was last updated. "
            "Updates automatically to today when the source file is replaced; you can override "
            "manually (e.g. historic migration date)."
        ),
    )
    uploaded_by = models.CharField(max_length=255, blank=True)
    revisions = GenericRelation("wagtailcore.Revision", related_query_name="dashboarddata")
    base_form_class = DashboardDataForm

    panels = [
        MultiFieldPanel(
            [
                FieldPanel("dashboard_title"),
                FieldPanel("dashboard_slug"),
            ],
            heading="Dashboard",
        ),
        FieldPanel(
            "source_file",
            help_text=(
                "Source data file for this dashboard. Upload CSV only "
                "(export from Numbers/Excel as CSV — .numbers files are not supported)."
            ),
        ),
        FieldPanel("data_updated_at"),
        FieldPanel(
            "data",
            help_text=(
                "Pre-computed Plotly figure JSON keyed by figure_id. "
                "Auto-regenerated when the source file changes, "
                "or paste JSON directly for historic dashboards."
            ),
        ),
    ]

    class Meta:
        """Settings for the DashboardData model."""

        ordering = ["dashboard_slug"]
        verbose_name = "Dashboard data upload"
        verbose_name_plural = "Dashboard data uploads"

    def __str__(self) -> str:
        """Return the admin display label for this upload."""
        return self.dashboard_title or self.dashboard_slug

    def save(self, *args: object, **kwargs: object) -> None:
        """Persist the row and regenerate figures when the source file changes."""
        if getattr(self, _SKIP_FILE_HOOK_ATTR, False):
            return super().save(*args, **kwargs)

        update_fields = kwargs.get("update_fields")
        if update_fields is not None and set(update_fields).issubset({"latest_revision"}):
            return super().save(*args, **kwargs)

        self._clear_save_feedback()
        file_changed = False
        duplicate_upload = False
        original_date = self.data_updated_at

        if self.source_file:
            rewind_source_file(self.source_file)
            new_hash = calculate_file_hash(self.source_file)
            new_upload = getattr(
                self, "_pending_source_upload", False
            ) or _is_new_source_file_upload(self.source_file)
            if hasattr(self, "_pending_source_upload"):
                delattr(self, "_pending_source_upload")

            file_changed = not self.pk
            if self.pk:
                row = (
                    type(self)
                    .objects.filter(pk=self.pk)
                    .only(
                        "source_file_hash",
                        "data_updated_at",
                    )
                    .first()
                )
                old_hash = row.source_file_hash if row else None
                if original_date is None and row is not None:
                    original_date = row.data_updated_at
                file_changed = old_hash != new_hash
                duplicate_upload = new_upload and not file_changed

            self.source_file_hash = new_hash

        if file_changed:
            kwargs.pop("update_fields", None)
            super().save(*args, **kwargs)

            try:
                self._regenerate_figures_from_storage(original_date)
            except (FileNotFoundError, ValueError, OSError, TypeError, KeyError) as exc:
                self._regeneration_error = str(exc)
                self.data_updated_at = original_date
                LOGGER.warning(
                    "dashboard_data.generate_figures_failed",
                    dashboard_slug=self.dashboard_slug,
                    error=str(exc),
                    exc_info=True,
                )

            setattr(self, _SKIP_FILE_HOOK_ATTR, True)
            try:
                super().save(update_fields=["data", "data_updated_at"])
            finally:
                delattr(self, _SKIP_FILE_HOOK_ATTR)
            return

        if duplicate_upload:
            self._duplicate_source_upload = True
            LOGGER.info(
                "dashboard_data.duplicate_source_upload",
                dashboard_slug=self.dashboard_slug,
                source_file_hash=self.source_file_hash,
            )

        super().save(*args, **kwargs)

    @classmethod
    def get_data(cls, dashboard_slug: str) -> DashboardData | None:
        """Return the dashboard data row for a slug, or None."""
        try:
            return cls.objects.get(dashboard_slug=dashboard_slug)
        except cls.DoesNotExist:
            return None

    def _clear_save_feedback(self) -> None:
        for attr in (
            "_duplicate_source_upload",
            "_regenerated_figure_count",
            "_regeneration_error",
            "_regeneration_empty",
        ):
            if hasattr(self, attr):
                delattr(self, attr)

    def _regenerate_figures_from_storage(self, original_date: object) -> None:
        """Generate figures from the committed source file and update ``data``."""
        from dashboard_visualisation import generate_figures

        self.refresh_from_db(fields=["source_file", "source_file_hash", "dashboard_slug"])
        rewind_source_file(self.source_file)

        LOGGER.info(
            "dashboard_data.regenerating_figures",
            dashboard_slug=self.dashboard_slug,
            source_file_hash=self.source_file_hash,
        )
        figures = generate_figures(self.dashboard_slug, self.source_file)
        self.data = figures or {}
        self.data_updated_at = timezone.localdate()
        self._regenerated_figure_count = len(self.data)
        if not self.data:
            self._regeneration_empty = True
            LOGGER.warning(
                "dashboard_data.regeneration_empty",
                dashboard_slug=self.dashboard_slug,
            )


def get_dashboard_data_save_feedback(instance: DashboardData) -> tuple[str | None, str]:
    """Return custom admin feedback text and Wagtail message level, if any."""
    if getattr(instance, "_duplicate_source_upload", False):
        return (
            "Source file was not updated because the uploaded file is identical to the "
            "current one. Figures and the data-updated date were left unchanged.",
            "warning",
        )

    if error := getattr(instance, "_regeneration_error", None):
        return (
            "The source file was saved but figure generation failed: "
            f"{error}. The data-updated date was not changed.",
            "error",
        )

    if getattr(instance, "_regeneration_empty", False):
        return (
            "The source file was saved but no figures were generated "
            f'(no viz service registered for slug "{instance.dashboard_slug}").',
            "warning",
        )

    count = getattr(instance, "_regenerated_figure_count", None)
    if count is not None:
        return (
            f"Source file updated. Regenerated {count} figure(s) and set the "
            "data-updated date to today.",
            "success",
        )

    return None, "success"


def apply_uploaded_by(instance: DashboardData, request: object) -> None:
    """Set ``uploaded_by`` from the admin user when creating or replacing the source file."""
    user = getattr(request, "user", None)
    if not user or not getattr(user, "is_authenticated", False):
        return

    is_create = instance.pk is None
    has_new_file = bool(getattr(request, "FILES", {}).get("source_file"))
    if is_create or has_new_file:
        instance.uploaded_by = user.get_username()


class DashboardDataUploadedByMixin:
    """Record which editor uploaded (or re-uploaded) the source file."""

    def save_instance(self) -> object:
        """Set ``uploaded_by`` on the snippet before Wagtail persists it."""
        apply_uploaded_by(self.form.instance, self.request)
        return super().save_instance()


class DashboardDataNoAutosaveMixin:
    """Disable Wagtail autosave for dashboard data uploads.

    ``RevisionMixin`` enables autosave by default. That would persist source
    file changes and regenerate figures as soon as a file is selected, before
    the editor clicks Save.
    """

    def setup(self, request: object, *args: object, **kwargs: object) -> None:
        """Disable autosave so file uploads are not saved until Save is clicked."""
        super().setup(request, *args, **kwargs)
        self.autosave_enabled = False


class DashboardDataSnippetSaveMessagesMixin:
    """Mixin for snippet create/edit views that surfaces upload feedback."""

    def save_action(self) -> object:
        """Show upload/regeneration feedback instead of the default success message."""
        message, level = get_dashboard_data_save_feedback(self.object)
        if message is not None:
            method = getattr(admin_messages, level, admin_messages.success)
            buttons = self.get_success_buttons() if level == "success" else None
            method(self.request, message, buttons=buttons)
            return redirect(self.get_success_url())
        return super().save_action()


class DashboardDataCreateView(
    DashboardDataUploadedByMixin,
    DashboardDataNoAutosaveMixin,
    DashboardDataSnippetSaveMessagesMixin,
    CreateView,
):
    """Create view with dashboard upload feedback."""


class DashboardDataEditView(
    DashboardDataUploadedByMixin,
    DashboardDataNoAutosaveMixin,
    DashboardDataSnippetSaveMessagesMixin,
    EditView,
):
    """Edit view with dashboard upload feedback."""


class DashboardDataViewSet(SnippetViewSet):
    """Wagtail admin viewset for the Dashboard Data Upload snippet."""

    model = DashboardData
    icon = "doc-full-inverse"
    menu_label = "Dashboard Data Upload"
    menu_name = "dashboard-data-upload"
    ordering = ["dashboard_slug"]
    add_view_class = DashboardDataCreateView
    edit_view_class = DashboardDataEditView
    list_display = [
        "dashboard_title",
        "dashboard_slug",
        "data_updated_at",
        "uploaded_by",
    ]
    list_filter = ["dashboard_slug"]


register_snippet(DashboardDataViewSet)
