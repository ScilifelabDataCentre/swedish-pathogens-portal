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
3. ``post_scrub``: scrub what field rules can't reach (values inside revision
   JSON), then fail if any text value, or string inside JSON, still equals a
   noted username or email.
4. django-scrubber deletes all sessions.

The whole run is one transaction, so a failure leaves the database unchanged.
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import CommandError
from django.db import connection, transaction
from django.db.models import Value
from django_scrubber import scrubbers
from django_scrubber.services.scrubber import ScrubberService
from wagtail.models import ModelLogEntry


class UserScrubbers:
    """Rules for ``auth.User`` beyond the global ones (names and email)."""

    # Starting with "!" makes it an unusable password in Django: no login, and
    # no password reset. Developers create their own account after restoring.
    password = Value("!scrubbed")
    last_login = scrubbers.Null
    is_active = Value(False)


class CommentScrubbers:
    """Rules for comments and comment replies."""

    text = scrubbers.Lorem


class TaskStateScrubbers:
    """Rules for workflow task states."""

    comment = scrubbers.Empty  # free-text workflow review comment


class ViewRestrictionScrubbers:
    """Rules for page and collection view restrictions."""

    # Wagtail stores these shared passwords in plain text
    password = Value("scrubbed")


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
        self.check_database_name()

        self.former_values = set()
        for username, email in get_user_model().objects.values_list("username", "email"):
            self.former_values.update(value.lower() for value in (username, email) if value)

        existing_tables = set(connection.introspection.table_names())
        with connection.cursor() as cursor:
            for table in settings.SCRUB_TABLES_TO_EMPTY:
                if table in existing_tables:
                    # Table names come from settings, not from input
                    cursor.execute(f'DELETE FROM "{table}"')  # noqa: S608

        # Log entries about the user accounts themselves; their label is the username
        ModelLogEntry.objects.filter(
            content_type=ContentType.objects.get_for_model(get_user_model())
        ).delete()

    def post_scrub(self) -> None:
        """Scrub values inside revision JSON, then run the leftover check."""
        with connection.cursor() as cursor:
            # The dashboard data uploader's username, copied into each snippet revision
            cursor.execute(
                "UPDATE wagtailcore_revision"
                " SET content = jsonb_set(content, '{uploaded_by}', to_jsonb('scrubbed'::text))"
                " WHERE content ? 'uploaded_by' AND content->>'uploaded_by' <> ''"
            )
            # Comments are saved with each page revision, text included
            cursor.execute(
                "UPDATE wagtailcore_revision SET content = jsonb_set("
                "  content, '{wagtail_admin_comments}',"
                "  (SELECT jsonb_agg(comment || jsonb_build_object('text', 'Scrubbed comment.'))"
                "   FROM jsonb_array_elements(content->'wagtail_admin_comments') AS comment))"
                " WHERE jsonb_typeof(content->'wagtail_admin_comments') = 'array'"
                " AND jsonb_array_length(content->'wagtail_admin_comments') > 0"
            )
        self.check_for_leftovers()

    def check_database_name(self) -> None:
        """Refuse to run unless connected to a scrub copy of the database."""
        name = connection.settings_dict["NAME"]
        if not name.endswith("_scrub"):
            raise CommandError(
                f'Refusing to scrub database "{name}": scrubbing only runs on a copy whose'
                ' name ends with "_scrub".'
            )

    def check_for_leftovers(self) -> None:
        """Find text values, or strings inside JSON, equal to a former username or email.

        Code that copies account data copies whole values (e.g. ``uploaded_by``,
        log labels). Names or emails *within* longer text are editorial content,
        which is kept as it is, so they aren't searched for.
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
                        "EXISTS (SELECT 1"  # noqa: S608
                        f" FROM jsonb_path_query(t.\"{column}\"::jsonb, 'strict $.**') j"
                        " WHERE jsonb_typeof(j) = 'string' AND lower(j #>> '{}') = ANY(%s))"
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
