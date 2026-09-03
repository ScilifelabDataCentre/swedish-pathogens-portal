"""Test settings: SQLite in-memory, no external services required."""

import os

# Provide a parseable DATABASE_URL so base.py can import without error.
# The actual DATABASES dict is overridden below.
os.environ.setdefault("DATABASE_URL", "sqlite://:memory:")

from .base import *  # noqa: F401,F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    },
}

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
