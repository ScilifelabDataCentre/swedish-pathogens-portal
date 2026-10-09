"""Test settings on PostgreSQL, for behaviour SQLite cannot show.

SQLite's full-text index does not stem words; PostgreSQL's does, and search
results depend on it. ``DATABASE_URL`` must point at a PostgreSQL server where
the user may create databases: the test runner creates and drops its own
``test_<name>`` database next to the one named in the URL.
"""

from django.core.exceptions import ImproperlyConfigured

from .test import *  # noqa: F403

DATABASES = {"default": env.db("DATABASE_URL")}  # noqa: F405

if DATABASES["default"]["ENGINE"] != "django.db.backends.postgresql":
    msg = "core.settings.test_postgres needs DATABASE_URL to point at PostgreSQL."
    raise ImproperlyConfigured(msg)
