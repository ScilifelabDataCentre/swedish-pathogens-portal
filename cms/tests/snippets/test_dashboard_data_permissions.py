"""Request-level coverage of the researcher dashboard upload workflow."""

from datetime import date
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser, Group, Permission, User
from django.contrib.messages import get_messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from wagtail.admin.panels import ObjectList
from wagtail.permissions import policy_registry

from cms.snippets.dashboard_data import DashboardData


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class DashboardDataResearcherTests(TestCase):
    """Exercise real Wagtail routes, forms, revisions, and upload persistence."""

    namespace = "wagtailsnippets_cms_dashboarddata"
    chooser_namespace = "wagtailsnippetchoosers_cms_dashboarddata"
    original_file = b"date,value\n2024-01-01,10\n"
    replacement_file = b"date,value\n2024-01-01,20\n"
    old_figures = {"private_figure_key": {"data": [{"y": [10]}]}}
    new_figures = {"private_figure_key": {"data": [{"y": [20]}]}}

    @classmethod
    def setUpTestData(cls) -> None:
        """Provision titled uploads exactly as internal editors hand them over."""
        cls.group = Group.objects.create(name="Research group A")
        cls.other_group = Group.objects.create(name="Research group B")
        cls.editors = Group.objects.get(name="Editors")
        cls.permissions = Permission.objects.filter(
            content_type__app_label="cms", content_type__model="dashboarddata"
        )
        access_admin = Permission.objects.get(
            content_type__app_label="wagtailadmin", codename="access_admin"
        )
        cls.group.permissions.add(
            access_admin, cls.permissions.get(codename="change_dashboarddata")
        )
        cls.editors.permissions.add(access_admin, *cls.permissions)
        cls.researcher = User.objects.create_user(username="researcher")
        cls.researcher.groups.add(cls.group)
        cls.editor = User.objects.create_user(username="editor")
        cls.editor.groups.add(cls.editors)
        cls.superuser = User.objects.create_superuser(username="internal-admin")
        cls.no_permission = User.objects.create_user(username="no-snippet-permission")
        cls.no_permission.user_permissions.add(access_admin)

        with patch("dashboard_visualisation.generate_figures", return_value=cls.old_figures):
            cls.own = DashboardData.objects.create(
                dashboard_title="Zebra dashboard",
                dashboard_slug="private-own-slug",
                research_group=cls.group,
                source_file=SimpleUploadedFile("original.csv", cls.original_file),
                uploaded_by="internal-admin",
            )
            cls.other = DashboardData.objects.create(
                dashboard_title="Alpha dashboard",
                dashboard_slug="private-other-slug",
                research_group=cls.other_group,
                source_file=SimpleUploadedFile("other.csv", cls.original_file),
            )
            cls.unassigned = DashboardData.objects.create(
                dashboard_title="Unassigned dashboard",
                dashboard_slug="private-unassigned-slug",
                source_file=SimpleUploadedFile("unassigned.csv", cls.original_file),
            )
        DashboardData.objects.filter(pk=cls.own.pk).update(data_updated_at=date(2024, 1, 1))
        cls.own.refresh_from_db()
        cls.first_revision = cls.own.save_revision(user=cls.superuser)
        cls.own.data = cls.new_figures
        cls.own.save(update_fields=["data"])
        cls.latest_revision = cls.own.save_revision(user=cls.superuser)

    def setUp(self) -> None:
        """Start each request as a researcher with change permission only."""
        self.client.force_login(self.researcher)

    def url(self, name: str, *args: object) -> str:
        """Reverse a dashboard snippet route."""
        return reverse(f"{self.namespace}:{name}", args=args)

    def assert_denied(self, response: object) -> None:
        """Check Wagtail's standard denial redirect and absence of protected content."""
        self.assertRedirects(response, reverse("wagtailadmin_home"), fetch_redirect_response=False)
        self.assertNotContains(response, "private_", status_code=302)
        self.assertNotContains(response, self.other.dashboard_title, status_code=302)

    def test_listing_and_results_show_only_assigned_titles_and_dates(self) -> None:
        """Both listing endpoints hide slugs, uploader details, filters, and actions."""
        for route in ("list", "list_results"):
            with self.subTest(route=route):
                response = self.client.get(self.url(route))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, self.own.dashboard_title)
                self.assertContains(response, "Data updated at")
                self.assertNotContains(response, self.other.dashboard_title)
                self.assertNotContains(response, self.unassigned.dashboard_title)
                self.assertNotContains(response, "dashboard_slug")
                self.assertNotContains(response, self.own.dashboard_slug)
                self.assertNotContains(response, "Uploaded by")
                self.assertNotContains(response, 'name="id"')
                self.assertNotContains(response, self.url("add"))
                self.assertNotContains(response, self.url("copy", self.own.pk))
                self.assertNotContains(response, self.url("delete", self.own.pk))

    def test_edit_has_read_only_title_and_only_source_file_input(self) -> None:
        """Hidden fields are absent from both the form and serialized panel data."""
        response = self.client.get(self.url("edit", self.own.pk))
        self.assertEqual(set(response.context["form"].fields), {"source_file"})
        self.assertContains(response, self.own.dashboard_title)
        self.assertNotContains(response, 'name="dashboard_title"')
        for hidden in ("dashboard_slug", "research_group", "data_updated_at", "private_figure_key"):
            self.assertNotContains(response, hidden)
        self.assertNotContains(response, 'name="data"')
        self.assertNotContains(response, self.own.dashboard_slug)
        self.assertNotContains(response, self.url("history", self.own.pk))
        self.assertNotContains(response, self.url("usage", self.own.pk))
        self.assertTrue(response.context["revision_enabled"])
        self.assertFalse(response.context["autosave_enabled"])

    def test_forged_fields_do_not_change_protected_metadata_or_figures(self) -> None:
        """Only an actual source upload may trigger generated metadata changes."""
        before = DashboardData.objects.values().get(pk=self.own.pk)
        response = self.client.post(
            self.url("edit", self.own.pk),
            {
                "dashboard_title": "Forged title",
                "dashboard_slug": "forged-slug",
                "research_group": self.other_group.pk,
                "data_updated_at": "1999-01-01",
                "data": '{"forged": true}',
                "uploaded_by": "forged-uploader",
                "source_file_hash": "forged-hash",
            },
        )
        self.assertRedirects(response, self.url("list"), fetch_redirect_response=False)
        after = DashboardData.objects.values().get(pk=self.own.pk)
        for field in before.keys() - {"latest_revision_id"}:
            self.assertEqual(after[field], before[field], field)
        self.assertEqual(self.own.revisions.count(), 3)

    def test_new_upload_uses_stored_slug_and_updates_generated_fields(self) -> None:
        """Validation and generation use the assigned dashboard, despite forged fields."""
        with (
            patch(
                "cms.snippets.dashboard_data.validate_source_file", return_value=(False, None)
            ) as validate,
            patch("dashboard_visualisation.generate_figures", return_value=self.old_figures) as gen,
        ):
            response = self.client.post(
                self.url("edit", self.own.pk),
                {
                    "source_file": SimpleUploadedFile("replacement.csv", self.replacement_file),
                    "dashboard_slug": "forged-slug",
                    "data_updated_at": "1999-01-01",
                    "data": '{"forged": true}',
                },
            )
        self.assertRedirects(response, self.url("list"), fetch_redirect_response=False)
        self.assertEqual(validate.call_args.args[0], self.own.dashboard_slug)
        self.assertEqual(gen.call_args.args[0], self.own.dashboard_slug)
        self.own.refresh_from_db()
        self.assertEqual(self.own.data, self.old_figures)
        self.assertEqual(self.own.dashboard_slug, "private-own-slug")
        self.assertEqual(self.own.data_updated_at, timezone.localdate())
        self.assertEqual(self.own.uploaded_by, self.researcher.username)
        self.assertNotEqual(
            self.own.source_file_hash, self.first_revision.content["source_file_hash"]
        )
        self.assertEqual(self.own.revisions.count(), 3)
        self.assertEqual(self.own.latest_revision.content["data"], self.old_figures)

    def test_invalid_file_does_not_save_or_create_revision(self) -> None:
        """A failed validation leaves the live upload and history intact."""
        original = DashboardData.objects.values().get(pk=self.own.pk)
        response = self.client.post(
            self.url("edit", self.own.pk),
            {"source_file": SimpleUploadedFile("invalid.numbers", b"invalid")},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Export")
        self.assertEqual(DashboardData.objects.values().get(pk=self.own.pk), original)
        self.assertEqual(self.own.revisions.count(), 2)
        self.assertNotContains(response, self.own.dashboard_slug)

    def test_duplicate_upload_preserves_figures_and_date(self) -> None:
        """The duplicate warning is retained without revealing internal identifiers."""
        with patch("dashboard_visualisation.generate_figures") as gen:
            response = self.client.post(
                self.url("edit", self.own.pk),
                {"source_file": SimpleUploadedFile("duplicate.csv", self.original_file)},
            )
        gen.assert_not_called()
        self.own.refresh_from_db()
        self.assertEqual(self.own.data, self.new_figures)
        self.assertEqual(self.own.data_updated_at, date(2024, 1, 1))
        self.assertEqual(self.own.uploaded_by, self.researcher.username)
        messages = " ".join(str(message) for message in get_messages(response.wsgi_request))
        self.assertIn("identical", messages)

    def test_generation_failure_and_empty_result_have_safe_feedback(self) -> None:
        """Keep detailed diagnostics for editors and report actionable outcomes to researchers."""
        cases = (
            (ValueError("private-own-slug private_figure_key"), "generation failed"),
            ({}, "no figures were generated"),
        )
        for result, expected in cases:
            with (
                self.subTest(result=result),
                patch("dashboard_visualisation.generate_figures") as gen,
            ):
                if isinstance(result, Exception):
                    gen.side_effect = result
                else:
                    gen.return_value = result
                content = (
                    self.replacement_file if isinstance(result, Exception) else self.original_file
                )
                response = self.client.post(
                    self.url("edit", self.own.pk),
                    {"source_file": SimpleUploadedFile("replacement.csv", content)},
                )
                self.assertRedirects(response, self.url("list"), fetch_redirect_response=False)
                messages = " ".join(str(message) for message in get_messages(response.wsgi_request))
                self.assertIn(expected, messages)
                self.assertIn("contact an editor", messages)
                self.assertNotIn("private-own-slug", messages)
                self.assertNotIn("private_figure_key", messages)
                self.own.refresh_from_db()
                if isinstance(result, Exception):
                    self.assertEqual(self.own.data, self.new_figures)
                    self.assertEqual(self.own.data_updated_at, date(2024, 1, 1))
                    self.assertEqual(self.own.source_file.read(), self.replacement_file)
                else:
                    self.assertEqual(self.own.data, {})
                    self.assertEqual(self.own.data_updated_at, timezone.localdate())

    def test_other_groups_and_unassigned_rows_cannot_be_edited(self) -> None:
        """Knowing an object ID does not give a researcher access."""
        for row in (self.other, self.unassigned):
            original = DashboardData.objects.values().get(pk=row.pk)
            for method in (self.client.get, self.client.post):
                self.assert_denied(method(self.url("edit", row.pk)))
            self.assertEqual(DashboardData.objects.values().get(pk=row.pk), original)

    def test_multiple_groups_are_listed_in_title_order(self) -> None:
        """Researchers can update uploads assigned to any of their groups."""
        self.researcher.groups.add(self.other_group)
        response = self.client.get(self.url("list"))
        self.assertEqual(list(response.context["object_list"]), [self.other, self.own])
        self.assertEqual(self.client.get(self.url("edit", self.other.pk)).status_code, 200)

    def test_extra_permissions_do_not_enable_administrative_routes(self) -> None:
        """Enforce edit-only access even with directly assigned add/delete permissions."""
        self.researcher.user_permissions.add(*self.permissions)
        urls = [
            self.url("add"),
            self.url("copy", self.own.pk),
            self.url("delete", self.own.pk),
            self.url("history", self.own.pk),
            self.url("history_results", self.own.pk),
            self.url("usage", self.own.pk),
            self.url("revisions_compare", self.own.pk, self.first_revision.pk, "live"),
            self.url("revisions_revert", self.own.pk, self.first_revision.pk),
            reverse("wagtail_bulk_action", args=["cms", "dashboarddata", "delete"])
            + f"?id={self.own.pk}&id={self.other.pk}",
        ]
        for route in ("choose", "choose_results", "chosen_multiple", "create"):
            urls.append(reverse(f"{self.chooser_namespace}:{route}") + f"?id={self.other.pk}")
        urls.append(reverse(f"{self.chooser_namespace}:chosen", args=[self.other.pk]))
        original = list(DashboardData.objects.values())
        for url in urls:
            for method in (self.client.get, self.client.post):
                with self.subTest(url=url, method=method.__name__):
                    self.assert_denied(method(url))
        self.assertEqual(list(DashboardData.objects.values()), original)
        self.assertEqual(self.own.revisions.count(), 2)

    def test_revision_overwrite_is_denied_on_current_edit_route(self) -> None:
        """A crafted current-edit POST cannot rewrite an older audit revision."""
        self.first_revision.refresh_from_db()
        content = self.first_revision.content.copy()
        response = self.client.post(
            self.url("edit", self.own.pk),
            {
                "overwrite_revision_id": self.first_revision.pk,
                "source_file": SimpleUploadedFile("replacement.csv", self.replacement_file),
            },
        )
        self.assert_denied(response)
        self.first_revision.refresh_from_db()
        self.assertEqual(self.first_revision.content, content)
        self.assertEqual(self.own.revisions.count(), 2)

    def test_internal_forms_and_lists_survive_alternating_user_requests(self) -> None:
        """Researcher configuration must not leak into internal editor requests."""
        for user in (self.researcher, self.editor, self.researcher, self.superuser):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                response = self.client.get(self.url("edit", self.own.pk))
                fields = set(response.context["form"].fields)
                listing = self.client.get(self.url("list"))
                if user == self.researcher:
                    self.assertEqual(fields, {"source_file"})
                    self.assertNotContains(listing, "dashboard_slug")
                else:
                    self.assertEqual(
                        fields,
                        {
                            "dashboard_title",
                            "dashboard_slug",
                            "research_group",
                            "source_file",
                            "data_updated_at",
                            "data",
                        },
                    )
                    self.assertContains(listing, self.own.dashboard_slug)
                    self.assertContains(listing, self.other.dashboard_title)
                    self.assertContains(response, self.url("history", self.own.pk))

    def test_editor_membership_takes_precedence_and_metadata_remains_editable(self) -> None:
        """A researcher who also belongs to Editors retains normal editorial controls."""
        self.researcher.groups.add(self.editors)
        response = self.client.post(
            self.url("edit", self.own.pk),
            {
                "dashboard_title": "Editor title",
                "dashboard_slug": "editor-slug",
                "research_group": self.other_group.pk,
                "data_updated_at": "2001-01-01",
                "data": '{"historic": true}',
            },
        )
        self.assertRedirects(response, self.url("list"), fetch_redirect_response=False)
        self.own.refresh_from_db()
        self.assertEqual(self.own.dashboard_title, "Editor title")
        self.assertEqual(self.own.dashboard_slug, "editor-slug")
        self.assertEqual(self.own.research_group_id, self.other_group.pk)
        self.assertEqual(self.own.data_updated_at, date(2001, 1, 1))
        self.assertEqual(self.own.data, {"historic": True})

    def test_internal_auxiliary_routes_and_diagnostic_feedback_remain_available(self) -> None:
        """Editors can configure, compare, restore, choose, and remove uploads."""
        self.client.force_login(self.editor)
        for url in (
            self.url("add"),
            self.url("copy", self.own.pk),
            self.url("delete", self.own.pk),
            self.url("history", self.own.pk),
            self.url("history_results", self.own.pk),
            self.url("usage", self.own.pk),
            self.url("revisions_compare", self.own.pk, self.first_revision.pk, "live"),
            self.url("revisions_revert", self.own.pk, self.first_revision.pk),
            reverse(f"{self.chooser_namespace}:choose"),
            reverse(f"{self.chooser_namespace}:chosen", args=[self.other.pk]),
            reverse("wagtail_bulk_action", args=["cms", "dashboarddata", "delete"])
            + f"?id={self.other.pk}",
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
        with patch(
            "dashboard_visualisation.generate_figures", side_effect=ValueError("diagnostic")
        ):
            response = self.client.post(
                self.url("edit", self.own.pk),
                {
                    "dashboard_title": self.own.dashboard_title,
                    "dashboard_slug": self.own.dashboard_slug,
                    "research_group": self.group.pk,
                    "data": "{}",
                    "source_file": SimpleUploadedFile("replacement.csv", self.replacement_file),
                },
            )
        messages = " ".join(str(message) for message in get_messages(response.wsgi_request))
        self.assertIn("diagnostic", messages)

    def test_group_membership_without_change_permission_cannot_edit(self) -> None:
        """Group assignment and staff status do not grant model permissions."""
        self.no_permission.is_staff = True
        self.no_permission.save()
        self.client.force_login(self.no_permission)
        DashboardData.objects.filter(pk=self.own.pk).update(research_group=self.other_group)
        self.no_permission.groups.add(self.other_group)
        self.assert_denied(self.client.get(self.url("edit", self.own.pk)))
        self.assert_denied(self.client.get(self.url("list")))

    def test_registered_policy_agrees_for_user_and_object_queries(self) -> None:
        """The central registry enforces model grants and object membership consistently."""
        policy = policy_registry.get_by_type(DashboardData)
        self.researcher.user_permissions.add(*self.permissions)
        user = User.objects.get(pk=self.researcher.pk)
        self.assertFalse(policy.user_has_permission(user, "add"))
        self.assertFalse(policy.user_has_permission(user, "delete"))
        self.assertFalse(policy.user_has_permission(AnonymousUser(), "change"))
        self.assertTrue(policy.user_has_permission_for_instance(user, "change", self.own))
        self.assertFalse(policy.user_has_permission_for_instance(user, "change", self.other))
        self.assertNotIn(user, policy.users_with_any_permission({"add", "delete"}))
        self.assertIn(user, policy.users_with_any_permission_for_instance({"change"}, self.own))
        self.assertNotIn(
            user, policy.users_with_any_permission_for_instance({"change"}, self.other)
        )
        self.assertNotIn(
            user, policy.users_with_any_permission_for_instance({"change"}, self.unassigned)
        )
        self.assertEqual(
            list(policy.instances_user_has_any_permission_for(user, {"change"})), [self.own]
        )
        self.assertFalse(policy.instances_user_has_any_permission_for(user, {"delete"}).exists())

    def test_form_without_user_context_is_restricted(self) -> None:
        """Omitting for_user cannot expose an internal editing form."""
        form_class = ObjectList(DashboardData.panels).bind_to_model(DashboardData).get_form_class()
        self.assertEqual(set(form_class(instance=self.own).fields), {"source_file"})
