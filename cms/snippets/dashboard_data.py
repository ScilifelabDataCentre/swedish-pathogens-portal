"""Dashboard data upload snippet."""

from __future__ import annotations

from collections.abc import Callable, Collection
from typing import TYPE_CHECKING

import structlog
from django.contrib.contenttypes.fields import GenericRelation
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.db import models
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.functional import cached_property
from wagtail.admin import messages as admin_messages
from wagtail.admin.auth import user_passes_test
from wagtail.admin.forms import WagtailAdminModelForm
from wagtail.admin.panels import FieldPanel, MultiFieldPanel, ObjectList, Panel
from wagtail.admin.ui.components import MediaContainer
from wagtail.admin.ui.tables import BaseColumn, BulkActionsCheckboxColumn
from wagtail.models import RevisionMixin
from wagtail.permission_policies import ModelPermissionPolicy
from wagtail.permissions import register_permission_policy
from wagtail.snippets.bulk_actions.delete import DeleteBulkAction
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.chooser import SnippetChooserViewSet
from wagtail.snippets.views.snippets import (
    CreateView,
    EditView,
    HistoryView,
    IndexView,
    RevisionsCompareView,
    SnippetViewSet,
    UsageView,
)

from dashboard_visualisation.registry import validate_source_columns, validate_source_file
from dashboard_visualisation.utils.uploads import (
    calculate_file_hash,
    rewind_source_file,
    validate_csv,
)

if TYPE_CHECKING:
    from django.contrib.auth.models import User

LOGGER = structlog.get_logger(__name__)

_SKIP_FILE_HOOK_ATTR = "_dashboard_data_skip_file_hook"
_UNSUPPORTED_SOURCE_EXTENSIONS = {".numbers", ".xlsx", ".xls", ".ods"}
_SOURCE_FILE_HELP_TEXT = (
    "Source data file for this dashboard. Upload CSV only "
    "(export from Numbers/Excel as CSV — .numbers files are not supported)."
)


def _is_new_source_file_upload(source_file: object) -> bool:
    """Return True when the admin form attached a new upload for this save."""
    if not source_file:
        return False
    if isinstance(source_file, UploadedFile):
        return True
    if hasattr(source_file, "_committed"):
        return not source_file._committed
    return False


