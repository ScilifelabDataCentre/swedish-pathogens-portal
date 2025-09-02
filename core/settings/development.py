"""
Development settings.

These settings are intended for local development.
"""

from .base import *  # noqa: F401,F403


DEBUG = True

ADMIN_URL = "admin/"


# DEVELOPMENT APPS
# ------------------------------------------------------------------------------
INSTALLED_APPS += ["django_extensions"]  # noqa: F405


# SECURITY
# ------------------------------------------------------------------------------
CSRF_TRUSTED_ORIGINS = ["http://localhost:8000", "http://127.0.0.1:8000"]
