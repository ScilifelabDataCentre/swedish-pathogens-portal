"""Test settings: the PostgreSQL cluster dev and production already run on.

The database comes from ``base.py``, which reads ``DATABASE_URL``; the test
runner creates and drops its own ``test_<name>`` database next to the one named
there. Tests used to run on SQLite in memory, which needs no cluster but does
not stem indexed words, so search behaved differently under test than in
production and every search assertion proved the wrong thing.

This module matches unittest's ``test*.py`` discovery pattern, so the suite
loads it as a test module too and anything raised here fails the whole run
rather than one test. Only an unconditional misconfiguration may raise, which
the engine check is: ``django.contrib.postgres`` is in ``INSTALLED_APPS``, so
no settings module in this project can run on another engine.
"""

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403

if DATABASES["default"]["ENGINE"] != "django.db.backends.postgresql":  # noqa: F405
    msg = "core.settings.test needs DATABASE_URL to point at PostgreSQL."
    raise ImproperlyConfigured(msg)

DEBUG = False

MEDIA_ROOT = BASE_DIR / "media" / "test"  # noqa: F405
MEDIA_URL = "/media/test/"

# Private visitor DE session payloads (must stay outside MEDIA_ROOT).
LIVER_SESSION_ROOT = BASE_DIR / "private" / "test" / "liver_resource_sessions"  # noqa: F405

# Test settings for Wagtail.
WAGTAIL_SITE_NAME = "Test Portal"
WAGTAILADMIN_BASE_URL = "http://localhost:8000"

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# EMAIL
# ------------------------------------------------------------------------------
# base.py defines no mail configuration, so declare it here rather than leaving
# tests to inherit Django's smtp default. setup_test_environment() rewrites
# every MAILERS alias to locmem anyway; naming it explicitly keeps the module
# free of deprecated EMAIL_* names and makes the intent readable.
MAILERS = {
    "default": {"BACKEND": "django.core.mail.backends.locmem.EmailBackend"},
}
