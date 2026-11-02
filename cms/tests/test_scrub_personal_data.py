"""Tests for the ``scrub_personal_data`` management command."""

from datetime import timedelta
from io import StringIO
from unittest import mock

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from django.contrib.sessions.models import Session
from django.core.management import CommandError, call_command
from django.db import connection, models
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from wagtail.contrib.forms.models import FormSubmission
from wagtail.log_actions import log
from wagtail.models import (
    Collection,
    CollectionViewRestriction,
    Comment,
    CommentReply,
    GroupApprovalTask,
    ModelLogEntry,
    Page,
    PageLogEntry,
    PageSubscription,
    PageViewRestriction,
    Revision,
    TaskState,
    Workflow,
    WorkflowTask,
)
from wagtail.users.models import UserProfile

from cms.pages import BasicPage
from cms.snippets.dashboard_data import DashboardData
from cms.tests.utils import create_test_image

User = get_user_model()


def scrub() -> str:
    """Run the command as if on a copy named ``*_scrub``; return its output."""
    out = StringIO()
    with mock.patch.dict(connection.settings_dict, {"NAME": "spp_scrub"}):
        call_command("scrub_personal_data", stdout=out)
    return out.getvalue()


class ScrubTestCase(TestCase):
    """Two editors and everything on the site that refers to them."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Create the editors, their content, history and private values."""
        cls.editor = User.objects.create_user(
            "scrubtest", "scrubtest@example.com", "password", first_name="Scrub"
        )
        cls.reviewer = User.objects.create_user("reviewer", "reviewer@example.com", "password")
        cls.group = Group.objects.create(name="Scrub editors")
        cls.editor.groups.add(cls.group)
        UserProfile.get_for_user(cls.editor)

        # Content: a page owned and locked by the editor, and an uploaded image
        cls.page = BasicPage(title="Scrub test", slug="scrub-test", owner=cls.editor)
        Page.get_first_root_node().add_child(instance=cls.page)
        cls.image = create_test_image()
        cls.image.uploaded_by_user = cls.editor
        cls.image.save()

        # Private comments, saved with the page's revision
        comment = Comment.objects.create(
            page=cls.page, user=cls.editor, text="private admin comment", contentpath="title"
        )
        CommentReply.objects.create(comment=comment, user=cls.reviewer, text="private reply")
        PageSubscription.objects.create(
            page=cls.page, user=cls.reviewer, comment_notifications=True
        )
        comment.log_create(user=cls.editor)
        Page.objects.filter(pk=cls.page.pk).update(locked=True, locked_by=cls.editor)
        cls.page.refresh_from_db()
        cls.page_revision = cls.page.save_revision(user=cls.editor)

        # A workflow with a review comment
        workflow = Workflow.objects.create(name="Scrub review")
        task = GroupApprovalTask.objects.create(name="Scrub approval")
        WorkflowTask.objects.create(workflow=workflow, task=task, sort_order=0)
        workflow.start(cls.page, cls.editor)
        TaskState.objects.update(comment="private review comment")
        log(
            instance=cls.page,
            action="wagtail.workflow.reject",
            user=cls.reviewer,
            data={"comment": "private review comment"},
        )
        log(instance=cls.editor, action="wagtail.create", user=cls.reviewer)

        # Dashboard data and a revision of it, both naming the uploader as text.
        # bulk_create skips the model's save(), which processes the source file.
        (cls.dashboard_data,) = DashboardData.objects.bulk_create(
            [
                DashboardData(
                    dashboard_title="Cases",
                    dashboard_slug="scrub-cases",
                    source_file="dashboard_data/cases.csv",
                    uploaded_by="scrubtest",
                )
            ]
        )
        dashboard_type = ContentType.objects.get_for_model(DashboardData)
        revision_fields = {
            "content_type": dashboard_type,
            "base_content_type": dashboard_type,
            "object_id": str(cls.dashboard_data.pk),
            "created_at": timezone.now(),
        }
        cls.dashboard_revision = Revision.objects.create(
            **revision_fields,
            content={"dashboard_title": "Cases", "uploaded_by": "scrubtest"},
            user=cls.editor,
        )
        cls.plain_revision = Revision.objects.create(
            **revision_fields, content={"dashboard_title": "Cases", "data": {"figure": 1}}
        )

        # Values that don't refer to a user but are private
        Session.objects.create(
            session_key="scrubtest-session",
            session_data="data",
            expire_date=timezone.now() + timedelta(days=1),
        )
        FormSubmission.objects.create(page=cls.page, form_data={"name": "A visitor"})
        cls.page_restriction = PageViewRestriction.objects.create(
            page=cls.page,
            restriction_type=PageViewRestriction.PASSWORD,
            password="page secret",  # noqa: S106
        )
        cls.collection_restriction = CollectionViewRestriction.objects.create(
            collection=Collection.get_first_root_node(),
            restriction_type=CollectionViewRestriction.PASSWORD,
            password="collection secret",  # noqa: S106
        )
        cls.login_restriction = PageViewRestriction.objects.create(
            page=Page.get_first_root_node(), restriction_type=PageViewRestriction.LOGIN
        )


