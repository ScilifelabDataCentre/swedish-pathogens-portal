"""
Development settings.

These settings are intended for local development.
"""

from .base import *  # noqa: F401,F403
from .base import INSTALLED_APPS


DEBUG = True

# Allow all hosts in dev
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "0.0.0.0"]

