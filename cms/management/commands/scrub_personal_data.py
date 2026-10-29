"""Management command: delete all users and personal data from a copy of the database.

Used to make a snapshot of production that can be shared with other instances.
Only runs on a database whose name ends with ``_scrub``, i.e. a copy restored
for this purpose, never on a live one.

Users are deleted through Django, so its ``on_delete`` rules apply: rows that
only exist for a user (profiles, API tokens, subscriptions, comments, admin log,
and django-allauth's tables once added) are deleted, and content keeps existing
with its user set to empty. Personal data that no foreign key reaches is then
removed by hand. Content itself (pages, images, documents, published text) is
kept as it is.

The whole run is one transaction: if the leftover check at the end fails, the
database is left unchanged. Create an account afterwards with
``manage.py createsuperuser``.
"""

from __future__ import annotations

import json

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand, CommandError, CommandParser
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
    UploadedFile,
)

from cms.snippets.dashboard_data import DashboardData


class Command(BaseCommand):
    """Delete all users and personal data from a copy of the database."""

    help = "Delete all users and personal data from a copy of the database (name ending in _scrub)."

    def add_arguments(self, parser: CommandParser) -> None:
        """Register command-line arguments."""
        parser.add_argument(
            "--ignore-value",
            action="append",
            default=[],
            help="A former username or email the leftover check doesn't look for, because it"
            ' equals ordinary content (e.g. "root" equals the title of Wagtail\'s root page).'
            " Can be repeated.",
        )

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
            former_values = {
                value.lower()
                for row in user_model.objects.values_list("username", "email")
                for value in row
                if value
            }

            # Log entries about the user accounts themselves; their label is the username
            ModelLogEntry.objects.filter(
                content_type=ContentType.objects.get_for_model(user_model)
            ).delete()
            user_count = user_model.objects.count()
            _, deleted = user_model.objects.all().delete()
            self.stdout.write(f"Deleted {user_count} users, and with them:")
            for label, count in sorted(deleted.items()):
                if label != user_model._meta.label and count:
                    self.stdout.write(f"  {label}: {count}")

            self.scrub_without_foreign_keys(user_model)
            ignored = {value.lower() for value in options["ignore_value"]}
            self.check_for_leftovers(former_values - ignored)

    def scrub_without_foreign_keys(self, user_model: type) -> None:
        """Remove personal data that deleting users doesn't reach."""
        # Log entries have no constraint on user_id, so it would point at deleted users
        PageLogEntry.objects.update(user=None)
        ModelLogEntry.objects.update(user=None)
        Session.objects.all().delete()

        # The dashboard data uploader's username, stored as text
        DashboardData.objects.update(uploaded_by="")

        # Private values not linked to users. View-restriction passwords are
        # shared passwords for private pages, stored in plain text.
        TaskState.objects.update(comment="")  # workflow review comments
        for restriction in (PageViewRestriction, CollectionViewRestriction):
            restriction.objects.filter(restriction_type=restriction.PASSWORD).update(
                password="scrubbed"  # noqa: S106 (a placeholder)
            )
        FormSubmission.objects.all().delete()  # whatever visitors typed into forms
        UploadedFile.objects.all().delete()  # temporary bulk-upload files

        # Revisions are JSON copies of objects, so they still hold the deleted
        # users' IDs (e.g. a page's owner), which would break reverting to them,
        # plus the uploader's username and the comments saved with each revision
        user_fields = {
            field.name
            for model in apps.get_models()
            for field in model._meta.concrete_fields
            if isinstance(field, ForeignKey) and field.related_model is user_model
        }
        replacements = dict.fromkeys(user_fields)
        replacements |= {"uploaded_by": "", "wagtail_admin_comments": []}
        with connection.cursor() as cursor:
            for key, value in sorted(replacements.items()):
                cursor.execute(
                    f"UPDATE {Revision._meta.db_table}"  # noqa: S608
                    " SET content = jsonb_set(content, %s, %s::jsonb) WHERE content ? %s",
                    [[key], json.dumps(value), key],
                )

    def check_for_leftovers(self, former_values: set[str]) -> None:
        """Fail if a text value, or a string inside JSON, equals a former username or email.

        Code that copies account data copies whole values (e.g. ``uploaded_by``,
        log labels). Names or emails *within* longer text are editorial content,
        which is kept as it is, so they aren't searched for.
        """
        values = sorted(former_values)
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
                cursor.execute(query, [values])
                (found,) = cursor.fetchone()
                if found:
                    leftovers.append(f"{table}.{column} ({found} rows)")

        self.stdout.write(f"Leftover check: looked for {len(values)} usernames/emails")
        if leftovers:
            raise CommandError(
                "Former usernames or emails are still in: " + ", ".join(leftovers) + "."
            )
