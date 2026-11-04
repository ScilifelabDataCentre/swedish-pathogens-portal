"""Tests for scrubbing personal data with django-scrubber (``core.scrubbing``).

The test settings install ``django_scrubber``; the scrub settings from
``core.settings.scrub`` are applied with ``override_settings``.
"""

from datetime import timedelta
from io import StringIO
from unittest import mock

from django.apps import apps
from django.contrib.admin.models import ADDITION, LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from django.contrib.sessions.models import Session
from django.core.management import CommandError, call_command
from django.db import connection
from django.test import TestCase, override_settings
from django.utils import timezone
from django.utils.module_loading import import_string
from django_scrubber import scrubbers
from django_scrubber.models import FakeData
from wagtail.admin.models import EditingSession, FormState
from wagtail.contrib.forms.models import FormSubmission
from wagtail.log_actions import log
from wagtail.models import (
    APIToken,
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
from core.scrubbing import COMMENT_TEXT
from core.settings import scrub as scrub_settings

User = get_user_model()
IndexEntry = apps.get_model("wagtailsearch", "IndexEntry")

SCRUB_SETTINGS = {
    name: getattr(scrub_settings, name)
    for name in (
        "SCRUBBER_SERVICE_CLASS",
        "SCRUBBER_GLOBAL_SCRUBBERS",
        "SCRUBBER_MAPPING",
        "SCRUB_TABLES_TO_EMPTY",
        "SCRUB_LEFTOVER_CHECK_IGNORED_VALUES",
    )
}

# Tables of apps not installed yet; the scrub skips them
NOT_YET_INSTALLED_TABLES = {
    "account_emailconfirmation",
    "socialaccount_socialtoken",
    "socialaccount_socialaccount",
    "mfa_authenticator",
    "usersessions_usersession",
}


def scrub() -> str:
    """Run ``scrub_data`` as if on a copy named ``*_scrub``; return its output."""
    out = StringIO()
    with mock.patch.dict(connection.settings_dict, {"NAME": "spp_scrub"}):
        call_command("scrub_data", "--remove-fake-data", stdout=out)
    return out.getvalue()


@override_settings(DEBUG=True, **SCRUB_SETTINGS)
class ScrubTestCase(TestCase):
    """Two editors and everything on the site that refers to them."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Create the editors, their content, history and private values."""
        cls.editor = User.objects.create_user(
            "scrubtest",
            "scrubtest@example.com",
            "password",
            first_name="Scrub",
            last_name="Tester",
            last_login=timezone.now(),
        )
        cls.reviewer = User.objects.create_user("reviewer", "reviewer@example.com", "password")
        cls.group = Group.objects.create(name="Scrub editors")
        cls.editor.groups.add(cls.group)
        UserProfile.get_for_user(cls.editor)

        # Content: a page owned and locked by the editor
        cls.page = BasicPage(title="Scrub test", slug="scrub-test", owner=cls.editor)
        Page.get_first_root_node().add_child(instance=cls.page)
        Page.objects.filter(pk=cls.page.pk).update(locked=True, locked_by=cls.editor)
        cls.page.refresh_from_db()
        page_type = ContentType.objects.get_for_model(Page)

        # Private comments, saved with the page's revision
        cls.comment = Comment.objects.create(
            page=cls.page, user=cls.editor, text="private admin comment", contentpath="title"
        )
        cls.reply = CommentReply.objects.create(
            comment=cls.comment, user=cls.reviewer, text="private reply"
        )
        cls.comment.log_create(user=cls.editor)
        cls.reply.log_create(user=cls.reviewer)
        cls.page_revision = cls.page.save_revision(user=cls.editor)

        # A workflow with a review comment, and history
        workflow = Workflow.objects.create(name="Scrub review")
        task = GroupApprovalTask.objects.create(name="Scrub approval")
        WorkflowTask.objects.create(workflow=workflow, task=task, sort_order=0)
        workflow.start(cls.page, cls.editor)
        TaskState.objects.update(comment="private review comment")
        TaskState.objects.get().log_state_change_action(cls.reviewer, "reject")

        # History about user accounts, one of which has since been deleted
        log(instance=cls.editor, action="wagtail.create", user=cls.reviewer)
        former = User.objects.create_user("former", "former@example.com")
        log(instance=former, action="wagtail.create", user=cls.reviewer)
        cls.former_pk = former.pk
        former.delete()

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
        cls.dashboard_revision = Revision.objects.create(
            content_type=dashboard_type,
            base_content_type=dashboard_type,
            object_id=str(cls.dashboard_data.pk),
            created_at=timezone.now(),
            content={"dashboard_title": "Cases", "uploaded_by": "scrubtest"},
        )

        # Rows in the tables that are emptied
        PageSubscription.objects.create(
            page=cls.page, user=cls.reviewer, comment_notifications=True
        )
        APIToken.objects.create(
            user=cls.editor, name="token", key_hash="hash", prefix="abc", created=timezone.now()
        )
        EditingSession.objects.create(
            user=cls.editor,
            content_type=page_type,
            object_id=str(cls.page.pk),
            last_seen_at=timezone.now(),
        )
        FormState.objects.create(
            user=cls.editor,
            data="unsaved form input",
            content_type=page_type,
            object_id=str(cls.page.pk),
            parent_object_id="",
            last_updated_at=timezone.now(),
        )
        FormSubmission.objects.create(page=cls.page, form_data={"name": "A visitor"})
        LogEntry.objects.create(
            user=cls.editor,
            content_type=page_type,
            object_id=str(cls.page.pk),
            object_repr="scrubtest",
            action_flag=ADDITION,
        )

        # Values that don't refer to a user but are private
        Session.objects.create(
            session_key="scrubtest-session",
            session_data="data",
            expire_date=timezone.now() + timedelta(days=1),
        )
        cls.page_restriction = PageViewRestriction.objects.create(
            page=cls.page,
            restriction_type=PageViewRestriction.PASSWORD,
            password="page secret",  # noqa: S106 (test data)
        )
        cls.collection_restriction = CollectionViewRestriction.objects.create(
            collection=Collection.get_first_root_node(),
            restriction_type=CollectionViewRestriction.PASSWORD,
            password="collection secret",  # noqa: S106 (test data)
        )
        cls.login_restriction = PageViewRestriction.objects.create(
            page=Page.get_first_root_node(), restriction_type=PageViewRestriction.LOGIN
        )

    def setUp(self) -> None:
        """Make django-scrubber generate its fake data again in each test.

        It remembers which providers it has generated data for, but the data
        itself is rolled back with each test.
        """
        scrubbers.Faker.INITIALIZED_PROVIDERS.clear()
        self.addCleanup(scrubbers.Faker.INITIALIZED_PROVIDERS.clear)


class UserTests(ScrubTestCase):
    """Users are kept, so references stay valid, but anonymised."""

    def test_keeps_users(self):
        """No user is deleted, and group memberships stay."""
        scrub()

        self.assertEqual(User.objects.count(), 2)
        self.assertTrue(self.group.user_set.filter(pk=self.editor.pk).exists())

    def test_replaces_names_and_emails(self):
        """Username, names and email are replaced with fake values."""
        scrub()

        editor = User.objects.get(pk=self.editor.pk)
        self.assertNotIn(editor.username, ("", "scrubtest"))
        self.assertNotIn(editor.first_name, ("", "Scrub"))
        self.assertNotIn(editor.last_name, ("", "Tester"))
        self.assertNotIn(editor.email, ("", "scrubtest@example.com"))
        self.assertIn("@", editor.email)

    def test_makes_accounts_unusable(self):
        """No one can log in, or reset a password, as a scrubbed user."""
        scrub()

        editor = User.objects.get(pk=self.editor.pk)
        self.assertFalse(editor.has_usable_password())
        self.assertFalse(editor.is_active)
        self.assertIsNone(editor.last_login)

    def test_content_keeps_its_users(self):
        """The page still points at its (anonymised) owner."""
        scrub()

        self.page.refresh_from_db()
        self.assertEqual(self.page.owner_id, self.editor.pk)
        self.assertEqual(self.page.title, "Scrub test")


class FieldRuleTests(ScrubTestCase):
    """Values replaced by the global and per-model rules."""

    def test_replaces_comment_text(self):
        """Comments and replies stay, with placeholder text."""
        scrub()

        self.comment.refresh_from_db()
        self.assertEqual(self.comment.text, COMMENT_TEXT)
        self.reply.refresh_from_db()
        self.assertEqual(self.reply.text, COMMENT_TEXT)

    def test_clears_workflow_review_comments(self):
        """Task states stay, without their comments."""
        self.assertTrue(TaskState.objects.exists())

        scrub()

        self.assertFalse(TaskState.objects.exclude(comment="").exists())

    def test_replaces_dashboard_data_uploader(self):
        """The uploader's username, stored as text, is replaced; the data stays."""
        scrub()

        self.dashboard_data.refresh_from_db()
        self.assertNotIn(self.dashboard_data.uploaded_by, ("", "scrubtest"))
        self.assertEqual(self.dashboard_data.dashboard_title, "Cases")

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


class EmptiedTablesTests(ScrubTestCase):
    """Tables that only hold per-user data, secrets or logs are emptied."""

    def test_empties_per_user_tables(self):
        """Every table in SCRUB_TABLES_TO_EMPTY that exists is emptied."""
        emptied = (
            APIToken,
            UserProfile,
            PageSubscription,
            EditingSession,
            FormState,
            FormSubmission,
            LogEntry,
            IndexEntry,
        )
        for model in emptied:
            self.assertTrue(model.objects.exists(), f"{model._meta.label} has no test row")

        scrub()

        for model in emptied:
            with self.subTest(model=model._meta.label):
                self.assertFalse(model.objects.exists())

    def test_deletes_sessions(self):
        """django-scrubber deletes all sessions."""
        scrub()

        self.assertFalse(Session.objects.exists())

    def test_removes_fake_data(self):
        """With --remove-fake-data, the generated fake values aren't left behind."""
        scrub()

        self.assertFalse(FakeData.objects.exists())


class RevisionTests(ScrubTestCase):
    """Values inside revision JSON, which field rules can't reach."""

    def test_fakes_comment_and_reply_text_in_page_revisions(self):
        """Comments and their replies in a revision get the same text as their rows."""
        comment = self.page_revision.content["wagtail_admin_comments"][0]
        self.assertEqual(comment["text"], "private admin comment")
        self.assertEqual(comment["replies"][0]["text"], "private reply")

        scrub()

        self.page_revision.refresh_from_db()
        scrubbed = self.page_revision.content["wagtail_admin_comments"][0]
        self.assertEqual(scrubbed["text"], COMMENT_TEXT)
        self.assertEqual(scrubbed["replies"][0]["text"], COMMENT_TEXT)
        self.assertEqual(scrubbed["contentpath"], comment["contentpath"])
        self.assertEqual(self.page_revision.content["title"], "Scrub test")

    def test_fakes_uploader_in_snippet_revisions(self):
        """A dashboard data revision gets the same fake uploader as its row."""
        scrub()

        self.dashboard_revision.refresh_from_db()
        self.dashboard_data.refresh_from_db()
        self.assertEqual(
            self.dashboard_revision.content["uploaded_by"], self.dashboard_data.uploaded_by
        )
        self.assertNotIn(self.dashboard_revision.content["uploaded_by"], ("", "scrubtest"))

    def test_page_revision_can_still_be_loaded(self):
        """Users are kept, so a revision's owner still exists."""
        scrub()

        self.page_revision.refresh_from_db()
        page = self.page_revision.as_object()
        self.assertEqual(page.owner, User.objects.get(pk=self.editor.pk))


class LogEntryTests(ScrubTestCase):
    """History is kept, with the values copied into it faked like their rows."""

    def test_keeps_history_and_who_did_what(self):
        """No history entry is deleted, and each still points at its (anonymised) user."""
        before = {
            log_model: set(log_model.objects.values_list("pk", "user_id"))
            for log_model in (PageLogEntry, ModelLogEntry)
        }

        scrub()

        for log_model, entries in before.items():
            with self.subTest(model=log_model._meta.label):
                self.assertEqual(set(log_model.objects.values_list("pk", "user_id")), entries)

    def test_labels_user_entries_with_their_fake_username(self):
        """An entry about an account gets the account's new username as its label."""
        entry = ModelLogEntry.objects.get(object_id=str(self.editor.pk))
        self.assertEqual(entry.label, "scrubtest")

        scrub()

        entry.refresh_from_db()
        self.assertEqual(entry.label, User.objects.get(pk=self.editor.pk).username)

    def test_labels_entries_about_deleted_users(self):
        """An entry about an account deleted since has no fake username to take."""
        entry = ModelLogEntry.objects.get(object_id=str(self.former_pk))
        self.assertEqual(entry.label, "former")

        scrub()

        entry.refresh_from_db()
        self.assertEqual(entry.label, "Deleted user")

    def test_leaves_other_labels_alone(self):
        """Entries about pages keep the page title as their label."""
        entry = PageLogEntry.objects.get(action="wagtail.comments.create")

        scrub()

        entry.refresh_from_db()
        self.assertEqual(entry.label, "Scrub test")

    def test_fakes_comment_and_reply_text(self):
        """Copies of comments and replies get the same text as their rows."""
        comment_entry = PageLogEntry.objects.get(action="wagtail.comments.create")
        reply_entry = PageLogEntry.objects.get(action="wagtail.comments.create_reply")
        self.assertEqual(comment_entry.data["comment"]["text"], "private admin comment")
        self.assertEqual(reply_entry.data["reply"]["text"], "private reply")

        scrub()

        comment_entry.refresh_from_db()
        self.assertEqual(comment_entry.data["comment"]["text"], COMMENT_TEXT)
        self.assertEqual(comment_entry.data["comment"]["contentpath"], "title")
        reply_entry.refresh_from_db()
        self.assertEqual(reply_entry.data["comment"]["text"], COMMENT_TEXT)
        self.assertEqual(reply_entry.data["reply"]["text"], COMMENT_TEXT)

    def test_clears_workflow_review_comments(self):
        """Copies of a workflow review comment are emptied, as on the task state."""
        entry = PageLogEntry.objects.get(action="wagtail.workflow.reject")
        self.assertEqual(entry.data["comment"], "private review comment")

        scrub()

        entry.refresh_from_db()
        self.assertEqual(entry.data["comment"], "")
        self.assertEqual(entry.data["workflow"]["title"], "Scrub review")


class LeftoverCheckTests(ScrubTestCase):
    """The check at the end fails, and undoes the scrub, if account data is left."""

    def assert_nothing_scrubbed(self) -> None:
        """Everything the scrub would have changed is as it was before."""
        self.assertEqual(User.objects.get(pk=self.editor.pk).username, "scrubtest")
        self.assertTrue(Session.objects.exists())
        self.assertTrue(UserProfile.objects.exists())
        self.page_restriction.refresh_from_db()
        self.assertEqual(self.page_restriction.password, "page secret")

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

        self.assertNotEqual(User.objects.get(pk=self.editor.pk).username, "scrubtest")

    def test_ignores_root_and_admin(self):
        """The usernames "root" and "admin" also name ordinary content."""
        User.objects.create_user("root")
        User.objects.create_user("admin")
        BasicPage.objects.filter(pk=self.page.pk).update(seo_title="Admin")

        output = scrub()

        self.assertIn("looked for 4 usernames/emails", output)


class SafetyTests(ScrubTestCase):
    """The scrub refuses to run anywhere but on a scrub copy."""

    def test_refuses_other_databases(self):
        """On a database not named ``*_scrub``, nothing is changed."""
        with self.assertRaisesMessage(CommandError, "Refusing to scrub database"):
            call_command("scrub_data", stdout=StringIO())

        self.assertEqual(User.objects.get(pk=self.editor.pk).username, "scrubtest")
        self.assertTrue(UserProfile.objects.exists())

    @override_settings(DEBUG=False)
    def test_refuses_without_debug(self):
        """django-scrubber's own guard: it only runs with DEBUG on."""
        with self.assertRaisesMessage(CommandError, "DEBUG=True"):
            scrub()

        self.assertEqual(User.objects.get(pk=self.editor.pk).username, "scrubtest")


class ScrubSettingsTests(TestCase):
    """The scrub settings name fields and tables that exist."""

    def test_mapped_fields_exist(self):
        """django-scrubber only warns about a per-model rule for a missing field."""
        for label, path in SCRUB_SETTINGS["SCRUBBER_MAPPING"].items():
            model = apps.get_model(label)
            rules = import_string(path)
            for name in (name for name in vars(rules) if not name.startswith("_")):
                with self.subTest(rule=f"{label}.{name}"):
                    model._meta.get_field(name)

    def test_global_field_names_exist(self):
        """Each field name with a global rule is used by at least one model."""
        field_names = {
            field.name for model in apps.get_models() for field in model._meta.concrete_fields
        }
        for name in SCRUB_SETTINGS["SCRUBBER_GLOBAL_SCRUBBERS"]:
            if isinstance(name, str):
                with self.subTest(field=name):
                    self.assertIn(name, field_names)

    def test_tables_to_empty_exist(self):
        """A misspelt or renamed table would be skipped without a word."""
        existing = set(connection.introspection.table_names())
        for table in SCRUB_SETTINGS["SCRUB_TABLES_TO_EMPTY"]:
            if table not in NOT_YET_INSTALLED_TABLES:
                with self.subTest(table=table):
                    self.assertIn(table, existing)