def _is_internal_user(user: User | None) -> bool:
    """Return True if the user is a superuser or belongs to the 'editors' group."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    return user.is_superuser or user.groups.filter(name="Editors").exists()


def _user_can_access_dashboard_data(user: User | None, obj: DashboardData) -> bool:
    if _is_internal_user(user):
        return True
    return bool(
        user is not None
        and user.is_authenticated
        and obj.research_group_id
        and user.groups.filter(pk=obj.research_group_id).exists()
    )


class DashboardDataForm(WagtailAdminModelForm):
    """Validate dashboard source uploads before save."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        """Limit researchers to replacing the source file, including on POST."""
        super().__init__(*args, **kwargs)

        for_user = kwargs.get("for_user")
        if not _is_internal_user(for_user):
            self.fields = {
                name: field for name, field in self.fields.items() if name == "source_file"
            }

    def clean_source_file(self) -> object:
        """Validate the source upload (custom viz-module checks, else CSV)."""
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

        handled, file_error = validate_source_file(
            dashboard_slug,
            source_file,
            filename=name,
            size_bytes=getattr(source_file, "size", None),
        )
        if handled:
            if file_error:
                raise ValidationError(file_error)
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

    research_group = models.ForeignKey(
        "auth.Group",
        on_delete=models.PROTECT,
        related_name="+",
        blank=True,
        null=True,
        help_text=(
            "Optional admin setting to restrict access to this dashboard data upload "
            "to a specific research group."
        ),
    )
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
                FieldPanel("research_group"),
            ],
            heading="Dashboard",
        ),
        FieldPanel(
            "source_file",
            help_text=_SOURCE_FILE_HELP_TEXT,
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

    researcher_panels = [
        FieldPanel("dashboard_title", read_only=True),
        FieldPanel("source_file", help_text=_SOURCE_FILE_HELP_TEXT),
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


def get_dashboard_data_save_feedback(
    instance: DashboardData, *, include_internal_details: bool = True
) -> tuple[str | None, str]:
    """Return custom admin feedback text and Wagtail message level, if any."""
    if getattr(instance, "_duplicate_source_upload", False):
        return (
            "Source file was not updated because the uploaded file is identical to the "
            "current one. Figures and the data-updated date were left unchanged.",
            "warning",
        )

    if error := getattr(instance, "_regeneration_error", None):
        if not include_internal_details:
            return (
                "The source file was saved but figure generation failed. "
                "The data-updated date was not changed. Please contact an editor.",
                "error",
            )
        return (
            "The source file was saved but figure generation failed: "
            f"{error}. The data-updated date was not changed.",
            "error",
        )

    if getattr(instance, "_regeneration_empty", False):
        if not include_internal_details:
            return (
                "The source file was saved but no figures were generated. "
                "Please contact an editor to check the dashboard configuration.",
                "warning",
            )
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


class DashboardDataObjectPermissionMixin:
    """Mixin for snippet views that checks object-level permissions."""

    def get_object(self, *args: object, **kwargs: object) -> DashboardData:
        """Return the object, or raise PermissionDenied if the user cannot access it."""
        obj = super().get_object(*args, **kwargs)
        live_obj = getattr(self, "live_object", obj)
        if not _user_can_access_dashboard_data(self.request.user, live_obj):
            raise PermissionDenied
        return obj


class DashboardDataPermissionPolicy(ModelPermissionPolicy):
    """Keep researchers edit-only and restrict objects to their assigned groups.

    Register this policy centrally so snippet actions, menus, and bulk actions
    all apply the same restrictions, including when extra permissions are granted.
    """

    def user_has_permission(self, user: User, action: str) -> bool:
        """Require Django permissions and reserve administrative actions for editors."""
        if not _is_internal_user(user) and action not in {"change", "view"}:
            return False
        return super().user_has_permission(user, action)

    def user_has_permission_for_instance(
        self, user: User, action: str, instance: DashboardData
    ) -> bool:
        """Also require membership in the upload's assigned research group."""
        return self.user_has_permission(user, action) and _user_can_access_dashboard_data(
            user, instance
        )

    def instances_user_has_any_permission_for(
        self, user: User, actions: Collection[str]
    ) -> models.QuerySet:
        """Return only the uploads the user may access."""
        queryset = super().instances_user_has_any_permission_for(user, actions)
        if _is_internal_user(user):
            return queryset
        return queryset.filter(research_group__in=user.groups.all())

    def users_with_any_permission(self, actions: Collection[str]) -> models.QuerySet:
        """Apply the role restriction when Wagtail looks up permitted users."""
        researcher_actions = set(actions) & {"change", "view"}
        researchers = super().users_with_any_permission(researcher_actions)
        return (
            super()
            .users_with_any_permission(actions)
            .filter(
                models.Q(is_superuser=True)
                | models.Q(groups__name="Editors")
                | models.Q(pk__in=researchers)
            )
            .distinct()
        )

    def users_with_any_permission_for_instance(
        self, actions: Collection[str], instance: DashboardData
    ) -> models.QuerySet:
        """Restrict user lookups to internal staff and the assigned group."""
        allowed = models.Q(is_superuser=True) | models.Q(groups__name="Editors")
        if instance.research_group_id:
            allowed |= models.Q(groups__pk=instance.research_group_id)
        return self.users_with_any_permission(actions).filter(allowed).distinct()


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
        message, level = get_dashboard_data_save_feedback(
            self.object, include_internal_details=_is_internal_user(self.request.user)
        )
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
    DashboardDataObjectPermissionMixin,
    DashboardDataUploadedByMixin,
    DashboardDataNoAutosaveMixin,
    DashboardDataSnippetSaveMessagesMixin,
    EditView,
):
    """Edit view with dashboard upload feedback."""

    def setup(self, request: HttpRequest, *args: object, **kwargs: object) -> None:
        """Keep researcher saves from overwriting historical revisions."""
        if not _is_internal_user(request.user):
            if request.POST.get("overwrite_revision_id"):
                raise PermissionDenied
            self.history_url_name = None
            self.usage_url_name = None
        super().setup(request, *args, **kwargs)

    def get_panel(self) -> Panel:
        """Choose the upload-only editor without changing the shared panels."""
        if _is_internal_user(self.request.user):
            return super().get_panel()
        return ObjectList(self.model.researcher_panels).bind_to_model(self.model)

    def get_form_class(self) -> type[WagtailAdminModelForm]:
        """Use the researcher panel's form instead of the viewset's full form."""
        if _is_internal_user(self.request.user):
            return super().get_form_class()
        return self.panel.get_form_class()

    def get_side_panels(self) -> MediaContainer:
        """Keep administrative history and usage controls out of the upload screen."""
        if _is_internal_user(self.request.user):
            return super().get_side_panels()
        return MediaContainer([])

    def get_page_subtitle(self) -> str:
        """Use the configured title rather than a slug fallback for researchers."""
        if _is_internal_user(self.request.user):
            return super().get_page_subtitle()
        return self.object.dashboard_title

    def get_success_message(self) -> str:
        """Keep the default save message free of internal identifiers."""
        if _is_internal_user(self.request.user):
            return super().get_success_message()
        return "Dashboard data upload saved."


