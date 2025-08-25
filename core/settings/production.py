"""
Production settings.

These settings are intended for deployments.
"""

from .base import *  # noqa: F401,F403
from .base import env


DEBUG = False

# Use compressed and hashed static files storage
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"


# TODO: WhiteNoise
# https://docs.djangoproject.com/en/5.2/ref/settings/#storages)
# https://whitenoise.readthedocs.io/en/stable/django.html#add-compression-and-caching-support


# REVIEW: SECURITY HEADERS
# ------------------------------------------------------------------------------
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool(
    "SECURE_HSTS_INCLUDE_SUBDOMAINS", default=False
)
SECURE_HSTS_PRELOAD = env.bool("SECURE_HSTS_PRELOAD", default=False)
