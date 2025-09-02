"""
Development settings.

These settings are intended for local development.
"""

from .base import *  # noqa: F401,F403


DEBUG = True

ADMIN_URL = "admin/"

# SECURITY
# ------------------------------------------------------------------------------
CSRF_TRUSTED_ORIGINS = ["http://localhost:8000", "http://127.0.0.1:8000"]