class DeleteUsersTests(ScrubTestCase):
    """Users are deleted, and with them the rows that only exist for them."""

    def test_deletes_all_users(self):
        """No users are left, and the output says how many were deleted."""
        output = scrub()

        self.assertFalse(User.objects.exists())
        self.assertIn("Deleted 2 users", output)

    def test_reports_what_was_deleted_with_them(self):
        """The output lists the rows deleted through ``on_delete``."""
        output = scrub()

        self.assertIn("wagtailcore.Comment: 1", output)
        self.assertIn("wagtailcore.PageSubscription: 1", output)
        self.assertIn("wagtailusers.UserProfile:", output)

    def test_deletes_rows_that_only_exist_for_users(self):
        """Profiles, comments, replies, subscriptions and group memberships are gone."""
        scrub()

        self.assertFalse(UserProfile.objects.exists())
        self.assertFalse(Comment.objects.exists())
        self.assertFalse(CommentReply.objects.exists())
        self.assertFalse(PageSubscription.objects.exists())
        self.assertFalse(User.groups.through.objects.exists())

    def test_keeps_content_without_its_users(self):
        """Pages, images and groups stay; their user references are emptied."""
        scrub()

        self.page.refresh_from_db()
        self.assertIsNone(self.page.owner)
        self.assertIsNone(self.page.locked_by)
        self.image.refresh_from_db()
        self.assertIsNone(self.image.uploaded_by_user)
        self.assertTrue(Group.objects.filter(pk=self.group.pk).exists())


class PrivateValuesTests(ScrubTestCase):
    """Private values that deleting users doesn't reach."""

    def test_deletes_log_entries(self):
        """Wagtail's history (users and comment copies) is deleted."""
        self.assertTrue(PageLogEntry.objects.exists())
        self.assertTrue(ModelLogEntry.objects.exists())

        scrub()

        self.assertFalse(PageLogEntry.objects.exists())
        self.assertFalse(ModelLogEntry.objects.exists())

    def test_deletes_sessions(self):
        """Sessions are deleted."""
        scrub()

        self.assertFalse(Session.objects.exists())

    def test_deletes_form_submissions(self):
        """What visitors typed into forms is deleted."""
        scrub()

        self.assertFalse(FormSubmission.objects.exists())

    def test_clears_dashboard_data_uploader(self):
        """The uploader's username, stored as text, is cleared; the data stays."""
        scrub()

        self.dashboard_data.refresh_from_db()
        self.assertEqual(self.dashboard_data.uploaded_by, "")
        self.assertEqual(self.dashboard_data.dashboard_title, "Cases")

    def test_clears_workflow_review_comments(self):
        """Task states stay, without their comments."""
        self.assertTrue(TaskState.objects.exists())

        scrub()

        self.assertFalse(TaskState.objects.exclude(comment="").exists())

    def test_replaces_view_restriction_passwords(self):
        """Password restrictions keep restricting, with a placeholder password."""
        scrub()

        self.page_restriction.refresh_from_db()
        self.assertEqual(self.page_restriction.password, "scrubbed")
        self.collection_restriction.refresh_from_db()
        self.assertEqual(self.collection_restriction.password, "scrubbed")

    def test_leaves_other_view_restrictions_alone(self):
        """A login restriction has no password and is left as it is."""
        scrub()

        self.login_restriction.refresh_from_db()
        self.assertEqual(self.login_restriction.password, "")