class DashboardDataHistoryView(
    DashboardDataObjectPermissionMixin,
    HistoryView,
):
    """History view with object-level permission checks."""


class DashboardDataRevisionsCompareView(
    DashboardDataObjectPermissionMixin,
    RevisionsCompareView,
):
    """Revision comparison view with object-level permission checks."""


class DashboardDataUsageView(
    DashboardDataObjectPermissionMixin,
    UsageView,
):
    """Usage view with object-level permission checks."""


class DashboardDataIndexView(IndexView):
    """Show researchers their dashboard titles and data-updated dates."""

    def setup(self, request: HttpRequest, *args: object, **kwargs: object) -> None:
        """Limit this request's columns, filters, and ordering before they are cached."""
        if not _is_internal_user(request.user):
            self.list_display = ["dashboard_title", "data_updated_at"]
            self.list_filter = []
            self.filterset_class = None
            self.default_ordering = ["dashboard_title", "pk"]
        super().setup(request, *args, **kwargs)

    @cached_property
    def columns(self) -> list[BaseColumn]:
        """Remove selection checkboxes when there are no permitted bulk actions."""
        columns = super().columns
        if _is_internal_user(self.request.user):
            return columns
        return [column for column in columns if not isinstance(column, BulkActionsCheckboxColumn)]

    def get_list_buttons(self, instance: DashboardData) -> list:
        """Researchers open uploads through their title links only."""
        if _is_internal_user(self.request.user):
            return super().get_list_buttons(instance)
        return []


class DashboardDataChooserViewSet(SnippetChooserViewSet):
    """Reserve all chooser endpoints for internal dashboard configuration."""

    def construct_view(self, view_class: type, **kwargs: object) -> Callable[..., HttpResponse]:
        """Guard listing, single/multiple selections, and chooser creation alike."""
        return user_passes_test(_is_internal_user)(super().construct_view(view_class, **kwargs))


class DashboardDataDeleteBulkAction(DeleteBulkAction):
    """Reject researcher bulk requests before any object details are rendered."""

    models = [DashboardData]

    def dispatch(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        """Reserve dashboard bulk deletion for internal users."""
        if not _is_internal_user(request.user):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class DashboardDataViewSet(SnippetViewSet):
    """Wagtail admin viewset for the Dashboard Data Upload snippet."""

    model = DashboardData
    icon = "doc-full-inverse"
    menu_label = "Dashboard Data Upload"
    menu_name = "dashboard-data-upload"
    ordering = ["dashboard_slug"]
    index_view_class = DashboardDataIndexView
    add_view_class = DashboardDataCreateView
    edit_view_class = DashboardDataEditView
    history_view_class = DashboardDataHistoryView
    revisions_compare_view_class = DashboardDataRevisionsCompareView
    usage_view_class = DashboardDataUsageView
    chooser_viewset_class = DashboardDataChooserViewSet
    list_display = [
        "dashboard_title",
        "dashboard_slug",
        "data_updated_at",
        "uploaded_by",
    ]
    list_filter = ["dashboard_slug"]

    def construct_view(self, view_class: type, **kwargs: object) -> Callable[..., HttpResponse]:
        """Expose only the listing and current upload editor to researchers.

        Wagtail creates restoration views dynamically from the edit view. Check
        view_name so these cannot inherit researcher access to the current row.
        """
        view = super().construct_view(view_class, **kwargs)
        if getattr(view_class, "view_name", None) in {"list", "edit"}:
            return view
        return user_passes_test(_is_internal_user)(view)

    def get_queryset(self, request: HttpRequest) -> models.QuerySet:
        """Return a queryset of DashboardData instances based on the user's permissions."""
        queryset = self.model.objects.all()

        user = request.user
        if _is_internal_user(user):
            return queryset

        return queryset.filter(research_group__in=user.groups.all())


register_permission_policy(DashboardData, DashboardDataPermissionPolicy(DashboardData))
register_snippet(DashboardDataViewSet)
