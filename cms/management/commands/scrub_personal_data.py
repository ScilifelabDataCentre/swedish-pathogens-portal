"""Management command: delete all users and personal data from a copy of the database.

Used to make a snapshot of production that can be shared with other deployed or local instances.

Personal data removal handled in 2 ways:
1. All users deleted via Django, and on_delete cascades to remove rows linked to the user
    by foreign keys (such asprofiles, API tokens).
2. Personal data not linked to users by foreign keys is removed manually.

Wagtail content like pages, images, documents is kept as is.

Run as a single transaction with check_for_leftovers() used as a guard at the end
to catch any remaining personal data.
"""

from __future__ import annotations

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.models import ForeignKey
from wagtail.contrib.forms.models import FormSubmission
from wagtail.models import (
    CollectionViewRestriction,
    ModelLogEntry,
    PageLogEntry,
    PageViewRestriction,
    Revision,
    TaskState,
)

from cms.snippets.dashboard_data import DashboardData


class Command(BaseCommand):
    """Deletes all users and personal data from a copy of the database."""

    help = "Delete all users and personal data from a copy of the database."

    def handle(self, *args, **options) -> None:
        """Scrub the database in one transaction, then check for leftovers."""
        name = connection.settings_dict["NAME"]
        if not name.endswith("_scrub"):
            raise CommandError(
                f'Refusing to scrub database "{name}": scrubbing only runs on a copy whose'
                ' name ends with "_scrub".'
            )

        with transaction.atomic():
            user_model = get_user_model()
            former_values = set()
            for username, email in user_model.objects.values_list("username", "email"):
                former_values.add(username.lower())
                if email:
                    former_values.add(email.lower())

            self.delete_users(user_model)
            self.scrub_private_values()
            self.scrub_revisions(user_model)

            self.check_for_leftovers(former_values)

    def delete_users(self, user_model: type) -> None:
        """Delete all users, and through ``on_delete`` the rows that only exist for them."""
        _, deleted = user_model.objects.all().delete()
        self.stdout.write(f"Deleted {deleted.get(user_model._meta.label, 0)} users, and with them:")
        for label, count in sorted(deleted.items()):
            if label != user_model._meta.label and count:
                self.stdout.write(f"  {label}: {count}")

    def scrub_private_values(self) -> None:
        """Manually remove private/personal values that are not removed by removing the user."""
        PageLogEntry.objects.all().delete()
        ModelLogEntry.objects.all().delete()
        Session.objects.all().delete()
        DashboardData.objects.update(uploaded_by="")
        TaskState.objects.update(comment="")
        FormSubmission.objects.all().delete()
        # used by wagtail for private pages, password's stored as plaintext in the db
        for restriction in (PageViewRestriction, CollectionViewRestriction):
            restriction.objects.filter(restriction_type=restriction.PASSWORD).update(
                password="scrubbed"  # noqa: S106
            )

    def scrub_revisions(self, user_model: type) -> None:
        """Remove users, uploaders and comments from revisions.

        Revisions are JSON copies of objects, so they still hold the deleted
        users' IDs (e.g. a page's owner), which would break reverting to them,
        plus the uploader's username and the comments saved with each revision.
        """
        user_fields = {
            field.name
            for model in apps.get_models()
            for field in model._meta.concrete_fields
            if isinstance(field, ForeignKey) and field.related_model is user_model
        }
        replacements = dict.fromkeys(user_fields)
        replacements |= {"uploaded_by": "", "wagtail_admin_comments": []}

        revisions = list(
            Revision.objects.filter(content__has_any_keys=list(replacements)).only("content")
        )
        for revision in revisions:
            # Only the keys a revision has, so no new keys are added
            revision.content.update(
                {key: value for key, value in replacements.items() if key in revision.content}
            )
        Revision.objects.bulk_update(revisions, ["content"], batch_size=500)

    def check_for_leftovers(self, former_values: set[str]) -> None:
        """Fail if a text value, or a string inside JSON, equals a former username or email.

        Code that copies account data copies whole values (e.g. ``uploaded_by``).
        Names or emails *within* longer text are editorial content, which is
        kept as it is, so they aren't searched for.
        """
        # These are common (local) usernames that could accidentally appear as ordinary content
        values_to_check = sorted(former_values - {"root", "admin"})
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT c.table_name, c.column_name, c.data_type FROM information_schema.columns c"
                " JOIN information_schema.tables t USING (table_schema, table_name)"
                " WHERE c.table_schema = 'public' AND t.table_type = 'BASE TABLE'"
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
                cursor.execute(query, [values_to_check])
                (found,) = cursor.fetchone()
                if found:
                    leftovers.append(f"{table}.{column} ({found} rows)")

        self.stdout.write(f"Leftover check: looked for {len(values_to_check)} usernames/emails")
        if leftovers:
            raise CommandError(
                "Former usernames or emails are still in: " + ", ".join(leftovers) + "."
            )