class RevisionTests(ScrubTestCase):
    """Users, uploaders and comments are removed from revisions."""

    def test_removes_users_and_comments_from_page_revisions(self):
        """The owner, lock and comments are emptied; the content stays."""
        content = self.page_revision.content
        self.assertEqual(content["owner"], self.editor.pk)
        self.assertEqual(content["locked_by"], self.editor.pk)
        self.assertEqual(content["wagtail_admin_comments"][0]["text"], "private admin comment")

        scrub()

        self.page_revision.refresh_from_db()
        content = self.page_revision.content
        self.assertIsNone(content["owner"])
        self.assertIsNone(content["locked_by"])
        self.assertEqual(content["wagtail_admin_comments"], [])
        self.assertEqual(content["title"], "Scrub test")

    def test_page_revision_can_still_be_loaded(self):
        """Reverting needs the revision as a page, without pointing at deleted users."""
        scrub()

        self.page_revision.refresh_from_db()
        page = self.page_revision.as_object()
        self.assertEqual(page.title, "Scrub test")
        self.assertIsNone(page.owner)

    def test_clears_uploader_in_snippet_revisions(self):
        """The dashboard data uploader is cleared in its revisions too."""
        scrub()

        self.dashboard_revision.refresh_from_db()
        self.assertEqual(self.dashboard_revision.content["uploaded_by"], "")

    def test_adds_no_keys(self):
        """Only keys a revision already has are replaced."""
        page_keys = set(self.page_revision.content)
        plain_content = self.plain_revision.content

        scrub()

        self.page_revision.refresh_from_db()
        self.assertEqual(set(self.page_revision.content), page_keys)
        self.plain_revision.refresh_from_db()
        self.assertEqual(self.plain_revision.content, plain_content)

    def test_empties_the_revision_author(self):
        """Who saved each revision is emptied through ``on_delete``."""
        scrub()

        self.assertFalse(Revision.objects.filter(user__isnull=False).exists())


class LeftoverCheckTests(ScrubTestCase):
    """The check at the end fails, and undoes the scrub, if account data is left."""

    def assert_nothing_scrubbed(self) -> None:
        """Everything the scrub would have changed is as it was before."""
        self.assertEqual(User.objects.count(), 2)
        self.assertTrue(Session.objects.exists())
        self.assertTrue(PageLogEntry.objects.exists())
        self.page_revision.refresh_from_db()
        self.assertEqual(self.page_revision.content["owner"], self.editor.pk)
        self.dashboard_data.refresh_from_db()
        self.assertEqual(self.dashboard_data.uploaded_by, "scrubtest")

    def test_passes_after_a_full_scrub(self):
        """With everything scrubbed, nothing is left; the output says what was checked."""
        output = scrub()

        self.assertIn("Leftover check: looked for 4 usernames/emails", output)

    def test_fails_on_a_username_in_a_text_column(self):
        """A text value equal to a former username fails and rolls back."""
        BasicPage.objects.filter(pk=self.page.pk).update(seo_title="scrubtest")

        with self.assertRaisesMessage(CommandError, "wagtailcore_page.seo_title (1 rows)"):
            scrub()
        self.assert_nothing_scrubbed()

    def test_fails_on_an_email_nested_in_json(self):
        """A string anywhere inside JSON equal to a former email fails, ignoring case."""
        content = {**self.page_revision.content, "body": [{"value": "Reviewer@Example.com"}]}
        Revision.objects.filter(pk=self.page_revision.pk).update(content=content)

        with self.assertRaisesMessage(CommandError, "wagtailcore_revision.content (1 rows)"):
            scrub()
        self.assert_nothing_scrubbed()

    def test_ignores_usernames_within_longer_text(self):
        """Names or emails inside longer text are editorial content."""
        BasicPage.objects.filter(pk=self.page.pk).update(
            seo_title="Questions? Email scrubtest@example.com"
        )

        scrub()

        self.assertFalse(User.objects.exists())

    def test_ignores_root_and_admin(self):
        """The usernames "root" and "admin" also name ordinary content."""
        User.objects.create_user("root")
        User.objects.create_user("admin")
        BasicPage.objects.filter(pk=self.page.pk).update(seo_title="Admin")

        output = scrub()

        self.assertFalse(User.objects.exists())
        self.assertIn("looked for 4 usernames/emails", output)


class DatabaseNameTests(ScrubTestCase):
    """The command only runs on a copy whose name ends with ``_scrub``."""

    def test_refuses_other_databases(self):
        """On any other database, nothing is changed."""
        with self.assertRaisesMessage(CommandError, "Refusing to scrub database"):
            call_command("scrub_personal_data", stdout=StringIO())

        self.assertEqual(User.objects.count(), 2)
        self.assertTrue(PageLogEntry.objects.exists())


class UserForeignKeyTests(SimpleTestCase):
    """Deleting users only works if every reference to them allows it."""

    def test_user_foreign_keys_cascade_or_set_null(self):
        """A new PROTECT or DO_NOTHING reference would break or escape the scrub.

        Wagtail's log entries use DO_NOTHING, but the command deletes them.
        """
        deleted_by_the_command = {PageLogEntry, ModelLogEntry}
        for model in apps.get_models():
            if model in deleted_by_the_command:
                continue
            for field in model._meta.concrete_fields:
                if isinstance(field, models.ForeignKey) and field.related_model is User:
                    with self.subTest(field=f"{model._meta.label}.{field.name}"):
                        self.assertIn(
                            field.remote_field.on_delete, (models.CASCADE, models.SET_NULL)
                        )
