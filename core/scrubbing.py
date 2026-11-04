"""How personal data is scrubbed by django-scrubber's ``scrub_data`` command.

What gets scrubbed is configured in ``core.settings.scrub``, which points
django-scrubber at the classes here. This module is only imported by
django-scrubber once Django has started, so it can import models.

A run, in order:

1. ``pre_scrub``: refuse unless the database is a scrub copy, note all
   usernames and emails (for the leftover check), then empty the tables that
   only hold per-user data, secrets or logs.
2. django-scrubber replaces values in place, using ``SCRUBBER_GLOBAL_SCRUBBERS``
   and the per-model classes below. Rows are kept, so all foreign keys stay
   valid.
3. ``post_scrub``: give the copies inside revision JSON and history entries,
   which field rules can't reach, the same fake values as their rows, then
   fail if any text value, or string inside JSON, still equals a noted
   username or email.
4. django-scrubber deletes all sessions.

The whole run is one transaction, so a failure leaves the database unchanged.
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import CommandError
from django.db import connection, transaction
from django.db.models import Case, F, IntegerField, OuterRef, Subquery, Value, When
from django.db.models.functions import Cast, Coalesce
from django_scrubber import scrubbers
from django_scrubber.services.scrubber import ScrubberService
from wagtail.models import BaseViewRestriction, ModelLogEntry, PageLogEntry, Revision

from cms.snippets.dashboard_data import DashboardData

# The text every comment and reply gets, in its row and in revisions
COMMENT_TEXT = "Lorem ipsum dolor sit amet, consectetur adipiscing elit."


class UserScrubbers:
    """Rules for ``auth.User`` beyond the global ones (names and email)."""

    # Starting with "!" makes it an unusable password in Django: no login, and
    # no password reset. Developers create their own account after restoring.
    password = Value("!scrubbed")
    last_login = scrubbers.Null
    is_active = Value(False)


class CommentScrubbers:
    """Rules for comments and comment replies."""

    text = Value(COMMENT_TEXT)


class TaskStateScrubbers:
    """Rules for workflow task states."""

    comment = scrubbers.Empty  # free-text workflow review comment


class ViewRestrictionScrubbers:
    """Rules for page and collection view restrictions."""

    # Wagtail stores these shared passwords in plain text. Only password
    # restrictions have one; login and group restrictions are left as they are.
    password = Case(
        When(restriction_type=BaseViewRestriction.PASSWORD, then=Value("scrubbed")),
        default=F("password"),
    )


class PortalScrubberService(ScrubberService):
    """django-scrubber's service, with the portal's steps before and after scrubbing."""

    def run(self, **kwargs) -> None:
        """Run the whole scrub in one transaction."""
        # django-scrubber commits model by model; one transaction means a failed
        # leftover check doesn't leave a half-scrubbed database behind
        with transaction.atomic():
            super().run(**kwargs)

    def pre_scrub(self) -> None:
        """Check the database, note usernames and emails, empty per-user tables."""
        name = connection.settings_dict["NAME"]
        if not name.endswith("_scrub"):
            raise CommandError(
                f'Refusing to scrub database "{name}": scrubbing only runs on a copy whose'
                ' name ends with "_scrub".'
            )

        self.former_values = set()
        for username, email in get_user_model().objects.values_list("username", "email"):
            self.former_values.add(username.lower())
            if email:
                self.former_values.add(email.lower())

        existing_tables = set(connection.introspection.table_names())
        with connection.cursor() as cursor:
            for table in settings.SCRUB_TABLES_TO_EMPTY:
                if table in existing_tables:
                    # Table names come from settings, not from input
                    cursor.execute(f'DELETE FROM "{table}"')  # noqa: S608

    def post_scrub(self) -> None:
        """Fake the values inside revisions and history, then run the leftover check."""
        self.scrub_revisions()
        self.scrub_log_entries()
        self.check_for_leftovers()

    def scrub_revisions(self) -> None:
        """Give the copies inside revisions the fake values their rows now have.

        Revisions are JSON copies of objects: a dashboard data revision holds
        the uploader's username, and a page revision its comments and their
        replies, text included.
        """
        # Each row has its own fake uploader
        uploaders = {
            str(pk): uploaded_by
            for pk, uploaded_by in DashboardData.objects.values_list("pk", "uploaded_by")
        }

        revisions = list(
            Revision.objects.filter(
                content__has_any_keys=["uploaded_by", "wagtail_admin_comments"]
            ).only("object_id", "content")
        )
        for revision in revisions:
            content = revision.content
            if "uploaded_by" in content:
                content["uploaded_by"] = uploaders.get(revision.object_id, "")
            for comment in content.get("wagtail_admin_comments", []):
                comment["text"] = COMMENT_TEXT
                for reply in comment.get("replies", []):
                    reply["text"] = COMMENT_TEXT
        Revision.objects.bulk_update(revisions, ["content"], batch_size=500)

    def scrub_log_entries(self) -> None:
        """Give the copies inside history entries the fake values their rows now have.

        A history entry about a user account is labelled with its username, and
        entries about comments and workflow reviews hold a copy of their text.
        """
        user_model = get_user_model()
        # Each account's own fake username; accounts deleted since have none
        ModelLogEntry.objects.filter(
            content_type=ContentType.objects.get_for_model(user_model)
        ).update(
            label=Coalesce(
                Subquery(
                    user_model.objects.filter(
                        pk=Cast(OuterRef("object_id"), IntegerField())
                    ).values("username")
                ),
                Value("Deleted user"),
            )
        )

        for log_model in (PageLogEntry, ModelLogEntry):
            entries = list(
                log_model.objects.filter(data__has_any_keys=["comment", "reply"]).only("data")
            )
            for entry in entries:
                data = entry.data
                if isinstance(data.get("comment"), dict):
                    data["comment"]["text"] = COMMENT_TEXT
                elif "comment" in data:
                    data["comment"] = ""  # workflow review comment, as on its TaskState
                if "reply" in data:
                    data["reply"]["text"] = COMMENT_TEXT
            log_model.objects.bulk_update(entries, ["data"], batch_size=500)

    def check_for_leftovers(self) -> None:
        """Find text values, or strings inside JSON, equal to a former username or email.

        Code that copies account data copies whole values (e.g. ``uploaded_by``).
        Names or emails *within* longer text are editorial content, which is
        kept as it is, so they aren't searched for.
        """
        values = sorted(self.former_values - settings.SCRUB_LEFTOVER_CHECK_IGNORED_VALUES)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT c.table_name, c.column_name, c.data_type FROM information_schema.columns c"
                " JOIN information_schema.tables t USING (table_schema, table_name)"
                " WHERE c.table_schema = 'public' AND t.table_type = 'BASE TABLE'"
                # django-scrubber's generated fake values, deleted after the scrub
                " AND c.table_name NOT LIKE 'django\\_scrubber\\_%'"
                " AND c.data_type IN ('character varying', 'text', 'json', 'jsonb')"
                " ORDER BY c.table_name, c.column_name"
            )
            columns = cursor.fetchall()

            leftovers = []
            for table, column, data_type in columns:
                # Table and column names come from information_schema, not from input
                if data_type in ("json", "jsonb"):
                    match = (
                        "EXISTS (SELECT 1 FROM unnest(%s::text[]) v"  # noqa: S608
                        f' WHERE strpos(lower(t."{column}"::jsonb::text), to_jsonb(v)::text) > 0)'
                    )
                else:
                    match = f'lower(t."{column}") = ANY(%s)'
                query = f'SELECT count(*) FROM "{table}" t WHERE {match}'  # noqa: S608
                cursor.execute(query, [values])
                (found,) = cursor.fetchone()
                if found:
                    leftovers.append(f"{table}.{column} ({found} rows)")

        self._write_stdout(f"Leftover check: looked for {len(values)} usernames/emails")
        if leftovers:
            raise CommandError(
                "Former usernames or emails are still in: "
                + ", ".join(leftovers)
                + ". Scrub them, or add the value to SCRUB_LEFTOVER_CHECK_IGNORED_VALUES"
                " if the match is expected."
            )
